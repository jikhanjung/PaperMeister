#!/usr/bin/env python3
"""P16 ①′: the re-judgement lane — pages the rule doubts, shown to a model
that browses the paper.

Without `--execute`: lists the doubted pages per paper and why the other
rows are not sent; `--dump` writes the request bodies. With `--execute`:
makes sure the server has the PDF and the workspace, submits one detect job
per paper (one item per doubted page), waits, and applies the replies —
kept / adjusted / merged / split / new / dismissed are derived from the
reply's `from` and `dismiss`, a person's rows are never touched (a reply that
would is recorded as `detect_conflicts_user`). Close the app first.

    python scripts/detect_figures.py --pilot tmp/p16_pilot.json
    python scripts/detect_figures.py --paper-ids 8803 --execute
    python scripts/detect_figures.py --pilot … --limit 10 --execute
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _print_utf8, open_database, target_files
from link_figures import cache_index, pages_of

from papermeister import figure_detect, figure_lane, figure_link, figure_prompts
from papermeister.nettls import install_system_trust
from papermeister.paths import OCR_JSON_DIR

_print_utf8()
install_system_trust()

PROMPT = figure_prompts.load('detect')
PROMPT_VERSION = PROMPT['version']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    parser.add_argument('--dump', help='write detect_<file id>.json here')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int, help='execute: at most this many papers')
    parser.add_argument('--no-wait', action='store_true')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')

    open_database(write=args.execute)
    from papermeister.preferences import get_client_id
    client_id = get_client_id()
    client = None
    if args.execute:
        from papermeister.figure_client import from_preferences
        client = from_preferences()
    index = cache_index(args.cache_dir)
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)

    totals: Counter = Counter()
    submitted = 0
    for pf in target_files(args):
        pages = pages_of(pf, args.cache_dir, index)
        if pages is None:
            totals['no cache'] += 1
            continue
        digest = figure_link.ocr_digest(pages)
        targets = figure_detect.detect_items(pf, pages, digest, PROMPT_VERSION, args.retry_errors)
        for _, why in targets.excluded:
            totals[f'excluded: {why}'] += 1
        if not targets.items:
            continue
        totals['pages due'] += len(targets.items)
        totals['papers due'] += 1
        body = figure_detect.detect_payload(pf, digest, targets, client_id, PROMPT)
        print(f'paper {pf.paper_id:>6}  {len(targets.items):>3} page(s): '
              + ', '.join(f"{it['page']}[{'+'.join(it['reasons'])}]" for it in targets.items[:6])
              + (' …' if len(targets.items) > 6 else '') + f'  {os.path.basename(pf.path)[:50]}')
        if args.dump:
            with open(os.path.join(args.dump, f'detect_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump(body, f, ensure_ascii=False, indent=1)
        if not args.execute:
            continue
        if args.limit and submitted >= args.limit:
            break
        submitted += 1
        try:
            figure_lane.ensure_workspace(client, pf, figure_link.workspace_payload(pf, pages), print)
            job = figure_lane.run_job(client, 'detect', body, print, wait=not args.no_wait)
        except Exception as exc:
            print(f'  FAILED: {type(exc).__name__}: {exc}')
            totals['server error'] += 1
            continue
        if job is None:
            continue
        results = figure_lane.results_by_key(job)
        for item in targets.items:
            reply = results.get(item['key'], {})
            result = reply.get('result') if reply.get('status') == 'done' else None
            applied = figure_detect.apply_detect(pf, item, targets.rows_by_item[item['key']], result,
                                                 digest, PROMPT_VERSION, reply.get('model') or 'gpt-6-astra')
            for name in ('kept', 'adjusted', 'merged', 'split', 'new', 'dismissed', 'conflicts', 'invalid', 'failed'):
                totals[name] += getattr(applied, name)
            print(f'    page {item["page"]:>4}  {reply.get("status", "missing"):<16} '
                  f'kept {applied.kept} adjusted {applied.adjusted} merged {applied.merged} split {applied.split} '
                  f'new {applied.new} dismissed {applied.dismissed} conflicts {applied.conflicts}'
                  + (f'  consulted {len(result.get("pages_consulted") or [])}p' if result else '')
                  + f'  {reply.get("elapsed_s", 0):.0f}s')
    print()
    for k, n in sorted(totals.items()):
        print(f'  {k:<28} {n:>6}')
    if not args.execute:
        print('Dry run — nothing sent. Add --execute to submit.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
