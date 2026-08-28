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


class PageBudget:
    """Keeps at most `limit` OCR pages in flight at once.

    A wrapper job is a whole PDF, so counting *papers* in flight measures
    nothing: twelve papers at this library's median of 13 pages is 156 pages
    queued against a server that asks for twelve. That is what the first run
    here did, and the cost landed on the other machine sharing the server.

    The app's Process window has always worked in pages (`min_queued_pages`);
    this is the same idea with a plain semaphore. A paper bigger than the whole
    budget still runs — alone — rather than deadlocking against a limit it can
    never fit under.
    """

    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self._in_flight = 0
        self._free = threading.Condition()

    def acquire(self, pages: int):
        with self._free:
            while self._in_flight and self._in_flight + pages > self.limit:
                self._free.wait()
            self._in_flight += pages

    def release(self, pages: int):
        with self._free:
            self._in_flight -= pages
            self._free.notify_all()


def other_active_clients():
    """How many *other* clients have work on the server right now.

    Counted from the job list rather than from `active_clients`, because the
    two differ in the case that matters. `active_clients` may or may not
    include this machine depending on whether a previous run's jobs are still
    finishing, and being wrong either way is costly: count itself as another
    client and the batch takes half the share it should; miss a client and it
    takes twice. Every job carries the `client_id` that submitted it, so the
    question can just be answered.
    """
    from papermeister.ocr import wrapper_list_jobs
    from papermeister.preferences import get_client_id

    mine = get_client_id()
    jobs = wrapper_list_jobs()
    if not jobs:
        return None            # empty list also means "could not ask"
    return len({
        job.get('client_id') for job in jobs
        if job.get('status') in ('processing', 'queued')
        and job.get('client_id') and job.get('client_id') != mine
    })


def recommended_queue_depth():
    """Pages to keep in flight: this client's share of the server.

    `wrapper_get_stats()` identifies us, so wrapper 0.2.4 answers with our own
    share rather than the whole machine — 6 of 12 while another PC is working.
    That is the number to use, and it is the server's to decide.

    It is still cross-checked against the job list. Not out of distrust: an
    older wrapper does not know the `client_id` parameter and quietly answers
    with the whole server, and a batch this long is exactly the thing that
    should not silently take it. The lower of the two is safe under both.
    """
    try:
        from papermeister.ocr import is_wrapper_mode, wrapper_get_stats
        if not is_wrapper_mode():
            return 6
        stats = wrapper_get_stats()
        share = int(stats.get('recommended_concurrency') or 0)
        capacity = int(stats.get('concurrency') or 0) or share or 6
        others = other_active_clients()
        if others is None:
            others = int(stats.get('active_clients') or 0)
    except Exception:
        return 6

    even_split = capacity // (others + 1)
    depth = max(1, min(share or even_split, even_split))
    sharing = f' with {others} other client(s)' if others else ' (nobody else on it)'
    print(f'Server does {capacity} pages at a time, shared{sharing} — '
          f'this client takes {depth}.')
    return depth


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
    budget = PageBudget(depth)
    total_pages = sum(count for _, count in targets)
    print(f'Re-OCR of {len(targets)} paper(s), {total_pages:,} pages, '
          f'{depth} page(s) in flight at a time.')
    print('Interrupt whenever you like — re-running resumes from what is left.')
    print()

    started = time.time()
    tally = {'done': 0, 'failed': 0, 'pages': 0}
    lock = threading.Lock()

    def convert(paper_file, page_count, index):
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
            return
        finally:
            budget.release(page_count)
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
    with ThreadPoolExecutor(max_workers=max(1, depth)) as pool:
        futures = [
            pool.submit(convert, paper_file, count, index)
            for index, (paper_file, count) in enumerate(targets, start=1)
        ]
        for _ in as_completed(futures):
            pass

    print()
    print(f'Converted {tally["done"]}, failed {tally["failed"]}, '
          f'in {(time.time() - started) / 60:.0f} min.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
