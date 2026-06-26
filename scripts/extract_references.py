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
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile, Reference, Folder, Source
from papermeister.biblio import extract_references_llm
from papermeister.references import save_references


def _short(title, n=28):
    """Collapse whitespace and truncate a title from the front for log lines."""
    t = ' '.join((title or '').split())
    return (t[:n] + '…') if len(t) > n else (t or '(untitled)')


def fetch_targets(args):
    """Return list of (paper_id, file_hash, title) for processed PDFs in scope."""
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
        targets.append((pf.paper.id, pf.hash, pf.paper.title or ''))

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
    parser.add_argument('--no-resolve', action='store_true',
                        help='Skip the post-extraction auto-resolve pass')
    parser.add_argument('--workers', type=int, default=1,
                        help='Parse N papers concurrently (the server batches '
                        'concurrent LLM requests; 2-4 is usually a clear win)')
    args = parser.parse_args()

    # Show the adaptive per-batch progress ("refs N/M: K in T.Ts → next batch B").
    logging.basicConfig(level=logging.INFO, format='%(message)s')

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
        for pid, h, title in targets[:20]:
            print(f'  paper={pid} hash={h[:8]} | {_short(title, 50)}')
        if len(targets) > 20:
            print(f'  ... and {len(targets) - 20} more')
        return

    ok = err = total_refs = 0
    done_pids = []
    t0 = time.time()

    def _extract(pid, h, title):
        # LLM-only (no DB) so it's safe to run in worker threads; the server
        # batches concurrent requests. DB writes happen in the main loop below.
        label = f'[{pid} {_short(title)}]'
        try:
            entries, source, mv, complete = extract_references_llm(
                h, backend=args.backend, label=label)
            return pid, title, entries, source, mv, complete, None
        except Exception as e:
            return pid, title, None, None, None, False, str(e)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(_extract, pid, h, title) for pid, h, title in targets]
        for i, fut in enumerate(as_completed(futures), 1):
            pid, title, entries, source, mv, complete, e = fut.result()
            short = _short(title)
            if e:
                err += 1
                print(f'[{i}/{len(targets)}] {pid} {short} ERR: {e[:80]}', flush=True)
                continue
            n = save_references(pid, entries, source, mv)   # main thread (DB)
            if complete:
                # Mark checked even when n == 0 (no references section) so re-runs
                # skip it. Partial results (complete=False) are saved but left
                # unchecked → a later --scope all re-parses and replaces them.
                Paper.update(references_checked=True).where(Paper.id == pid).execute()
            ok += 1
            total_refs += n
            done_pids.append(pid)
            if complete:
                tag = f'{n} refs' if n else 'no references section'
            else:
                tag = f'{n} refs PARTIAL — some batches skipped, will retry'
            print(f'[{i}/{len(targets)}] {pid} {short} ok | {tag}', flush=True)

    # Auto-resolve the just-extracted references against held papers (one shared
    # index for the whole run) so the 'in library' link is populated.
    resolved = 0
    if done_pids and not args.no_resolve:
        from papermeister.references import (
            build_resolution_index, build_work_index, resolve_paper_references)
        index = build_resolution_index()
        # Phase 2: canonicalize externals into CitedWork nodes (pass-1 exact
        # dedup). LLM near-dup merge (pass 2) is a separate batch — normalize_works.py.
        work_index = build_work_index()
        for pid in done_pids:
            c = resolve_paper_references(pid, index=index, work_index=work_index)
            resolved += c.get('doi', 0) + c.get('title', 0)

    elapsed = time.time() - t0
    print(f'\n=== Done ===')
    print(f'  ok:       {ok}')
    print(f'  err:      {err}')
    print(f'  refs:     {total_refs}')
    if not args.no_resolve:
        print(f'  resolved: {resolved} (matched to library)')
    print(f'  time:     {elapsed:.1f}s ({elapsed/max(1,len(targets)):.1f}s/paper)')


if __name__ == '__main__':
    main()
