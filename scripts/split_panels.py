#!/usr/bin/env python3
"""P16 ③: the panel lane — for now, only what happens before the server.

Lists which figures the panel stage is due on and why the others are not
(a lane that "did nothing, no error" is what fsis EC §6-9 warns about),
re-attaches panels whose entries changed by label (`--rematch --execute`),
and with `--dump` writes the request items so the shape can be read.
Nothing is sent — ocrserver's side (P02) is not built yet.

    python scripts/split_panels.py --pilot tmp/p16_pilot.json
    python scripts/split_panels.py --paper-ids 664 --dump tmp/p16_panels
    python scripts/split_panels.py --pilot … --rematch --execute
    python scripts/split_panels.py --pilot … --include-maps --retry-errors
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _print_utf8, open_database, target_files

from papermeister import figure_panels, figure_prompts

_print_utf8()

PROMPT = figure_prompts.load('panels')
PROMPT_VERSION = PROMPT['version']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--dump', help='write panels_<file id>.json (the request items) here')
    parser.add_argument('--rematch', action='store_true', help='re-attach panels whose entries changed')
    parser.add_argument('--include-maps', action='store_true')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--execute', action='store_true', help='write (rematch only)')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')

    open_database(write=args.execute)
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
    totals: Counter = Counter()
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
                else:
                    print(f'    #{row.id} would re-attach')
    print()
    for key, n in sorted(totals.items()):
        print(f'  {key:<28} {n:>6}')
    if args.rematch and not args.execute:
        print('Dry run — nothing written. Add --execute to re-attach.')
    print('Nothing sent: the server side of ③ is not built yet.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
