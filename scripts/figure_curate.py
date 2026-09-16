#!/usr/bin/env python3
"""P16 review: record a person's decision about stored figures.

    python scripts/figure_curate.py confirm  --figure-ids 12,13 --reason "plate box right"
    python scripts/figure_curate.py dismiss  --figure-ids 40 --reason "journal logo"
    python scripts/figure_curate.py restore  --figure-ids 40 --reason "…"
    python scripts/figure_curate.py rename   --figure-ids 41 --name "Plate III" --reason "OCR read II"
    python scripts/figure_curate.py set-bbox --figure-ids 41 --bbox 60,110,940,900 --reason "right column left out"
    python scripts/figure_curate.py merge    --figure-ids 41,42,43 --reason "one plate, facing pages"
    python scripts/figure_curate.py replay   --record tmp/p16_curation/20260916.json

Targets are `--figure-ids` (the `#id` on the review sheet) or `--keys
file:page:x0,y0,x1,y1 …` (space-separated — what the sheet prints before rows are stored). Nothing
is written without `--execute`; the dry run shows the change. Every applied
operation is appended to the day's record under the data directory
(`tmp/p16_curation/YYYYMMDD.json`) so that `replay` can land the same
decisions after re-assembly or re-OCR — rows are found again by identity, not
id. Close the app first: the database has one writer.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _print_utf8, open_database

from papermeister.paths import DATA_DIR

_print_utf8()

RECORD_DIR = os.path.join(DATA_DIR, 'tmp', 'p16_curation')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('op', choices=('confirm', 'dismiss', 'restore', 'rename', 'set-bbox', 'merge', 'replay'))
    parser.add_argument('--figure-ids', help='comma-separated Figure ids')
    parser.add_argument('--keys', nargs='+', help='file:page:x0,y0,x1,y1 keys, space-separated')
    parser.add_argument('--name', default='', help='rename: the printed name')
    parser.add_argument('--bbox', help='set-bbox: x0,y0,x1,y1 in page permille')
    parser.add_argument('--reason', default='', help='why — required, goes into the record')
    parser.add_argument('--record', help='replay: the record file; otherwise where to append '
                                         f'(default {RECORD_DIR}/YYYYMMDD.json)')
    parser.add_argument('--execute', action='store_true', help='write to the database')
    args = parser.parse_args()

    open_database(write=args.execute)
    from papermeister import figure_curation as cur
    from papermeister.models import Figure
    if not Figure.table_exists():
        print('error: no figures are stored yet — run scripts/assemble_figures.py --execute first', file=sys.stderr)
        return 2

    today = os.path.join(RECORD_DIR, datetime.datetime.now().strftime('%Y%m%d') + '.json')
    record = args.record or today

    if args.op == 'replay':
        if not args.record:
            parser.error('replay needs --record')
        entries = cur.load_record(args.record)
        print(f'{len(entries)} recorded decision(s) in {args.record}')
        for line in cur.replay(entries, today if args.execute else None, args.execute):
            print(line)
        if not args.execute:
            print('Dry run — nothing written. Add --execute to apply.')
        return 0

    ids = [int(x) for x in (args.figure_ids or '').split(',') if x.strip()]
    keys = list(args.keys or [])
    try:
        rows = cur.find_rows(ids, keys)
        bbox = [int(v) for v in args.bbox.split(',')] if args.bbox else None
        plan = cur.plan(args.op, rows, args.reason, name=args.name, bbox=bbox)
    except (cur.CurationError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2

    print(f'{args.op} — {args.reason}')
    for line in plan.describe():
        print(line)
    if args.execute:
        cur.apply(plan, record)
        print(f'Written. Recorded in {record}')
    else:
        print('Dry run — nothing written. Add --execute to apply.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
