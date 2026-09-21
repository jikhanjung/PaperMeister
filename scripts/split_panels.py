#!/usr/bin/env python3
"""P16 ③: the panel lane.

Lists which figures the panel stage is due on and why the others are not
(a lane that "did nothing, no error" is what fsis EC §6-9 warns about).
`--rematch --execute` re-attaches panels whose entries changed, by label.
`--execute` (without `--rematch`) submits one panels job per paper with the
figures due, waits, checks each reply and writes the panels. Close the app.

    python scripts/split_panels.py --pilot tmp/p16_pilot.json
    python scripts/split_panels.py --paper-ids 664 --dump tmp/p16_panels
    python scripts/split_panels.py --paper-ids 664 --execute
    python scripts/split_panels.py --pilot … --rematch --execute
    python scripts/split_panels.py --pilot … --include-maps --retry-errors
    python scripts/split_panels.py --collect --execute        # apply finished jobs from earlier runs
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _print_utf8, open_database, target_files
from link_figures import share

from papermeister import figure_lane, figure_panels, figure_prompts
from papermeister.nettls import install_system_trust

_print_utf8()
install_system_trust()

PROMPT = figure_prompts.load('panels')
PROMPT_VERSION = PROMPT['version']


def apply_replies(pf, rows, items, results: dict, totals: Counter) -> None:
    _apply_replies(pf, rows, items, results, totals)
    share(pf, totals)


def _apply_replies(pf, rows, items, results: dict, totals: Counter) -> None:
    from papermeister.models import Figure
    for row, item in zip(rows, items, strict=True):
        reply = results.get(item['key'], {})
        result = reply.get('result') if reply.get('status') == 'done' else None
        siblings = Figure.select().where((Figure.paper_file == pf.id) & (Figure.page == row.page)
                                         & (Figure.id != row.id) & (Figure.dismissed == False)).count()  # noqa: E712
        check = figure_panels.validate_panel_result(item, result, siblings) if result else None
        applied = figure_panels.apply_panels(row, item, result, check, PROMPT_VERSION,
                                             reply.get('model') or 'gpt-6-astra')
        for name in ('written', 'unchanged', 'protected', 'failed', 'reviewed'):
            totals[name] += getattr(applied, name)
        print(f'    #{row.id:<6} {reply.get("status", "missing"):<16} '
              + (f'panels {len(check.panels)}  {check.why or ", ".join(check.review) or "ok"}' if check
                 else str(reply.get('error', ''))[:80])
              + f'  {reply.get("elapsed_s", 0):.0f}s')


def collect(client, args) -> int:
    """Apply finished panels jobs from earlier runs. The item key is `<figure id>@<panel_key>`."""
    from papermeister.models import Figure
    totals: Counter = Counter()
    jobs = client.jobs(kind='panels')
    print(f'{len(jobs)} panels job(s) on the server for this client: '
          + ', '.join(f'{k} {n}' for k, n in sorted(Counter(j.get("status") for j in jobs).items())))
    for job in jobs:
        if job.get('status') not in ('done', 'done_with_errors'):
            continue
        replies = figure_lane.results_by_key(client.job('panels', job['job_id']))
        rows, items = [], []
        for key in replies:
            fid = key.split('@')[0]
            row = Figure.get_or_none(Figure.id == int(fid)) if fid.isdigit() else None
            if row is None or row.dismissed:
                totals['no such figure'] += 1
                continue
            item = figure_panels.panel_item(row, PROMPT_VERSION)
            if item['key'] != key:
                totals['stale key (box, prompt or dpi changed)'] += 1
                continue
            if row.panel_key == item['key'].split('@', 1)[1] and row.panel_result_digest:
                totals['already applied'] += 1
                continue
            rows.append(row)
            items.append(item)
        if not rows:
            continue
        print(f'job {job["job_id"][:8]}  {len(rows)} figure(s)')
        if args.execute:
            apply_replies(rows[0].paper_file, rows, items, replies, totals)
        else:
            totals['would apply'] += len(rows)
    print()
    for k, n in sorted(totals.items()):
        print(f'  {k:<32} {n:>6}')
    if not args.execute:
        print('Dry run — nothing written. Add --execute to apply.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--dump', help='write panels_<file id>.json (the request items) here')
    parser.add_argument('--rematch', action='store_true', help='re-attach panels whose entries changed')
    parser.add_argument('--include-maps', action='store_true')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--figure-ids', help='comma-separated: only these figures (with --paper-ids)')
    parser.add_argument('--force', action='store_true',
                        help='ask the server to answer again instead of serving its cached reply — '
                             'for an item whose reply the checks rejected (same key, same bad answer otherwise)')
    parser.add_argument('--execute', action='store_true', help='submit and write (or, with --rematch, re-attach)')
    parser.add_argument('--limit', type=int, help='execute: at most this many papers')
    parser.add_argument('--no-wait', action='store_true')
    parser.add_argument('--collect', action='store_true', help='apply finished jobs from earlier runs')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot and not args.collect:
        parser.error('give --paper-ids or --pilot (or --collect)')

    open_database(write=args.execute)
    client = None
    if (args.execute and not args.rematch) or args.collect:
        from papermeister.figure_client import from_preferences
        from papermeister.preferences import get_client_id
        client = from_preferences()
        client_id = get_client_id()
    if args.collect:
        return collect(client, args)
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
    totals: Counter = Counter()
    submitted = 0
    for pf in target_files(args):
        t = figure_panels.split_targets(pf, PROMPT_VERSION, args.retry_errors, args.include_maps)
        totals['due'] += len(t.due)
        totals['rematch'] += len(t.rematch)
        for _, why in t.excluded:
            totals[f'excluded: {why}'] += 1
        if t.due or t.rematch:
            print(f'  paper {pf.paper_id:>6}  due {len(t.due):>3}  rematch {len(t.rematch):>2}  '
                  f'{os.path.basename(pf.path)[:60]}')
        if args.dump and t.due:
            with open(os.path.join(args.dump, f'panels_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump([figure_panels.panel_item(r, PROMPT_VERSION) for r in t.due], f,
                          ensure_ascii=False, indent=1)
        if args.rematch:
            for row in t.rematch:
                if args.execute:
                    done, note = figure_panels.rematch(row)
                    totals['rematched' if done else 'rematch: unmapped'] += 1
                    print(f'    #{row.id} {"ok " if done else "?? "} {note}')
                    share(pf, totals)
                else:
                    print(f'    #{row.id} would re-attach')
            continue
        if not (args.execute and t.due):
            continue
        if args.limit and submitted >= args.limit:
            break
        submitted += 1
        due = t.due
        if args.figure_ids:
            wanted = {int(x) for x in args.figure_ids.split(',')}
            due = [r for r in due if r.id in wanted]
            if not due:
                continue
        items = [figure_panels.panel_item(r, PROMPT_VERSION) for r in due]
        body = {'client_id': client_id, 'file_hash': pf.hash, 'items': items, 'prompt': PROMPT,
                'options': {'model': 'gpt-6-astra', 'effort': 'high', 'dpi': figure_panels.RENDER_DPI}}
        if args.force:
            body['force'] = True
        try:
            figure_lane.ensure_pdf(client, pf, print)
            job = figure_lane.run_job(client, 'panels', body, print, wait=not args.no_wait)
        except Exception as exc:
            print(f'  FAILED: {type(exc).__name__}: {exc}')
            totals['server error'] += 1
            continue
        if job is None:
            continue
        apply_replies(pf, t.due, items, figure_lane.results_by_key(job), totals)
    print()
    for key, n in sorted(totals.items()):
        print(f'  {key:<28} {n:>6}')
    if not args.execute:
        print('Dry run — nothing sent or written. Add --execute.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
