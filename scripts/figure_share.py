#!/usr/bin/env python3
"""P16: figure results ↔ cache JSON (and the Zotero sibling attachment).

`--export`: write each paper's figures into its cache JSON `figures` key and,
when `zotero_upload_ocr_json` is on, push the JSON to the sibling in place.
`--import`: land the `figures` block of each paper's cache JSON on this
library's rows (matched by identity; a person's rows are left alone; an
export made against other OCR text is ignored). The lanes and figure_curate
export after every change; this is for backfill and for a second machine.

    python scripts/figure_share.py --export --pilot tmp/p16_pilot.json --execute
    python scripts/figure_share.py --import --paper-ids 664 --execute
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _print_utf8, open_database, target_files

from papermeister import figure_share
from papermeister.nettls import install_system_trust

_print_utf8()
install_system_trust()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export', action='store_true')
    mode.add_argument('--import', dest='do_import', action='store_true')
    parser.add_argument('--no-push', action='store_true', help='export: write the JSON only, no Zotero')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')

    open_database(write=args.execute)
    totals: Counter = Counter()
    for pf in target_files(args):
        if args.export:
            if not args.execute:
                totals['would export'] += 1
                continue
            try:
                outcome = figure_share.write_to_cache(pf, push=not args.no_push)
                totals['exported'] += 1
                if outcome:
                    totals[f'sibling {outcome}'] += 1
            except Exception as exc:
                totals['failed'] += 1
                print(f'  paper {pf.paper_id:>6}  FAILED {type(exc).__name__}: {exc}')
        else:
            if not args.execute:
                totals['would import'] += 1
                continue
            report = figure_share.import_from_cache(pf)
            print(f'  paper {pf.paper_id:>6}  {report}')
            totals['created'] += report.created
            totals['updated'] += report.updated
            totals['left alone'] += report.protected
            if report.skipped_reason:
                totals[f'skipped: {report.skipped_reason}'] += 1
    print()
    for k, n in sorted(totals.items()):
        print(f'  {k:<48} {n:>6}')
    if not args.execute:
        print('Dry run — nothing written. Add --execute.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
