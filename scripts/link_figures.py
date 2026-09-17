#!/usr/bin/env python3
"""P16 ②: the caption lane.

Without `--execute`: builds, for each chosen paper, what the caption stage
would send (the workspace and the request), prints sizes and why each figure
is or is not due, and with `--dump` writes the JSON bodies. Read-only.

With `--execute`: for each paper with figures due, makes sure the server has
the PDF and the paper's workspace, submits one link job, waits for it (the
worker calls the model at most once every few minutes — a paper takes
minutes, thirty papers take hours; `--no-wait` submits and returns), checks
the reply against the request and the paper, and writes what survives. A
skipped or rejected figure keeps what it had and counts an attempt.
`--collect` applies finished jobs from earlier runs instead of submitting.
Close the app first: the database has one writer.

    python scripts/link_figures.py --pilot tmp/p16_pilot.json
    python scripts/link_figures.py --paper-ids 664,992 --dump tmp/p16_link
    python scripts/link_figures.py --paper-ids 664 --execute
    python scripts/link_figures.py --pilot … --limit 30 --execute
    python scripts/link_figures.py --collect --execute
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _CACHE_HASH, _print_utf8, load_pages, open_database, target_files

from papermeister import figure_lane, figure_link, figure_prompts, ocr_layout
from papermeister.nettls import install_system_trust
from papermeister.paths import OCR_JSON_DIR

_print_utf8()
install_system_trust()

PROMPT = figure_prompts.load('link')
PROMPT_VERSION = PROMPT['version']


def cache_index(cache_dir: str) -> dict:
    out = {}
    for name in os.listdir(cache_dir):
        m = _CACHE_HASH.search(name)
        if m:
            out.setdefault(m.group(1), name)
    return out


def pages_of(pf, cache_dir: str, index: dict):
    name = index.get(pf.hash[:8])
    pages = load_pages(os.path.join(cache_dir, name)) if name else None
    if not pages or not any(ocr_layout.is_structured(t) for t in pages):
        return None
    return pages


def apply_reply(pf, pages, targets, request, job_item: dict, totals: Counter) -> None:
    """Validate one paper's reply and write it; say what happened."""
    status = job_item.get('status')
    if status != 'done' or not isinstance(job_item.get('result'), dict):
        # No usable reply: every figure that was due counts an attempt.
        applied = figure_link.apply_link(targets, figure_link.LinkCheck(), {}, request['ocr_digest'],
                                         PROMPT_VERSION, 'gpt-6-astra')
        totals[f'item {status}'] += 1
        print(f'  paper {pf.paper_id:>6}  {status}: {job_item.get("error", "")[:120]}  '
              f'(attempt counted on {applied.failed})')
        return
    result = job_item['result']
    check = figure_link.validate_link_result(request, result, pages, {str(r.id): r for r in targets.due})
    applied = figure_link.apply_link(targets, check, result, request['ocr_digest'], PROMPT_VERSION,
                                     job_item.get('model') or 'gpt-6-astra')
    totals['written'] += applied.written
    totals['unchanged'] += applied.unchanged
    totals['failed (skipped/rejected)'] += applied.failed
    totals['reviewed'] += applied.reviewed
    print(f'  paper {pf.paper_id:>6}  written {applied.written}  unchanged {applied.unchanged}  '
          f'skipped {len(check.skipped)}  rejected {len(check.rejected)}  review {len(check.review)}  '
          f'pages consulted {len(result.get("pages_consulted") or [])}  '
          f'{job_item.get("elapsed_s", 0):.0f}s')
    for fid, why in check.rejected:
        print(f'      rejected #{fid}: {why}')
    for fid, reasons in check.review.items():
        print(f'      review   #{fid}: {", ".join(reasons)}')


def collect(client, args, index) -> int:
    """Apply finished link jobs from earlier runs (review category 2)."""
    from papermeister.models import PaperFile
    totals: Counter = Counter()
    for job in client.jobs(kind='link'):
        if job.get('status') not in ('done', 'done_with_errors'):
            continue
        full = client.job('link', job['job_id'])
        for key, item in figure_lane.results_by_key(full).items():
            prefix = key.split('@')[0]
            pf = PaperFile.select().where(PaperFile.hash.startswith(prefix) & ~PaperFile.path.endswith('.json')).first()
            if pf is None:
                totals['no such file'] += 1
                continue
            pages = pages_of(pf, args.cache_dir, index)
            if pages is None:
                continue
            digest = figure_link.ocr_digest(pages)
            targets = figure_link.link_targets(pf, digest, PROMPT_VERSION)
            if not targets.due:
                totals['nothing due (already applied?)'] += 1
                continue
            request = figure_link.link_payload(pf, pages, targets, digest, client.client_id, PROMPT)
            if request['items'][0]['key'] != key:
                totals['stale key (text or prompt changed)'] += 1
                continue
            if args.execute:
                apply_reply(pf, pages, targets, request, item, totals)
            else:
                print(f'  paper {pf.paper_id:>6}  would apply job {job["job_id"]} ({item.get("status")})')
                totals['would apply'] += 1
    for k, n in sorted(totals.items()):
        print(f'  {k:<32} {n:>6}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    parser.add_argument('--dump', help='write workspace_<id>.json and link_<id>.json per paper here')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--execute', action='store_true', help='submit to the server and write replies')
    parser.add_argument('--limit', type=int, help='execute: at most this many papers')
    parser.add_argument('--no-wait', action='store_true', help='execute: submit only; apply later with --collect')
    parser.add_argument('--collect', action='store_true', help='apply finished jobs from earlier runs')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot and not args.collect:
        parser.error('give --paper-ids or --pilot (or --collect)')

    open_database(write=args.execute)
    from papermeister.preferences import get_client_id
    client_id = get_client_id()
    index = cache_index(args.cache_dir)
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
    client = None
    if args.execute or args.collect:
        from papermeister.figure_client import from_preferences
        client = from_preferences()
    if args.collect:
        return collect(client, args, index)

    totals: Counter = Counter()
    sizes: list[tuple[int, int, int]] = []
    submitted = 0
    for pf in target_files(args):
        pages = pages_of(pf, args.cache_dir, index)
        if pages is None:
            totals['no cache'] += 1
            continue
        digest = figure_link.ocr_digest(pages)
        targets = figure_link.link_targets(pf, digest, PROMPT_VERSION, args.retry_errors)
        for _, why in targets.excluded:
            totals[f'excluded: {why}'] += 1
        totals['due'] += len(targets.due)
        totals['context'] += len(targets.context)
        if not targets.due:
            totals['papers with nothing due'] += 1
            continue
        totals['papers due'] += 1
        request = figure_link.link_payload(pf, pages, targets, digest, client_id, PROMPT)
        workspace = figure_link.workspace_payload(pf, pages)
        if args.execute:
            if args.limit and submitted >= args.limit:
                break
            submitted += 1
            print(f'paper {pf.paper_id}  {os.path.basename(pf.path)[:60]}  due {len(targets.due)}')
            try:
                figure_lane.ensure_workspace(client, pf, workspace, print)
                job = figure_lane.run_job(client, 'link', request, print, wait=not args.no_wait)
            except Exception as exc:  # one paper's server trouble must not stop the run
                print(f'  FAILED: {type(exc).__name__}: {exc}')
                totals['server error'] += 1
                continue
            if job is not None:
                item = figure_lane.results_by_key(job).get(request['items'][0]['key'], {'status': 'missing'})
                apply_reply(pf, pages, targets, request, item, totals)
            continue
        req_bytes = len(json.dumps(request, ensure_ascii=False).encode('utf-8'))
        ws_bytes = len(json.dumps(workspace, ensure_ascii=False).encode('utf-8'))
        sizes.append((len(pages), req_bytes, ws_bytes))
        print(f'  paper {pf.paper_id:>6}  {len(pages):>4} pages  due {len(targets.due):>3}  context {len(targets.context):>2}  '
              f'request {req_bytes / 1024:6.1f} KB  workspace {ws_bytes / 1024:7.1f} KB  '
              f"hints plate {len(request['items'][0]['hints']['plate_pages'])} expl {len(request['items'][0]['hints']['explanation_pages'])}  "
              f'{os.path.basename(pf.path)[:60]}')
        if args.dump:
            with open(os.path.join(args.dump, f'link_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump(request, f, ensure_ascii=False, indent=1)
            with open(os.path.join(args.dump, f'workspace_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump(workspace, f, ensure_ascii=False)

    print()
    for key, n in sorted(totals.items()):
        print(f'  {key:<32} {n:>6}')
    if sizes:
        req = sorted(s[1] for s in sizes)
        ws = sorted(s[2] for s in sizes)
        print(f'  request KB   median {req[len(req) // 2] / 1024:.1f}  max {req[-1] / 1024:.1f}  '
              f'total {sum(req) / 1024 / 1024:.1f} MB')
        print(f'  workspace KB median {ws[len(ws) // 2] / 1024:.1f}  max {ws[-1] / 1024:.1f}  '
              f'total {sum(ws) / 1024 / 1024:.1f} MB')
    if not args.execute:
        print('Dry run — nothing sent. Add --execute to submit.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
