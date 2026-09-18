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


def apply_reply(pf, pages, targets, request, replies: dict, totals: Counter) -> None:
    """Validate a paper's replies (one per request item) and write them; say what happened."""
    existing = {str(r.id): r for r in targets.due}
    check = figure_link.LinkCheck()
    consulted: set[int] = set()
    elapsed = 0.0
    model = 'gpt-6-astra'
    for item in request['items']:
        reply = replies.get(item['key'], {'status': 'missing'})
        status = reply.get('status')
        if status != 'done' or not isinstance(reply.get('result'), dict):
            totals[f'item {status}'] += 1
            print(f'  paper {pf.paper_id:>6}  item {item.get("part", [1, 1])[0]}/{item.get("part", [1, 1])[1]} '
                  f'{status}: {str(reply.get("error", ""))[:120]}')
            continue
        result = reply['result']
        check.merge(figure_link.validate_link_result(item, result, pages, existing))
        consulted |= set(result.get('pages_consulted') or [])
        elapsed += float(reply.get('elapsed_s') or 0)
        model = reply.get('model') or model
    # Figures no item answered for count an attempt (apply_link does that).
    applied = figure_link.apply_link(targets, check, {}, request['ocr_digest'], PROMPT_VERSION, model)
    totals['written'] += applied.written
    totals['unchanged'] += applied.unchanged
    totals['failed (skipped/rejected/no reply)'] += applied.failed
    totals['reviewed'] += applied.reviewed
    copied = figure_link.propagate_link(pf)
    if copied:
        totals['copied to same-PDF entries'] += copied
    print(f'  paper {pf.paper_id:>6}  written {applied.written}  unchanged {applied.unchanged}  '
          f'skipped {len(check.skipped)}  rejected {len(check.rejected)}  review {len(check.review)}  '
          f'no reply {applied.failed - len(check.skipped) - len(check.rejected)}  '
          f'pages consulted {len(consulted)}  {elapsed:.0f}s over {len(request["items"])} item(s)')
    for fid, why in check.rejected:
        print(f'      rejected #{fid}: {why}')
    for fid, reasons in check.review.items():
        print(f'      review   #{fid}: {", ".join(reasons)}')


def _file_of(replies: dict):
    """The PaperFile the reply's figure ids belong to, or None."""
    from papermeister.models import Figure
    for item in replies.values():
        result = item.get('result') or {}
        for f in (result.get('figures') or []) + (result.get('skipped') or []):
            fid = str(f.get('figure_id', ''))
            if fid.isdigit():
                row = Figure.get_or_none(Figure.id == int(fid))
                if row is not None:
                    return row.paper_file
    return None


def recheck(args, index) -> int:
    """Re-run the printed-text checks on linked rows; rewrite their reasons."""
    from papermeister.models import Figure
    totals: Counter = Counter()
    for pf in target_files(args):
        pages = pages_of(pf, args.cache_dir, index)
        if pages is None:
            continue
        rows = list(Figure.select().where((Figure.paper_file == pf.id) & Figure.linked_at.is_null(False)))
        for row in rows:
            before = json.loads(row.uncertain_reasons_json or '[]')
            now = figure_link.recheck_printed(row, pages)
            changed = ({r for r in before if r in (figure_link.CAPTION_NOT_PRINTED, figure_link.DESCRIPTION_NOT_PRINTED)}
                       != set(now))
            totals['linked rows'] += 1
            if changed:
                totals['would change' if not args.execute else 'changed'] += 1
                if args.execute:
                    figure_link.apply_recheck(row, pages)
            for r in now:
                totals[f'now: {r}'] += 1
    for k, n in sorted(totals.items()):
        print(f'  {k:<32} {n:>6}')
    if not args.execute:
        print('Dry run — nothing written. Add --execute to rewrite the reasons.')
    return 0


def collect(client, args, index) -> int:
    """Apply finished link jobs from earlier runs (review category 2)."""
    from papermeister.models import PaperFile
    totals: Counter = Counter()
    jobs = client.jobs(kind='link')
    print(f'{len(jobs)} link job(s) on the server for this client: '
          + ', '.join(f'{k} {n}' for k, n in sorted(Counter(j.get("status") for j in jobs).items())))
    for job in jobs:
        if job.get('status') not in ('done', 'done_with_errors'):
            continue
        full = client.job('link', job['job_id'])
        replies = figure_lane.results_by_key(full)
        # The file is the one whose rows the reply names — twins of one PDF
        # share the hash prefix, and a twin's reply applied to the wrong entry
        # counts attempts on figures it never mentioned (2026-09-18).
        found = _file_of(replies)
        if found is None:
            prefix = next(iter(replies), '').split('@')[0]
            found = PaperFile.select().where(PaperFile.hash.startswith(prefix) & ~PaperFile.path.endswith('.json')).first()
        for pf in ([found] if found else []):
            pages = pages_of(pf, args.cache_dir, index)
            if pages is None:
                continue
            digest = figure_link.ocr_digest(pages)
            targets = figure_link.link_targets(pf, digest, PROMPT_VERSION)
            if not targets.due:
                totals['nothing due (already applied?)'] += 1
                continue
            request = None
            # Jobs submitted before the 40-figure split carry the unsplit key:
            # try that shape too (10**6 = everything in one item).
            for per_item in sorted({args.per_item, figure_link.MAX_ITEM_WEIGHT, 40, 20, 10, 10 ** 6}, reverse=True):
                candidate = figure_link.link_payload(pf, pages, targets, digest, client.client_id, PROMPT, per_item)
                if any(it['key'] in replies for it in candidate['items']):
                    request = candidate
                    break
            if request is None:
                totals['stale key (text, prompt or item split changed)'] += 1
                continue
            keys = [it['key'] for it in request['items']]
            if args.execute:
                apply_reply(pf, pages, targets, request, replies, totals)
            else:
                print(f'  paper {pf.paper_id:>6}  would apply job {job["job_id"]} '
                      f'({sum(1 for k in keys if replies.get(k, {}).get("status") == "done")}/{len(keys)} items done)')
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
    parser.add_argument('--recheck', action='store_true',
                        help='re-run the printed-text checks on already linked figures (after the checks changed)')
    parser.add_argument('--per-item', type=int, default=figure_link.MAX_ITEM_WEIGHT,
                        help=f'answer weight per request item — a plate counts {figure_link.PLATE_WEIGHT}, a body figure 1 '
                             f'(default {figure_link.MAX_ITEM_WEIGHT}; smaller for a paper whose sessions drop)')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot and not args.collect:
        parser.error('give --paper-ids or --pilot (or --collect)')
    if args.recheck and not (args.paper_ids or args.pilot):
        parser.error('--recheck needs --paper-ids or --pilot')

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
    if args.recheck:
        return recheck(args, index)

    totals: Counter = Counter()
    sizes: list[tuple[int, int, int]] = []
    submitted = 0
    seen_hashes: set[str] = set()
    for pf in target_files(args):
        if pf.hash in seen_hashes:
            # The same PDF under another library entry: one paper, one call.
            # Its rows get the reply by propagation when the first entry is applied.
            totals['same PDF as an earlier entry (propagated)'] += 1
            continue
        seen_hashes.add(pf.hash)
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
        request = figure_link.link_payload(pf, pages, targets, digest, client_id, PROMPT, args.per_item)
        workspace = figure_link.workspace_payload(pf, pages)
        if args.execute:
            if args.limit and submitted >= args.limit:
                break
            submitted += 1
            print(f'paper {pf.paper_id}  {os.path.basename(pf.path)[:60]}  due {len(targets.due)} '
                  f'in {len(request["items"])} item(s)')
            try:
                figure_lane.ensure_workspace(client, pf, workspace, print)
                job = figure_lane.run_job(client, 'link', request, print, wait=not args.no_wait)
            except Exception as exc:  # one paper's server trouble must not stop the run
                print(f'  FAILED: {type(exc).__name__}: {exc}')
                totals['server error'] += 1
                continue
            if job is not None:
                apply_reply(pf, pages, targets, request, figure_lane.results_by_key(job), totals)
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
