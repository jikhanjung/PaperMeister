#!/usr/bin/env python3
"""P11 — reset references for given papers (delete rows + un-check).

Deletes a paper's `Reference` rows and clears its `references_checked` flag so a
later `extract_references.py --scope all` re-parses it from scratch. Use after a
detection bug fix to redo papers that were extracted wrongly — e.g. the 化石
journal-issue volumes whose references were captured by the pre-fix single-
section detector (devlog 065).

This does NOT touch CitedWork nodes; run `normalize_works.py --execute` after the
re-extraction to reconcile cite_counts.

Convention: dry-run by default; pass --execute to write to the DB.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, Reference

# 化石 journal-issue volumes that already have references_checked=True from the
# pre-fix detector (last-heading→EOF / spaced-heading fallback). See devlog 065.
DEFAULT_IDS = [16, 17, 19, 20, 22, 24, 25, 26, 27, 28, 29]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--paper-ids', default='',
                        help='Comma-separated paper IDs (default: the 化石 set '
                        + ','.join(map(str, DEFAULT_IDS)) + ')')
    parser.add_argument('--execute', action='store_true',
                        help='Write to the DB (default: dry-run preview)')
    args = parser.parse_args()

    init_db()

    ids = ([int(x) for x in args.paper_ids.split(',') if x.strip()]
           if args.paper_ids else list(DEFAULT_IDS))
    print(f'Reset target paper-ids ({len(ids)}): {ids}')

    rows = list(Paper.select(Paper.id, Paper.title, Paper.references_checked)
                .where(Paper.id.in_(ids)))
    found = {p.id for p in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        print(f'  WARNING: not found in DB: {missing}')

    total_refs = 0
    for p in sorted(rows, key=lambda x: x.id):
        n = Reference.select().where(Reference.citing_paper == p.id).count()
        total_refs += n
        title = ' '.join((p.title or '').split())[:42]
        print(f'  paper={p.id:>4} checked={int(p.references_checked)} '
              f'refs={n:>4} | {title}')

    if not args.execute:
        print(f'\nDRY-RUN (no --execute). Would delete {total_refs} Reference '
              f'rows and clear references_checked on {len(found)} papers.')
        return

    del_refs = (Reference.delete()
                .where(Reference.citing_paper.in_(list(found))).execute())
    upd = (Paper.update(references_checked=False)
           .where(Paper.id.in_(list(found))).execute())
    print(f'\nDeleted {del_refs} Reference rows; cleared references_checked on '
          f'{upd} papers.')
    print('Next: python scripts/extract_references.py --scope all --workers 3 '
          '--execute')


if __name__ == '__main__':
    main()
