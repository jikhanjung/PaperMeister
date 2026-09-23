"""Keep the figure server busy for days, one Zotero collection at a time.

The three model stages are serial on the server and an item is minutes, so
a library's worth of figures is measured in days. This runs unattended: it
lands whatever finished, tops the queue back up, and walks the collections
in tree order — a collection, then its sub-collections, then the next.

    python scripts/figure_queue.py --days 5 --execute            # the whole Zotero tree, in order
    python scripts/figure_queue.py --collections 1,78 --execute  # these collections only
    python scripts/figure_queue.py --status                      # what it would do, and where it is

Per pass, in this order:
  1. collect — finished link / panels replies land in the DB (and the cache JSON)
  2. panels  — figures whose captions are cut into entries go for splitting
  3. link    — the next papers of the plan are assembled and their captions asked for

The queue is kept near `--max-queue` items, not filled to the brim: a
shorter queue is easier to abandon, and a reply that lands changes what the
next paper needs. A PDF longer than `--max-pages` is left out — an abstract
volume is a day of server time and a handful of real figures.

**The desktop app must be closed**: this writes the DB, and SQLite takes one
writer. Stop it with Ctrl-C or by creating the file named by `--stop-file`;
it picks up where it left off (the plan's cursor lives in
`<data>/figure_queue.json`).
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
from papermeister.paths import DATA_DIR, OCR_JSON_DIR  # noqa: E402
from scripts.assemble_figures import collection_files  # noqa: E402

STATE_PATH = os.path.join(DATA_DIR, 'figure_queue.json')
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


def submit_link(client, pf, pages, prompt, per_item: int) -> int:
    """Ask for this paper's captions. Returns the items submitted."""
    digest = figure_link.ocr_digest(pages)
    targets = figure_link.link_targets(pf, digest, prompt['version'])
    if not targets.due:
        return 0
    request = figure_link.link_payload(pf, pages, targets, digest, client.client_id, prompt, per_item)
    figure_lane.ensure_workspace(client, pf, figure_link.workspace_for(pf, pages, request), lambda m: None)
    reply = client.submit('link', request)
    reading = request.get('reading_pages')
    log(f'  link   paper {pf.paper_id:>6}  {len(targets.due):>3} figure(s) in {len(request["items"])} item(s)'
        + (f', reading {len(reading)}/{len(pages)} pages' if reading else ', whole text')
        + f'  job {reply["job_id"][:8]}')
    return len(request['items'])


def submit_panels(client, pf, prompt) -> int:
    """Ask for the splits this paper's captioned figures are now due."""
    targets = figure_panels.split_targets(pf, prompt['version'])
    for row in targets.rematch:
        figure_panels.rematch(row)
    if targets.rematch:
        figure_share.write_to_cache(pf)
    if not targets.due:
        return 0
    figure_lane.ensure_pdf(client, pf, lambda m: None)
    items = [figure_panels.panel_item(row, prompt['version']) for row in targets.due]
    body = {'client_id': client.client_id, 'file_hash': pf.hash, 'items': items, 'prompt': prompt,
            'options': {'model': 'gpt-6-astra', 'effort': 'high', 'dpi': figure_panels.RENDER_DPI}}
    reply = client.submit('panels', body)
    log(f'  panels paper {pf.paper_id:>6}  {len(items):>3} figure(s)  job {reply["job_id"][:8]}')
    return len(items)


# ── the loop ─────────────────────────────────────────────────────────

def queue_depth(client) -> int:
    return sum(j.get('total', 0) - j.get('done', 0)
               for j in client.jobs() if j.get('status') in ('queued', 'processing'))


def panels_candidates(paper_ids: list[int], prompt_version: str, limit: int) -> list:
    """Files whose captioned figures are due for splitting, papers first come."""
    from papermeister.models import PaperFile
    out = []
    for pid in paper_ids:
        for pf in PaperFile.select().where((PaperFile.paper == pid) & (PaperFile.status == 'processed')
                                           & PaperFile.path.endswith('.pdf')):
            targets = figure_panels.split_targets(pf, prompt_version)
            if targets.due or targets.rematch:
                out.append(pf)
                break
        if len(out) >= limit:
            break
    return out


def run(args) -> int:
    from papermeister.figure_client import from_preferences
    init_db()
    client = from_preferences()
    link_prompt = figure_prompts.load('link')
    panels_prompt = figure_prompts.load('panels')

    collections = plan_collections(args.collections)
    state = load_state()
    done_collections = set(state.get('done_collections', []))
    touched = list(state.get('touched_papers', []))          # papers whose link was asked for
    log(f'plan: {len(collections)} collection(s), {len(done_collections)} already walked; '
        f'queue cap {args.max_queue} items, page cap {args.max_pages or "none"}')
    if args.status:
        depth = queue_depth(client)
        log(f'server queue: {depth} item(s) outstanding')
        for folder in collections:
            mark = 'done' if folder.id in done_collections else '    '
            log(f'  {mark} {folder.id:>5} {folder.name[:50]}')
        return 0

    deadline = datetime.now() + timedelta(days=args.days) if args.days else None
    totals: Counter = Counter()
    while True:
        if args.stop_file and os.path.exists(args.stop_file):
            log('stop file found — stopping')
            break
        if deadline and datetime.now() >= deadline:
            log('time budget spent — stopping')
            break

        # 1. land what finished
        from papermeister.figure_pipeline import collect_finished
        report = collect_finished(client)
        if report.jobs:
            log(f'collected {report.summary()}')
            totals['captions'] += report.link_written
            totals['panels'] += report.panels_written

        # 2. top the queue up
        depth = queue_depth(client)
        submitted = 0
        if depth < args.max_queue:
            room = args.max_queue - depth
            # panels first: those papers are further along, and a split is
            # the last thing a paper needs.
            for pf in panels_candidates(touched, panels_prompt['version'], limit=8):
                if submitted >= room:
                    break
                try:
                    submitted += submit_panels(client, pf, panels_prompt)
                except Exception as exc:
                    log(f'  panels paper {pf.paper_id}: {type(exc).__name__}: {exc}')
                    totals['errors'] += 1
            while submitted < room:
                pf = next_paper(collections, done_collections, state, args)
                if pf is None:
                    break
                pages = pages_of(pf)
                if pages is None:
                    totals['no structured OCR'] += 1
                    continue
                try:
                    assemble(pf, pages)
                    n = submit_link(client, pf, pages, link_prompt, args.per_item)
                except Exception as exc:
                    log(f'  link   paper {pf.paper_id}: {type(exc).__name__}: {exc}')
                    totals['errors'] += 1
                    continue
                submitted += n
                if n and pf.paper_id not in touched:
                    touched.append(pf.paper_id)
            state['touched_papers'] = touched[-2000:]
            state['done_collections'] = sorted(done_collections)
            save_state(state)

        if submitted:
            log(f'queue now ~{depth + submitted} item(s) ({submitted} submitted this pass)')
        elif not report.jobs:
            log(f'nothing to do; queue {depth} item(s) — sleeping {args.sleep}s')
        time.sleep(args.sleep if (submitted or report.jobs) else max(args.sleep, IDLE_SLEEP))
    for k, n in sorted(totals.items()):
        log(f'  {k:<24} {n:>6}')
    return 0


def next_paper(collections, done_collections, state, args):
    """The next paper of the plan, walking collections in order."""
    cursor = state.get('cursor') or {}
    for folder in collections:
        if folder.id in done_collections:
            continue
        files = state.get('files_cache', {}).get(str(folder.id))
        if files is None:
            pdfs = collection_files(str(folder.id))
            files = [pf.id for pf in pdfs if _within_pages(pf, args.max_pages)]
            state.setdefault('files_cache', {})[str(folder.id)] = files
            log(f'collection {folder.id} {folder.name[:40]}: {len(files)} PDF(s) within the page cap')
        index = cursor.get(str(folder.id), 0)
        while index < len(files):
            from papermeister.models import PaperFile
            pf = PaperFile.get_or_none(PaperFile.id == files[index])
            index += 1
            cursor[str(folder.id)] = index
            state['cursor'] = cursor
            if pf is not None:
                return pf
        done_collections.add(folder.id)
        log(f'collection {folder.id} {folder.name[:40]}: walked')
    return None


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
    parser.add_argument('--status', action='store_true', help='say where the plan stands and exit')
    parser.add_argument('--execute', action='store_true', help='actually submit and write')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    args = parser.parse_args()
    if not args.execute and not args.status:
        parser.error('add --execute to run, or --status to look')
    if args.stop_file and os.path.exists(args.stop_file):
        os.remove(args.stop_file)
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
