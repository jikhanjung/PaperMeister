"""Keep the figure server busy for days, one Zotero collection at a time.

The three model stages are serial on the server and an item is minutes, so
a library's worth of figures is measured in days. This runs unattended: it
lands whatever finished, tops the queue back up, and walks the collections
in tree order — a collection, then its sub-collections, then the next.

    python scripts/figure_queue.py --days 5 --execute            # the whole Zotero tree, in order
    python scripts/figure_queue.py --collections 1,78 --execute  # these collections only
    python scripts/figure_queue.py --status                      # what it would do, and where it is

Work goes in **batches** — the pilot list, then each collection in tree order —
and a batch's stages are kept together: its captions (link), then its splits
(panels), and only when both are asked for does the next batch's link start.
The server works first in, first out; a batch's splits must not end up
behind the next batch's captions.

Per pass:
  1. collect — finished link / panels replies land in the DB (and the cache JSON)
  2. for the first unfinished batch: submit the splits its landed captions made due,
     then more of its link; a batch whose link and splits are all asked for is done

The queue is kept near `--max-queue` items, not filled to the brim: a
shorter queue is easier to abandon, and a reply that lands changes what the
next paper needs. A PDF longer than `--max-pages` is left out — an abstract
volume is a day of server time and a handful of real figures.

Two ways to run it:

    python scripts/figure_queue.py --tick --execute   # one pass and exit — Task Scheduler, every 5 min
    python scripts/figure_queue.py --execute          # one process, a pass every 2 min, for days

The tick is the normal way (`scripts/install-figure-tick.ps1` registers it):
a tick that dies costs one interval, and the machine coming back from a
reboot or a power cut picks the work up without anyone. Either way the
plan's cursor lives in `<data>/figure_queue.json`, and a lock
(`<data>/figure_queue.lock`, held by the OS) keeps two passes from running
at once — a tick that finds the last one still busy just exits.

The desktop app may stay open. The DB is in WAL mode with a busy timeout, so
the two take turns writing; a reply both of them land is applied once (the
second finds nothing due); and the app's Process Figures waits for items a
pass already put on the server instead of submitting them again.

To pause: create the file named by `--stop-file` (`<data>/figure_queue.stop`).
Ticks skip while it exists and leave it in place; delete it to resume. A
long-running loop stops at its next pass and removes it when started again.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister import (  # noqa: E402
    figure_lane,
    figure_link,
    figure_panels,
    figure_prompts,
    figure_share,
)
from papermeister.database import init_db  # noqa: E402
from papermeister.nettls import install_system_trust  # noqa: E402
from papermeister.paths import DATA_DIR, LOG_DIR, OCR_JSON_DIR  # noqa: E402
from scripts.assemble_figures import collection_files  # noqa: E402

# The institution's network intercepts TLS; its root CA is in the OS store,
# not in certifi. Without this every Zotero call raises
# CERTIFICATE_VERIFY_FAILED — which is what ended the first overnight run.
install_system_trust()

STATE_PATH = os.path.join(DATA_DIR, 'figure_queue.json')
LOCK_PATH = os.path.join(DATA_DIR, 'figure_queue.lock')
#: A pass that finds nothing to do waits this long before looking again.
IDLE_SLEEP = 300


def log(message: str) -> None:
    print(f'{datetime.now():%m-%d %H:%M:%S}  {message}', flush=True)


# ── the plan ─────────────────────────────────────────────────────────

def zotero_collections() -> list:
    """The Zotero collections in tree order: each root, then its children."""
    from papermeister.models import Folder, Source
    out = []

    def walk(folder):
        out.append(folder)
        for child in Folder.select().where(Folder.parent == folder.id).order_by(Folder.name):
            walk(child)

    for src in Source.select().where(Source.source_type == 'zotero').order_by(Source.id):
        for root in Folder.select().where((Folder.source == src.id) & Folder.parent.is_null()).order_by(Folder.name):
            walk(root)
    return out


def plan_collections(spec: str | None) -> list:
    from papermeister.models import Folder
    if not spec:
        return zotero_collections()
    out = []
    for token in spec.split(','):
        token = token.strip()
        if not token:
            continue
        folder = Folder.get_or_none(Folder.id == int(token)) if token.isdigit() else None
        if folder is None:
            matches = [f for f in Folder.select() if token.lower() in (f.name or '').lower()]
            if len(matches) != 1:
                raise SystemExit(f'{token!r} matches {len(matches)} collections')
            folder = matches[0]
        out.append(folder)
    return out


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


# ── one paper ────────────────────────────────────────────────────────

def pages_of(pf) -> list[str] | None:
    from papermeister import ocr_layout
    path = figure_share.cache_path(pf)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    pages = [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]
    return pages if any(ocr_layout.is_structured(t) for t in pages) else None


def assemble(pf, pages) -> int:
    """Store what the rule finds; returns how many rows the file now has."""
    from papermeister import figure_store, figures
    from papermeister.models import Figure
    assembled = figure_store.with_placeholders(figures.assemble_document(pages))
    figure_store.apply_plan(figure_store.plan_store(pf, assembled))
    return Figure.select().where(Figure.paper_file == pf.id).count()


def submit_link(client, pf, pages, prompt, per_item: int, outstanding: set[str]) -> int:
    """Ask for this paper's captions. Returns the items submitted."""
    digest = figure_link.ocr_digest(pages)
    targets = figure_link.link_targets(pf, digest, prompt['version'])
    if not targets.due:
        return 0
    request = figure_link.link_payload(pf, pages, targets, digest, client.client_id, prompt, per_item)
    if any(it['key'] in outstanding for it in request['items']):
        return 0                      # this paper's captions are already being asked for
    figure_lane.ensure_workspace(client, pf, figure_link.workspace_for(pf, pages, request), lambda m: None)
    reply = client.submit('link', request)
    outstanding.update(it['key'] for it in request['items'])
    reading = request.get('reading_pages')
    log(f'  link   paper {pf.paper_id:>6}  {len(targets.due):>3} figure(s) in {len(request["items"])} item(s)'
        + (f', reading {len(reading)}/{len(pages)} pages' if reading else ', whole text')
        + f'  job {reply["job_id"][:8]}')
    return len(request['items'])


def submit_panels(client, pf, prompt, outstanding: set[str]) -> int:
    """Ask for the splits this paper's captioned figures are now due —
    except those already waiting on the server."""
    targets = figure_panels.split_targets(pf, prompt['version'])
    pending = _pending_rematch(targets.rematch)
    for row in pending:
        figure_panels.rematch(row)
    if pending:
        figure_share.write_to_cache(pf)
    items = [figure_panels.panel_item(row, prompt['version']) for row in targets.due]
    items = [it for it in items if it['key'] not in outstanding]
    if not items:
        return 0
    figure_lane.ensure_pdf(client, pf, lambda m: None)
    outstanding.update(it['key'] for it in items)
    body = {'client_id': client.client_id, 'file_hash': pf.hash, 'items': items, 'prompt': prompt,
            'options': {'model': 'gpt-6-astra', 'effort': 'high', 'dpi': figure_panels.RENDER_DPI}}
    reply = client.submit('panels', body)
    log(f'  panels paper {pf.paper_id:>6}  {len(items):>3} figure(s)  job {reply["job_id"][:8]}')
    return len(items)


# ── the loop ─────────────────────────────────────────────────────────

def queue_depth(client) -> int:
    return sum(j.get('total', 0) - j.get('done', 0)
               for j in client.jobs() if j.get('status') in ('queued', 'processing'))


class TrackedClient:
    """The figure client, plus the jobs this run submitted itself.

    The server lists at most 1000 jobs (100 by default, 2026-10-06) and has
    no paging; a job that leaves the list is invisible to collecting and to
    the "anything outstanding?" check, so its reply never lands and its batch
    closes early. Every job this run submits is remembered by id
    (`state['open_jobs']`) and fetched directly when the list no longer
    shows it, until it is finished and collected."""

    def __init__(self, client, state: dict):
        self._client = client
        self._open = state.setdefault('open_jobs', {})      # job_id -> kind

    def __getattr__(self, name):
        return getattr(self._client, name)

    def submit(self, kind: str, body: dict) -> dict:
        reply = self._client.submit(kind, body)
        if reply.get('job_id'):
            self._open[reply['job_id']] = kind
        return reply

    def jobs(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        listed = self._client.jobs(kind=kind, status=status)
        seen = {j.get('job_id') for j in listed}
        for job_id, job_kind in list(self._open.items()):
            if job_id in seen or (kind and job_kind != kind):
                continue
            try:
                full = self._client.job(job_kind, job_id)
            except Exception as exc:   # gone from the server, or the server away: try next pass
                log(f'  job {job_id[:8]} not readable: {type(exc).__name__}: {exc}')
                continue
            summary = {k: v for k, v in full.items() if k not in ('items', 'worker')}
            summary.setdefault('job_id', job_id)
            summary.setdefault('kind', job_kind)
            if summary.get('status') in ('failed', 'cancelled'):
                self._open.pop(job_id, None)   # nothing will come of it; collect reads done jobs only
            if status is None or summary.get('status') == status:
                listed.append(summary)
        return listed

    def forget(self, job_ids) -> None:
        """Jobs finished and collected: no longer this run's to watch."""
        for job_id in job_ids:
            self._open.pop(job_id, None)


def outstanding_keys(client) -> set[str]:
    """Item keys already waiting on the server. A figure whose split is
    queued is still "due" in the DB until the reply lands — without this
    check every pass submitted it again (2026-09-24/25: one paper's two
    figures, fifty times, and the queue full of them starved everything)."""
    keys: set[str] = set()
    for job in client.jobs():
        if job.get('status') not in ('queued', 'processing'):
            continue
        for item in client.job(job['kind'], job['job_id']).get('items', []):
            if item.get('status') in ('queued', 'processing') and 'key' in item:
                keys.add(item['key'])
    return keys


# ── batches ──────────────────────────────────────────────────────────
#
# A batch is the pilot list or one collection. Batches go in order: while a
# batch has captions or splits still to ask for, the next batch's link
# waits. The server is first in, first out, so submitting the next batch's
# link ahead of this batch's splits would put every split behind a day of
# captions (it did: the pilot's splits waited behind collection 1's link for
# four days). A batch that has asked for everything and only waits on its
# captions does not hold the next one back: with the queue capped, its
# splits wait behind at most a queue's worth.

class Batch:
    def __init__(self, key: str, name: str, file_ids: list[int]):
        self.key, self.name, self.file_ids = key, name, file_ids


def plan_batches(args, state) -> list[Batch]:
    from scripts.assemble_figures import target_files
    batches: list[Batch] = []
    cache = state.setdefault('files_cache', {})
    if args.pilot and os.path.isfile(args.pilot):
        if 'pilot' not in cache:
            class _A:
                pilot = args.pilot
                paper_ids = None
                collection = None
                # The pilot was chosen by hand and its long monographs are the
                # point of it (the 231- and 291-page plate volumes) — no cap.
                max_pages = 0
            cache['pilot'] = [pf.id for pf in target_files(_A)]
        batches.append(Batch('pilot', 'pilot', cache['pilot']))
    for folder in plan_collections(args.collections):
        key = str(folder.id)
        if key not in cache:
            cache[key] = [pf.id for pf in collection_files(key) if _within_pages(pf, args.max_pages)]
        batches.append(Batch(key, folder.name, cache[key]))
    return batches


def outstanding_hashes(outstanding: set[str]) -> set[str]:
    """File-hash prefixes with a link item waiting (key `hash12@digest12@version#i/n`)."""
    return {k.split('@')[0] for k in outstanding if k.count('@') == 2}


def batch_state(batch: Batch, state, outstanding: set[str], prompt_version: str) -> dict:
    """What a batch still needs: link papers not yet asked for, link replies
    not yet landed, splits not yet asked for."""
    from papermeister.models import PaperFile
    cursor = (state.get('cursor') or {}).get(batch.key, 0)
    waiting = outstanding_hashes(outstanding)
    link_out = panels_due = 0
    # Every file of the batch, not only the walked ones: a file has splits due
    # only if its captions are in, which is true of the pilot's files before
    # the walk reaches them (their link ran long ago).
    for fid in batch.file_ids:
        pf = PaperFile.get_or_none(PaperFile.id == fid)
        if pf is None:
            continue
        if pf.hash[:12] in waiting:
            link_out += 1
            continue
        targets = figure_panels.split_targets(pf, prompt_version)
        # A split already waiting on the server is asked for: it is ahead of
        # anything submitted after it, which is all the ordering needs. A
        # re-attach that could not map its labels is a person's to decide
        # (re-cut or fix the labels) — not work the batch waits for; left
        # in, it held the pilot batch open forever (2026-09-30, 29 rows).
        if _pending_rematch(targets.rematch) or any(
                figure_panels.panel_item(r, prompt_version)['key'] not in outstanding for r in targets.due):
            panels_due += 1
    return {'link_left': max(0, len(batch.file_ids) - cursor), 'link_out': link_out, 'panels_due': panels_due}


def status_lines(batches: list[Batch], state, done: set, outstanding: set[str], prompt_version: str,
                 upcoming: int = 3) -> list[str]:
    """Where the plan stands: the batches done in one line, the batches under
    way in full, the next few by size, the rest in one line.

    It used to list the first twelve batches — once the run was a hundred
    batches in, all twelve read `done` and the batch actually under way (a
    689-file collection, half walked) never showed (2026-10-08)."""
    finished = [b for b in batches if b.key in done]
    rest = [b for b in batches if b.key not in done]
    lines = [f'done   {len(finished)} batch(es), {sum(len(b.file_ids) for b in finished)} file(s)']
    if not rest:
        return lines + ['nothing left']
    # The first batch not done is being worked on, and so is any after it
    # whose link has started (fill_queue goes on to the next batch while one
    # only waits on its captions).
    cursor = state.get('cursor') or {}
    started = 1
    while started < len(rest) and cursor.get(rest[started].key, 0):
        started += 1
    under_way, following = rest[:started], rest[started:]
    for now in under_way:
        st = batch_state(now, state, outstanding, prompt_version)
        total = len(now.file_ids)
        lines.append(f'now    {now.key:>6} {now.name[:40]:<40} {total:>5} file(s): '
                     f'link asked {total - st["link_left"]}/{total}, waiting {st["link_out"]}, '
                     f'splits due {st["panels_due"]}')
    for batch in following[:upcoming]:
        lines.append(f'next   {batch.key:>6} {batch.name[:40]:<40} {len(batch.file_ids):>5} file(s)')
    later = following[upcoming:]
    if later:
        lines.append(f'then   {len(later)} batch(es), {sum(len(b.file_ids) for b in later)} file(s)')
    return lines


def _pending_rematch(rows: list) -> list:
    """Rows whose panels can still be re-attached by label — not those a
    re-attach already failed on and flagged for a person."""
    flag = figure_panels.ENTRIES_CHANGED_UNMAPPED
    return [r for r in rows if flag not in json.loads(r.uncertain_reasons_json or '[]')]


def run(args) -> int:
    from papermeister.figure_client import from_preferences
    init_db()
    link_prompt = figure_prompts.load('link')
    panels_prompt = figure_prompts.load('panels')

    state = load_state()
    client = TrackedClient(from_preferences(), state)
    batches = plan_batches(args, state)
    done = set(state.get('done_batches', []))
    if not args.tick:                          # every five minutes it would only be noise
        log(f'plan: {len(batches)} batch(es), {len(done)} done; queue cap {args.max_queue} items, '
            f'page cap {args.max_pages or "none"}')
    if args.status:
        kinds = Counter((state.get('open_jobs') or {}).values())
        log(f'server queue: {queue_depth(client)} item(s) outstanding; this runner waits on '
            f'{sum(kinds.values())} job(s) ({", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"})')
        for line in status_lines(batches, state, done, outstanding_keys(client), panels_prompt['version']):
            log(f'  {line}')
        return 0

    if args.tick:
        return tick(args, client, batches, state, done, link_prompt, panels_prompt)

    deadline = datetime.now() + timedelta(days=args.days) if args.days else None
    totals: Counter = Counter()
    while True:
        if args.stop_file and os.path.exists(args.stop_file):
            log('stop file found — stopping')
            break
        if deadline and datetime.now() >= deadline:
            log('time budget spent — stopping')
            break
        busy = one_pass(client, batches, state, done, link_prompt, panels_prompt, args, totals)
        if busy is None:                       # the server away: wait, then try again
            time.sleep(max(args.sleep, IDLE_SLEEP))
            continue
        time.sleep(args.sleep if busy else max(args.sleep, IDLE_SLEEP))
    for k, n in sorted(totals.items()):
        log(f'  {k:<24} {n:>6}')
    return 0


def tick(args, client, batches, state, done: set, link_prompt, panels_prompt) -> int:
    """One pass, then exit — what Task Scheduler runs every few minutes.

    A runner that lives for days stops everything when it dies (2026-09-23:
    four hours in, an unhandled TLS error, nothing in the log) and has to be
    started again by hand after every reboot. A tick that dies costs one
    interval: the next one is a fresh process. Everything a pass needs is in
    the state file and the DB already, so a pass is the same code either way."""
    if args.stop_file and os.path.exists(args.stop_file):
        log(f'paused — {args.stop_file} exists; delete it to resume')
        return 0
    totals: Counter = Counter()
    one_pass(client, batches, state, done, link_prompt, panels_prompt, args, totals)
    return 1 if totals.get('errors') else 0


def one_pass(client, batches, state, done: set, link_prompt, panels_prompt, args,
             totals: Counter) -> bool | None:
    """Land what finished, top the queue up, save the state. True when
    something happened, False when there was nothing to do, None when the
    server could not be asked."""
    # 1. land what finished. A pass that throws (the server away, a
    # Zotero hiccup) must not end a run that has days to go.
    from papermeister.figure_pipeline import CollectReport, collect_finished
    order = list(state.get('settled_jobs', []))
    settled = set(order)
    try:
        report = collect_finished(client, skip_jobs=settled)
        # Oldest out first. `sorted(...)[-5000:]` dropped job ids by their
        # spelling — recent jobs among them, read again every pass after
        # (2026-10-09: 11 of the last two hours').
        order += [job_id for job_id in report.settled if job_id not in settled]
        settled |= report.settled
        state['settled_jobs'] = order[-5000:]
        client.forget(settled)
    except Exception as exc:
        log(f'collect failed: {type(exc).__name__}: {exc}')
        totals['errors'] += 1
        report = CollectReport()
    if report.jobs or report.link_missed:
        log(f'collected {report.summary()}')

    if over_budget(args):
        # A tick that spent its time landing replies leaves the topping-up to
        # the next one rather than run into it.
        save_state(state)
        log('tick budget spent after collecting — the next tick tops the queue up')
        return True

    # 2. top the queue up, batch by batch
    try:
        depth = queue_depth(client)
        outstanding = outstanding_keys(client)
    except Exception as exc:
        log(f'server unreachable: {type(exc).__name__}: {exc} — trying again later')
        totals['errors'] += 1
        save_state(state)
        return None
    room = max(0, args.max_queue - depth)
    submitted = fill_queue(client, batches, state, done, outstanding, room,
                           link_prompt, panels_prompt, args, totals)
    state['done_batches'] = sorted(done)
    save_state(state)

    if submitted:
        log(f'queue now ~{depth + submitted} item(s) ({submitted} submitted this pass)')
    elif not report.jobs:
        log(f'nothing to do; queue {depth} item(s)')
    return bool(submitted or report.jobs)


def over_budget(args) -> bool:
    """Past this tick's time? (`args.deadline` is a `time.monotonic()` value;
    the long-running loop has none.)"""
    deadline = getattr(args, 'deadline', None)
    return deadline is not None and time.monotonic() >= deadline


class RunLock:
    """One runner at a time, however it was started.

    Two passes at once would each see the other's items as not yet waiting
    and submit them again. The lock is the OS's on an open file, so it goes
    away with the process however the process ends — no stale lock file to
    clean up after a crash or a power cut."""

    def __init__(self, path: str):
        self.path = path
        self._f = None

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        f = open(self.path, 'a+')
        try:
            if os.name == 'nt':
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def release(self) -> None:
        if self._f is not None:
            self._f.close()          # closing the handle drops the lock
            self._f = None


def fill_queue(client, batches, state, done: set, outstanding: set, room: int,
               link_prompt, panels_prompt, args, totals) -> int:
    """One pass's submissions, batch by batch. Returns the items submitted."""
    submitted = 0
    for batch in batches:
        if batch.key in done:
            continue
        if over_budget(args) or room <= submitted:
            break
        st = batch_state(batch, state, outstanding, panels_prompt['version'])
        # splits of this batch go in as soon as its captions land
        if st['panels_due'] and room > submitted:
            submitted += submit_batch_panels(client, batch, state, panels_prompt, outstanding,
                                             room - submitted, totals)
        if st['link_left'] and room > submitted:
            submitted += submit_batch_link(client, batch, state, link_prompt, outstanding,
                                           room - submitted, args, totals)
        st = batch_state(batch, state, outstanding, panels_prompt['version'])
        if not st['link_left'] and not st['link_out'] and not st['panels_due']:
            done.add(batch.key)
            log(f'batch {batch.key} {batch.name[:40]}: captions and splits all asked for — next batch')
            continue
        # This batch still has work to put in: the next batch's link waits
        # for it. A batch that only waits on its own captions has nothing to
        # put in, and holding the next batch's link then drained the server
        # queue to nothing at every small batch (2026-10-09: 0 items, four
        # workers idle). Its splits, when the captions land, wait behind at
        # most a queue's worth (~1 h) — not the days the rule was made for.
        if st['link_left'] or st['panels_due']:
            break
    return submitted


def submit_batch_panels(client, batch, state, prompt, outstanding, room, totals) -> int:
    from papermeister.models import PaperFile
    submitted = 0
    for fid in batch.file_ids:
        if submitted >= room:
            break
        pf = PaperFile.get_or_none(PaperFile.id == fid)
        if pf is None:
            continue
        try:
            submitted += submit_panels(client, pf, prompt, outstanding)
        except Exception as exc:
            log(f'  panels paper {pf.paper_id}: {type(exc).__name__}: {exc}')
            totals['errors'] += 1
    return submitted


def submit_batch_link(client, batch, state, prompt, outstanding, room, args, totals) -> int:
    from papermeister.models import PaperFile
    cursor = state.setdefault('cursor', {})
    submitted = 0
    while submitted < room and not over_budget(args):
        index = cursor.get(batch.key, 0)
        if index >= len(batch.file_ids):
            break
        cursor[batch.key] = index + 1
        pf = PaperFile.get_or_none(PaperFile.id == batch.file_ids[index])
        if pf is None:
            continue
        pages = pages_of(pf)
        if pages is None:
            totals['no structured OCR'] += 1
            continue
        try:
            assemble(pf, pages)
            submitted += submit_link(client, pf, pages, prompt, args.per_item, outstanding)
        except Exception as exc:
            log(f'  link   paper {pf.paper_id}: {type(exc).__name__}: {exc}')
            totals['errors'] += 1
    return submitted


def _within_pages(pf, limit: int) -> bool:
    if not limit:
        return True
    path = figure_share.cache_path(pf)
    if not os.path.isfile(path):
        return False            # no OCR cache: nothing for the figure stages anyway
    try:
        with open(path, encoding='utf-8') as f:
            return len(json.load(f).get('pages') or []) <= limit
    except (OSError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--collections', help='comma-separated Folder ids or name fragments, in the order to '
                                              'process them (default: the whole Zotero tree, in tree order)')
    parser.add_argument('--pilot', default=os.path.join(DATA_DIR, 'tmp', 'p16_pilot.json'),
                        help='a pilot list to run as the first batch (default: <data>/tmp/p16_pilot.json if present; '
                             "'' to skip)")
    parser.add_argument('--days', type=float, default=0, help='stop after this many days (0 = until the plan ends)')
    parser.add_argument('--max-queue', type=int, default=120,
                        help='keep about this many items outstanding on the server (default 120 ≈ 12 hours)')
    parser.add_argument('--max-pages', type=int, default=200,
                        help='skip a PDF whose OCR cache has more pages (default 200; 0 = no limit)')
    parser.add_argument('--per-item', type=int, default=figure_link.MAX_ITEM_WEIGHT,
                        help='answer weight per link item (a plate counts 8)')
    parser.add_argument('--sleep', type=int, default=120, help='seconds between passes')
    parser.add_argument('--stop-file', default=os.path.join(DATA_DIR, 'figure_queue.stop'),
                        help='create this file to stop after the current pass')
    parser.add_argument('--tick', action='store_true',
                        help='one pass, then exit — for Task Scheduler (scripts/install-figure-tick.ps1). '
                             'The stop file pauses ticks instead of ending a run, and is left in place')
    parser.add_argument('--budget', type=int, default=240,
                        help='with --tick: stop starting new work after this many seconds (default 240)')
    parser.add_argument('--log', help='append the output to this file (with --tick: default '
                                      '<data>/logs/figure_queue.log — pythonw has no console)')
    parser.add_argument('--status', action='store_true', help='say where the plan stands and exit')
    parser.add_argument('--execute', action='store_true', help='actually submit and write')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    args = parser.parse_args()
    if not args.execute and not args.status:
        parser.error('add --execute to run, or --status to look')
    if args.tick and not args.log:
        args.log = os.path.join(LOG_DIR, 'figure_queue.log')
    if args.log:
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        sys.stdout = sys.stderr = open(args.log, 'a', encoding='utf-8', buffering=1)
    if args.status:
        return run(args)

    lock = RunLock(LOCK_PATH)
    if not lock.acquire():
        if not args.tick:                      # a tick finding the last one still busy is routine
            log(f'another runner holds {LOCK_PATH} — not starting')
        return 0
    try:
        if args.tick:
            args.deadline = time.monotonic() + args.budget
        elif args.stop_file and os.path.exists(args.stop_file):
            os.remove(args.stop_file)          # a run started by hand means go
        return run(args)
    except Exception:
        import traceback
        log('pass failed:\n' + traceback.format_exc())
        return 1
    finally:
        lock.release()


if __name__ == '__main__':
    sys.exit(main())
