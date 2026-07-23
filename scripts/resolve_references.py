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

    # Re-resolve ONLY the held dimension. The external CitedWork layer (P12:
    # resolved_work + 'work-*' match_method) is preserved — a reference that
    # neither matches a held paper now nor was held before AND already points at
    # a CitedWork is left untouched, so we never overwrite a 'work-*' label with
    # 'none' or double-link resolved_work. When a ref becomes held we clear its
    # resolved_work (mutual exclusivity); dropped false-positives become
    # unresolved and can be re-canonicalized by normalize_works --pass 1.
    plan = []  # (ref_id, new_pid, method, score)
    stable = recovered = dropped = unresolved = skipped = 0
    for r in refs:
        pid, method, score = resolve_one(
            r.doi, r.title, r.year, r.authors_json, index,
            threshold=args.threshold, min_tokens=args.min_tokens)
        was_held = r.resolved_paper_id is not None
        if pid is not None:
            if r.resolved_paper_id == pid:
                stable += 1
            else:
                recovered += 1                 # newly held (from external/unresolved/re-point)
                plan.append((r.id, pid, method, score))
        elif was_held:
            dropped += 1                       # held match no longer valid (FP removal)
            plan.append((r.id, None, 'none', None))
        elif r.resolved_work_id is not None:
            skipped += 1                       # external CitedWork — leave P12 layer intact
        else:
            unresolved += 1                    # plain unresolved — mark 'none'
            if r.match_method != 'none':
                plan.append((r.id, None, 'none', None))

    print(f"\nHeld — stable {stable}, recovered/re-pointed {recovered}, "
          f"dropped(FP) {dropped}")
    print(f"External CitedWork left intact: {skipped} | unresolved: {unresolved}")
    print(f"Rows to write: {len(plan)}")

    if not args.execute:
        print('\nDRY-RUN (no --execute). Sample changes:')
        for ref_id, pid, method, score in plan[:15]:
            r = Reference.get_by_id(ref_id)
            src = (r.title or r.raw_text or '')[:45]
            if pid is not None:
                print(f'  +held  "{src}" -> paper={pid} '
                      f'"{index["papers"][pid]["title"][:45]}" ({method} {score})')
            else:
                print(f'  -drop  "{src}" (was paper={r.resolved_paper_id})')
        return

    with db.atomic():
        for ref_id, pid, method, score in plan:
            Reference.update(
                resolved_paper=pid, resolved_work=None,
                match_method=method, match_score=score
            ).where(Reference.id == ref_id).execute()
    print(f'\nWritten to DB. {len(plan)} references updated.')
    print('Next: normalize_works.py --pass 1 --execute (re-canonicalize newly '
          'unresolved refs into CitedWorks) then --pass 2 (cite_count/reconcile).')


if __name__ == '__main__':
    main()
