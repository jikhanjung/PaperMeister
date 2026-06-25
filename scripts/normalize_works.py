#!/usr/bin/env python3
"""P11 Phase 2 — normalize external references into canonical CitedWork nodes.

Two passes (see devlog/20260625_P12_External_Work_Normalization.md):

  Pass 1 (deterministic, fast): every reference that doesn't resolve to a held
          paper is canonicalized into a CitedWork by exact DOI / (title_key,
          year), creating a node when none matches.
  Pass 2 (LLM, only on collisions): CitedWorks are blocked by (first author
          surname, year); clusters with >=2 candidates are sent to the LLM,
          which decides which are the SAME work — confirmed duplicates merge.
          Verdicts are persisted (merge_checked) so re-runs are resumable.

Then cite_count is recomputed and held-paper reconciliation runs.

Convention: dry-run by default; pass --execute to write to the DB.
Run on the Windows machine (live DB lives there) once extraction is idle.
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import CitedWork, Reference
from papermeister import references as refs
from papermeister.biblio import llm_match_works


def run_pass1(execute: bool) -> dict:
    """Exact-dedup every unresolved reference into CitedWork nodes."""
    pids = [r[0] for r in refs.db.execute_sql(
        "SELECT DISTINCT citing_paper_id FROM reference").fetchall()]
    unresolved = refs.db.execute_sql(
        "SELECT COUNT(*) FROM reference "
        "WHERE resolved_paper_id IS NULL AND resolved_work_id IS NULL"
    ).fetchone()[0]
    print(f'  papers with references: {len(pids)}')
    print(f'  references not yet linked to a node: {unresolved}')
    if not execute:
        return {}
    held_index = refs.build_resolution_index()
    work_index = refs.build_work_index()
    totals = {}
    for n, pid in enumerate(pids, 1):
        c = refs.resolve_paper_references(pid, index=held_index, work_index=work_index)
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
        if n % 200 == 0:
            print(f'    pass1 {n}/{len(pids)} papers…', flush=True)
    return totals


def run_pass2(execute: bool, backend: str, workers: int, max_cluster: int) -> dict:
    """LLM-merge near-duplicate CitedWorks within (surname, year) blocks."""
    clusters = refs.cluster_works_by_block(max_cluster=max_cluster)
    sizes = sorted((len(c) for c in clusters), reverse=True)
    print(f'  candidate clusters (>=2, unjudged): {len(clusters)}'
          + (f'  sizes top: {sizes[:8]}' if sizes else ''))
    if not execute or not clusters:
        return {'merged': 0, 'clusters': len(clusters)}

    from papermeister.preferences import get_pref
    url = get_pref('ocr_pod_url', '') if backend == 'qwen' else ''
    from concurrent.futures import ThreadPoolExecutor, as_completed

    merged = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # LLM (no DB) in workers; merge writes happen in this main thread.
        fut_map = {pool.submit(llm_match_works, ws, backend, url): ws
                   for ws in clusters}
        for i, fut in enumerate(as_completed(fut_map), 1):
            ws = fut_map[fut]
            try:
                groups = fut.result()
            except Exception as e:
                print(f'  [cluster {i}/{len(clusters)}] LLM ERR: {str(e)[:80]}',
                      flush=True)
                continue
            for grp in groups:
                if len(grp) >= 2:
                    ids = [ws[k].id for k in grp]
                    merged += refs.merge_works(min(ids), ids)
            refs.mark_merge_checked([w.id for w in ws])
            if i % 20 == 0:
                print(f'    pass2 {i}/{len(clusters)} clusters, {merged} merged…',
                      flush=True)
    return {'merged': merged, 'clusters': len(clusters)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', choices=['qwen', 'claude'], default='qwen')
    ap.add_argument('--pass', dest='which', choices=['all', '1', '2'], default='all')
    ap.add_argument('--workers', type=int, default=3,
                    help='Parallel LLM clusters in pass 2 (server batches them)')
    ap.add_argument('--max-cluster', type=int, default=25,
                    help='Skip blocks larger than this in pass 2 (too noisy)')
    ap.add_argument('--no-reconcile', action='store_true',
                    help='Skip promoting works that match a held paper')
    ap.add_argument('--execute', action='store_true',
                    help='Write to the DB (default: dry-run preview)')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    init_db()
    t0 = time.time()
    active = CitedWork.select().where(CitedWork.merged_into_paper.is_null(True)).count()
    print(f'Existing CitedWork nodes (active): {active}')
    if not args.execute:
        print('DRY-RUN (no --execute). Preview only:')

    if args.which in ('all', '1'):
        print('\n== Pass 1: exact dedup ==')
        t = run_pass1(args.execute)
        if t:
            print('  ' + ', '.join(f'{k}={v}' for k, v in sorted(t.items())))

    if args.which in ('all', '2'):
        print('\n== Pass 2: LLM merge ==')
        r = run_pass2(args.execute, args.backend, args.workers, args.max_cluster)
        if args.execute:
            print(f'  merged duplicates: {r["merged"]}')

    if args.execute:
        n = refs.recompute_cite_counts()
        print(f'\ncite_count recomputed for {n} works')
        if not args.no_reconcile:
            promoted = refs.reconcile_works_with_papers()
            print(f'promoted to held papers: {promoted}')
        total = CitedWork.select().where(
            CitedWork.merged_into_paper.is_null(True)).count()
        print(f'active CitedWork nodes now: {total}')
        print(f'time: {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
