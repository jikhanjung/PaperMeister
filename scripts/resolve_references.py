#!/usr/bin/env python3
"""P11 — resolve parsed references to papers we own (Phase 1).

For each Reference, try to link it to a held Paper:
  1. DOI exact match (normalized) against Paper.doi / PaperBiblio.doi.
  2. Title match: token-overlap candidate generation, then score by title
     similarity + year agreement + first-author surname.

held vs cited-only falls out of this: `resolved_paper` set => we own it;
null => external (cited-only).

The matching logic lives in `papermeister.references` (shared with the
desktop's post-extraction auto-resolve). This pass is re-runnable. Convention:
dry-run unless --execute.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Reference, db
from papermeister.references import build_resolution_index, resolve_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--threshold', type=float, default=0.7,
                        help='Min title score to accept a non-DOI match')
    parser.add_argument('--min-tokens', type=int, default=2,
                        help='Min shared title tokens to consider a candidate')
    parser.add_argument('--reresolve', action='store_true',
                        help='Recompute even references already resolved')
    parser.add_argument('--execute', action='store_true',
                        help='Write resolution to the DB (default: dry-run)')
    args = parser.parse_args()

    init_db()
    index = build_resolution_index()
    print(f"Held papers indexed: {len(index['papers'])} | DOIs: {len(index['doi_map'])}")

    q = Reference.select()
    if not args.reresolve:
        q = q.where(Reference.match_method == '')
    refs = list(q)
    print(f'References to resolve: {len(refs)}')

    updates = []  # (ref_id, paper_id, method, score)
    counts = {'doi': 0, 'title': 0, 'none': 0}
    for r in refs:
        pid, method, score = resolve_one(
            r.doi, r.title, r.year, r.authors_json, index,
            threshold=args.threshold, min_tokens=args.min_tokens)
        counts[method] = counts.get(method, 0) + 1
        updates.append((r.id, pid, method, score))

    print(f"\nResolved by DOI:   {counts['doi']}")
    print(f"Resolved by title: {counts['title']}")
    print(f"Unresolved:        {counts['none']}")

    if not args.execute:
        print('\nDRY-RUN (no --execute). Sample title matches:')
        shown = 0
        for ref_id, pid, method, score in updates:
            if method == 'title' and shown < 15:
                r = Reference.get_by_id(ref_id)
                title = index['papers'][pid]['title']
                print(f'  ref="{(r.title or r.raw_text)[:50]}" -> '
                      f'paper={pid} "{title[:50]}" (score={score})')
                shown += 1
        return

    with db.atomic():
        for ref_id, pid, method, score in updates:
            Reference.update(
                resolved_paper=pid, match_method=method, match_score=score
            ).where(Reference.id == ref_id).execute()
    print('\nWritten to DB.')


if __name__ == '__main__':
    main()
