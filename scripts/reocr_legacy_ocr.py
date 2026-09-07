#!/usr/bin/env python3
"""Re-OCR the papers whose cached OCR predates the layout-aware model.

The OCR server changed output format between 2026-04-09 and 2026-05-13: before,
a page came back as flat markdown; after, as HTML in which every block carries
what it is and where it sat. The Text tab uses the second form to show headings,
captions and figures, so papers processed in the April batch — 2,049 of them,
about 58,000 pages — still read as one flat column. Re-OCR is what fixes them;
nothing can recover the layout from the text alone.

Targets are worked out from the cache itself, not from a list: a paper is a
target while its cached JSON has no layout labels, and stops being one the
moment it does. So this is interruptible and resumable by construction — stop
it, run it again, and it picks up what is left.

    python scripts/reocr_legacy_ocr.py                    # what it would do
    python scripts/reocr_legacy_ocr.py --limit 5 --execute  # try a few first
    python scripts/reocr_legacy_ocr.py --execute --workers 4

Run it on the machine that owns the library (Windows), with the app closed.
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Verify TLS against the OS trust store: the lab network re-signs with its own
# root CA, which certifi does not carry. Must run before any pyzotero call.
from papermeister.nettls import install_system_trust

install_system_trust()

from papermeister.database import init_db
from papermeister.models import PaperFile
from papermeister.paths import OCR_JSON_DIR
from papermeister.preferences import get_pref
from papermeister.text_extract import ocr_json_filename, process_paper_file


def _print_utf8():
    """Let the console take non-ASCII titles.

    This library is half European and Japanese, and the Windows console
    defaults to cp949 here — printing a filename with an accent in it killed
    the run before it started.

    Line buffering goes on at the same time. This run takes hours and people
    watch it through a redirect or a tee, where block buffering shows nothing
    at all until it is over.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, ValueError):
            pass


_print_utf8()      # before anything can print a title with an accent in it


def cache_path(paper_file):
    """Where this PDF's OCR JSON lives, or None if the file has no hash."""
    try:
        return os.path.join(OCR_JSON_DIR, ocr_json_filename(paper_file))
    except Exception:
        return None


#: The label attribute that only the layout-aware model emits.
_MARKER = 'data-label='
_CHUNK = 1 << 16


def has_layout_labels(path):
    """Whether this cache file is from the layout-aware model.

    Scanned as a stream and stopped at the first hit rather than parsed. Four
    in five cache files are already converted and answer from their first
    chunk, which is the difference between a startup scan of ten thousand
    files taking seconds and taking minutes.
    """
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            tail = ''
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    return False
                if _MARKER in tail + chunk:
                    return True
                # Carry the boundary so a marker split across chunks is seen.
                tail = chunk[-len(_MARKER):]
    except OSError:
        return True            # unreadable: not a target, and not our problem


def page_count(path):
    """Pages in a cache file, or None if it is empty or unreadable.

    An empty cache is a failed OCR rather than an old one — a different queue,
    reachable from the app as "Retry", and not what this script is for.
    """
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    pages = data.get('pages') or []
    if not any((p.get('markdown') or '').strip() for p in pages):
        return None
    return len(pages)


def find_targets():
    """Processed PDFs whose cached OCR is the old flat-markdown form.

    Sorted shortest first: the tail of this library is 600-800 page plate
    volumes, and banking the quick ones first means an interrupted run has
    converted more papers rather than fewer.
    """
    candidates = list(
        PaperFile.select()
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash.is_null(False))
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
        )
    )
    print(f'Scanning {len(candidates):,} cached OCR files...', flush=True)
    started = time.time()

    targets = []
    for paper_file in candidates:
        path = cache_path(paper_file)
        if not path or not os.path.exists(path) or has_layout_labels(path):
            continue
        pages = page_count(path)
        if pages is None:
            continue
        targets.append((paper_file, pages))
    targets.sort(key=lambda pair: pair[1])
    print(f'  scanned in {time.time() - started:.0f}s', flush=True)
    return targets


def refresh_zotero_sibling(paper_file, log):
    """Replace the OCR JSON already attached in Zotero with the new one.

    The normal OCR path uploads a sibling only when there is not one yet, so a
    re-OCR leaves the old JSON in Zotero. That matters beyond tidiness: on a
    cache miss the app pulls the sibling back down rather than paying for OCR,
    which would quietly restore the flat version this run just replaced.
    """
    if not (paper_file.zotero_key and get_pref('zotero_upload_ocr_json', False)):
        return
    json_filename = ocr_json_filename(paper_file)
    sibling = (
        PaperFile.select()
        .where(
            (PaperFile.paper == paper_file.paper)
            & (PaperFile.path == json_filename)
            & (PaperFile.zotero_key.is_null(False))
        )
        .first()
    )
    if sibling is None:
        return          # nothing enrolled in Zotero; the local file is the copy

    user_id, api_key = get_pref('zotero_user_id', ''), get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        return
    from papermeister.ingestion import hash_file
    from papermeister.zotero_client import ZoteroClient

    path = os.path.join(OCR_JSON_DIR, json_filename)
    outcome = ZoteroClient(user_id, api_key).replace_attachment_file(sibling.zotero_key, path)
    if outcome in ('updated', 'unchanged'):
        new_hash = hash_file(path)
        if new_hash and new_hash != (sibling.hash or ''):
            sibling.hash = new_hash
            sibling.save()
    else:
        log(f'    Zotero sibling not replaced: {outcome}')


class PageQueue:
    """Keeps roughly `target` OCR pages outstanding on the server.

    A wrapper job is a whole PDF, so counting *papers* measures nothing:
    twelve papers at this library's median of 13 pages is 156 pages against a
    server that runs twelve. Pages are the unit.

    But the target is a **floor to submit up to, not a ceiling to stay under**
    — the same rule the app's Process window uses. The server admits only this
    client's share however much it is given, so anything past the share waits
    in our own queue and is admitted the instant a page finishes. Keeping that
    small buffer is what stops the share going idle between papers; holding
    strictly at or below it leaves slots empty every time a paper ends, which
    is visible as in-flight dipping 6 → 5 → 3 while the server has work to
    hand us.

    Submitting ahead does not take anything from the other machine. Admission
    is capped per client, so a longer queue here only ever lengthens our own.
    """

    def __init__(self, target: int):
        self.limit = max(1, target)
        self._outstanding = 0
        self._room = threading.Condition()

    def set_limit(self, target: int):
        """Change the target mid-run; waiters re-check against the new one."""
        with self._room:
            self.limit = max(1, target)
            self._room.notify_all()

    def ceiling(self) -> int:
        """How much to hold open, which is more than the share itself.

        A paper counts against this from the moment it is picked up, but only
        part of that time is spent on the OCR server: before it there is the
        PDF to fetch from Zotero, and after it the JSON to write and upload.
        Pages held during those phases are idle as far as the server is
        concerned, so aiming at exactly the share leaves it short — measured
        live as server-side outstanding sagging to 11 against a share of 12.

        The extra costs nothing. Admission is capped per client, so anything
        past the share waits in our own queue and goes in the instant a page
        finishes.
        """
        return self.limit + max(2, self.limit // 2)

    def acquire(self, pages: int):
        with self._room:
            while self._outstanding > self.ceiling():
                self._room.wait()
            self._outstanding += pages

    def release(self, pages: int):
        with self._room:
            self._outstanding -= pages
            self._room.notify_all()


def recommended_queue_depth():
    """Pages to keep in flight: this client's share, as the server states it.

    `wrapper_client_concurrency()` reads /api/stats with our id attached, so
    the wrapper counts us among its clients and answers with our share — 6 of
    12 while another machine is working. Enforcement is the server's; this is
    what keeps the local queue the right size rather than piling up pages that
    will only sit in its waiting list.
    """
    try:
        from papermeister.ocr import is_wrapper_mode, wrapper_client_concurrency
        if not is_wrapper_mode():
            return 6
        depth = wrapper_client_concurrency()
    except Exception:
        return 6
    print(f'This client keeps {depth} page(s) in flight.')
    return max(1, depth)


#: How often to re-ask the server for our share, in seconds. The app fixes its
#: target once per batch, which is fine for a batch that ends; this one runs
#: for days, across the other machine starting and finishing its own work.
_SHARE_REFRESH = 60


def follow_the_share(budget, stop):
    """Keep the page budget matched to what the server currently allots us.

    The share moves when clients come and go — 12 alone, 6 once a second
    machine attaches. Enforcement is the server's either way, so getting this
    wrong is never incorrect, only wasteful: too high and pages pile up in the
    server's waiting list, too low and our share sits idle for hours.
    """
    from papermeister.ocr import wrapper_client_concurrency

    while not stop.wait(_SHARE_REFRESH):
        try:
            share = wrapper_client_concurrency()
        except Exception as exc:
            # A blip while asking is not a reason to change how much we take.
            print(f'    could not re-check our share ({exc}); keeping {budget.limit}')
            continue
        if share and share != budget.limit:
            print(f'    share is now {share} page(s) (was {budget.limit})')
            budget.set_limit(share)


#: Consecutive failures that mean the server is gone rather than one paper
#: being awkward. Real per-paper failures are isolated; a run of them is not.
_OUTAGE_STREAK = 3

#: How long to wait for it to come back before giving up on this run. The work
#: is resumable, so stopping costs a re-run — spinning for hours costs a night.
_OUTAGE_PATIENCE = 900

#: Gap between health probes while waiting one out.
_OUTAGE_POLL = 15


def _server_answers(check_health) -> bool:
    """True once the server responds at all — the shape of the reply is the
    caller's problem, being reachable is this one's."""
    try:
        check_health()
    except Exception:
        return False
    return True


class ServerGate:
    """Holds the run still while the OCR server is refusing everything.

    Without this a proxy hiccup empties the whole queue in seconds: the batch
    keeps submitting into a server that rejects instantly, so every remaining
    paper "fails" without ever being tried. That is what happened on the first
    full run — 53 papers burned in the time it takes to POST them, none of
    which had reached the wrapper at all.

    Isolated failures still pass through untouched; only a streak of them is
    treated as an outage.
    """

    def __init__(self, patience: int = _OUTAGE_PATIENCE):
        self.patience = patience
        self.gave_up = False
        self._streak = 0
        self._lock = threading.Lock()
        self._clear = threading.Event()
        self._clear.set()

    def wait_if_down(self):
        """Block while an outage is being ridden out. True to keep going."""
        self._clear.wait()
        return not self.gave_up

    def note_success(self):
        with self._lock:
            self._streak = 0

    def note_failure(self) -> bool:
        """Record a failure; True if the caller should ride out an outage."""
        with self._lock:
            self._streak += 1
            if self._streak < _OUTAGE_STREAK or not self._clear.is_set():
                return False
            self._clear.clear()          # this thread runs the recovery wait
            return True

    def ride_out(self):
        from papermeister.ocr import check_health

        print(f'    {_OUTAGE_STREAK} failures in a row — treating the server as '
              f'down, waiting up to {self.patience // 60} min')
        deadline = time.time() + self.patience
        try:
            while time.time() < deadline:
                time.sleep(_OUTAGE_POLL)
                if not _server_answers(check_health):
                    continue
                print('    server is answering again — carrying on')
                with self._lock:
                    self._streak = 0
                return
            self.gave_up = True
            print(f'    still down after {self.patience // 60} min — stopping. '
                  f'Nothing is lost; re-run to pick up where this left off.')
        finally:
            self._clear.set()


def preview(everything, selected):
    """Report the whole backlog, then what this invocation would actually do."""
    pages = sum(count for _, count in everything)
    print(f'{len(everything)} paper(s) still on the old flat OCR, {pages:,} pages in total.')
    if not everything:
        return 0
    print(f'  shortest: {everything[0][1]} pages   longest: {everything[-1][1]} pages')

    if len(selected) != len(everything):
        chosen_pages = sum(count for _, count in selected)
        print(f'This run would take {len(selected)} of them ({chosen_pages:,} pages).')
    print()
    print('First few, shortest first:')
    for paper_file, count in selected[:10]:
        print(f'  {count:>4} pages  {os.path.basename(paper_file.path)[:70]}')
    print()
    print('Nothing was changed. Re-run with --execute to re-OCR them.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--execute', action='store_true',
                        help='actually re-OCR (default is a preview)')
    parser.add_argument('--limit', type=int,
                        help='stop after this many papers — use it for a trial run')
    parser.add_argument('--max-pages', type=int,
                        help='skip papers longer than this (the plate volumes)')
    parser.add_argument('--paper-ids', type=str,
                        help='comma-separated Paper ids — convert only these, '
                             'for retrying one that failed')
    parser.add_argument('--queue-pages', type=int,
                        help='OCR pages to keep in flight (default: what the '
                             'server has free)')
    args = parser.parse_args()

    init_db()
    everything = find_targets()
    targets = everything
    if args.paper_ids:
        wanted = {int(part) for part in args.paper_ids.split(',') if part.strip()}
        targets = [t for t in targets if t[0].paper_id in wanted]
        absent = wanted - {t[0].paper_id for t in targets}
        if absent:
            print(f'Not targets (already converted, or no legacy cache): '
                  f'{sorted(absent)}')
    if args.max_pages:
        dropped = [t for t in targets if t[1] > args.max_pages]
        targets = [t for t in targets if t[1] <= args.max_pages]
        if dropped:
            print(f'Skipping {len(dropped)} paper(s) over {args.max_pages} pages '
                  f'(--max-pages); they stay on the old OCR.')
    if args.limit:
        targets = targets[:args.limit]

    if not args.execute:
        return preview(everything, targets)

    if not targets:
        print('Nothing left to re-OCR.')
        return 0

    from papermeister.ocr import backend_label, ensure_workers_ready
    print(f'Checking {backend_label()}...')
    try:
        ensure_workers_ready()
    except RuntimeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    depth = args.queue_pages or recommended_queue_depth()
    budget = PageQueue(depth)
    total_pages = sum(count for _, count in targets)
    print(f'Re-OCR of {len(targets)} paper(s), {total_pages:,} pages, '
          f'{depth} page(s) in flight at a time.')
    print('Interrupt whenever you like — re-running resumes from what is left.')
    print()

    started = time.time()
    tally = {'done': 0, 'failed': 0, 'pages': 0}
    lock = threading.Lock()

    def convert(paper_file, page_count, index):
        if not gate.wait_if_down():
            return                      # the server never came back
        prefix = f'[{index}/{len(targets)}]'
        name = os.path.basename(paper_file.path)[:60]
        budget.acquire(page_count)
        print(f'{prefix} {name} ({page_count} pages)')
        try:
            # force: ignore the local cache *and* the Zotero sibling, both of
            # which hold the very output being replaced.
            process_paper_file(paper_file, force=True)
            refresh_zotero_sibling(paper_file, log=print)
        except Exception as exc:
            with lock:
                tally['failed'] += 1
            print(f'{prefix}   FAILED: {exc}')
            if gate.note_failure():
                gate.ride_out()
            return
        finally:
            budget.release(page_count)
        gate.note_success()
        with lock:
            tally['done'] += 1
            tally['pages'] += page_count
            elapsed = time.time() - started
            rate = tally['pages'] / elapsed * 60 if elapsed else 0
            left = total_pages - tally['pages']
            eta = f'{left / rate / 60:.1f} h' if rate else '?'
            print(f'{prefix}   done — {tally["done"]} converted, '
                  f'{rate:.0f} pages/min, ~{eta} left')

    # One thread per page of budget is the most that can ever be in flight
    # (a paper is at least one page); the budget, not the pool, is the limit.
    gate = ServerGate()
    stop_watching = threading.Event()
    watcher = threading.Thread(target=follow_the_share, args=(budget, stop_watching),
                               daemon=True)
    watcher.start()

    # The queue bounds the load; the pool only has to be wide enough never to
    # be the thing that stops it. Sized at one thread per page of share is not:
    # with one-page papers every thread is busy holding a page, so there is
    # nobody left to submit the paper that should be waiting behind them, and
    # the buffer silently never forms. Room is left for the share growing
    # mid-run too — it doubles when the other machine finishes.
    with ThreadPoolExecutor(max_workers=max(8, depth * 2 + 4)) as pool:
        futures = [
            pool.submit(convert, paper_file, count, index)
            for index, (paper_file, count) in enumerate(targets, start=1)
        ]
        for _ in as_completed(futures):
            pass
    stop_watching.set()

    print()
    print(f'Converted {tally["done"]}, failed {tally["failed"]}, '
          f'in {(time.time() - started) / 60:.0f} min.')
    if gate.gave_up:
        print('Stopped early: the OCR server stopped answering. '
              'Re-run when it is back — nothing was lost.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
