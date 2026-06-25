#!/usr/bin/env python3
"""P11 — extract the references section of OCR-processed papers (Phase 1).

Parses each paper's bibliography into structured `Reference` rows via the
ocrserver Qwen3 model. Non-destructive: re-running replaces a paper's existing
Reference set for the same `source` (delete-and-replace, idempotent).

Resolution (matching a Reference to a paper we own) is a SEPARATE pass —
see scripts/resolve_references.py.

Convention: dry-run by default; pass --execute to write to the DB.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile, Reference, Folder, Source
from papermeister.biblio import extract_references_llm
from papermeister.references import save_references


def fetch_targets(args):
    """Return list of (paper_id, file_hash) for processed PDFs in scope."""
    query = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
            & (Paper.trashed_at.is_null(True))
        )
    )

    if args.paper_ids:
        ids = [int(x) for x in args.paper_ids.split(',') if x.strip()]
        query = query.where(Paper.id.in_(ids))
    elif args.scope == 'directory':
        query = query.join(Folder).join(Source).where(Source.source_type == 'directory')

    # Dedupe by paper (a paper may have several PaperFile rows / hashes); keep
    # the first PDF hash per paper.
    targets, seen = [], set()
    for pf in query:
        if pf.paper.id in seen:
            continue
        seen.add(pf.paper.id)
        targets.append((pf.paper.id, pf.hash))

    if args.skip_existing and not args.paper_ids:
        # Skip papers already checked (have refs OR confirmed none). --reextract
        # or explicit --paper-ids bypass this so a paper can be re-parsed.
        checked = {
            p.id for p in
            Paper.select(Paper.id).where(Paper.references_checked == True)  # noqa: E712
        }
        targets = [t for t in targets if t[0] not in checked]

    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['qwen', 'claude'], default='qwen')
    parser.add_argument('--scope', choices=['all', 'directory'], default='all')
    parser.add_argument('--paper-ids', default='', help='Comma-separated paper IDs')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--skip-existing', action='store_true', default=True)
    parser.add_argument('--reextract', dest='skip_existing', action='store_false',
                        help='Re-parse papers that already have references')
    parser.add_argument('--execute', action='store_true',
                        help='Write to the DB (default: dry-run preview)')
    args = parser.parse_args()

    init_db()
    args.source_label = 'llm-qwen' if args.backend == 'qwen' else 'llm-sonnet'

    targets = fetch_targets(args)
    print(f'Targets (scope={args.scope}, skip_existing={args.skip_existing}): {len(targets)}')
    if args.limit > 0:
        targets = targets[:args.limit]
        print(f'  --limit {args.limit} -> {len(targets)}')
    if not targets:
        return
    if not args.execute:
        print('DRY-RUN (no --execute). Would parse references for these papers:')
        for pid, h in targets[:20]:
            print(f'  paper={pid} hash={h[:8]}')
        if len(targets) > 20:
            print(f'  ... and {len(targets) - 20} more')
        return

    ok = err = total_refs = 0
    t0 = time.time()
    for i, (pid, h) in enumerate(targets, 1):
        try:
            entries, source, model_version = extract_references_llm(h, backend=args.backend)
            n = save_references(pid, entries, source, model_version)
            # Mark checked even when n == 0 (no references section) so re-runs skip it.
            Paper.update(references_checked=True).where(Paper.id == pid).execute()
            ok += 1
            total_refs += n
            tag = f'{n} refs' if n else 'no references section'
            print(f'[{i}/{len(targets)}] paper={pid} ok | {tag}', flush=True)
        except Exception as e:
            err += 1
            print(f'[{i}/{len(targets)}] paper={pid} ERR: {str(e)[:100]}', flush=True)

    elapsed = time.time() - t0
    print(f'\n=== Done ===')
    print(f'  ok:    {ok}')
    print(f'  err:   {err}')
    print(f'  refs:  {total_refs}')
    print(f'  time:  {elapsed:.1f}s ({elapsed/max(1,len(targets)):.1f}s/paper)')


if __name__ == '__main__':
    main()
