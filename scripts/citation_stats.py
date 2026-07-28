from papermeister.paths import DB_PATH

#!/usr/bin/env python3
"""P14 L0 — in-library citation-network statistics (read-only).

Summarises the held->held citation graph that already exists implicitly in
`reference.resolved_paper_id` (a resolved reference whose target we own is an
in-library citation edge: citing_paper -> cited_paper). No graph engine; just
degree counts and top lists to sanity-check the network and surface the most
central papers.

READ-ONLY. Opens the DB `mode=ro` and never writes. Safe alongside a running
extraction, but ONLY on native Windows (WAL). Do NOT run from WSL against the
`/mnt/c` DB (drvfs index-desync risk, devlog 068). Pure stdlib.

    python scripts/citation_stats.py            # full summary
    python scripts/citation_stats.py --top 25   # longer top lists
    python scripts/citation_stats.py --db PATH

Note: the graph is only as complete as extraction (references_checked %). At
partial coverage the degrees are a lower bound — interpret as a subgraph.
"""
import argparse
import os
import sqlite3
import sys

DEFAULT_DB = DB_PATH


def connect_ro(db_path):
    if not os.path.exists(db_path):
        sys.exit(f'DB not found: {db_path}')
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    con.execute('PRAGMA query_only = 1')
    return con


def first_author(con, paper_id):
    row = con.execute(
        'SELECT name FROM author WHERE paper_id = ? ORDER BY "order" LIMIT 1',
        (paper_id,)).fetchone()
    if not row:
        return '(no author)'
    name = row[0]
    # stored as "Last, First" or "First Last"; show the surname-ish token
    return name.split(',')[0].strip() if ',' in name else name.split()[-1]


def paper_label(con, paper_id):
    row = con.execute('SELECT title, year FROM paper WHERE id = ?',
                      (paper_id,)).fetchone()
    if not row:
        return f'#{paper_id} (missing)'
    title, year = row
    title = (title or '(untitled)').strip()
    if len(title) > 60:
        title = title[:57] + '...'
    yr = f' ({year})' if year else ''
    return f'{first_author(con, paper_id)}{yr}: {title}'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--top', type=int, default=15, help='rows in each top list')
    args = ap.parse_args()

    con = connect_ro(args.db)
    cur = con.cursor()

    # ---- coverage ----
    papers = cur.execute('SELECT COUNT(*) FROM paper').fetchone()[0]
    checked = cur.execute(
        'SELECT COUNT(*) FROM paper WHERE references_checked = 1').fetchone()[0]

    # ---- reference resolution breakdown ----
    total_refs = cur.execute('SELECT COUNT(*) FROM reference').fetchone()[0]
    held = cur.execute(
        'SELECT COUNT(*) FROM reference WHERE resolved_paper_id IS NOT NULL'
    ).fetchone()[0]
    external = cur.execute(
        'SELECT COUNT(*) FROM reference WHERE resolved_work_id IS NOT NULL'
    ).fetchone()[0]
    unresolved = total_refs - held - external

    # ---- held->held graph ----
    # Distinct directed edges (a paper citing the same target twice = 1 edge).
    edges = cur.execute(
        'SELECT COUNT(*) FROM (SELECT DISTINCT citing_paper_id, resolved_paper_id '
        'FROM reference WHERE resolved_paper_id IS NOT NULL '
        'AND resolved_paper_id <> citing_paper_id)').fetchone()[0]
    self_cites = cur.execute(
        'SELECT COUNT(*) FROM (SELECT DISTINCT citing_paper_id, resolved_paper_id '
        'FROM reference WHERE resolved_paper_id = citing_paper_id)').fetchone()[0]
    n_citing = cur.execute(
        'SELECT COUNT(DISTINCT citing_paper_id) FROM reference '
        'WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id'
    ).fetchone()[0]
    n_cited = cur.execute(
        'SELECT COUNT(DISTINCT resolved_paper_id) FROM reference '
        'WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id'
    ).fetchone()[0]
    nodes = cur.execute(
        'SELECT COUNT(*) FROM (SELECT citing_paper_id AS p FROM reference '
        'WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id '
        'UNION SELECT resolved_paper_id FROM reference '
        'WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id)'
    ).fetchone()[0]

    pct = 100.0 * checked / papers if papers else 0.0
    print('=' * 64)
    print('In-library citation network — stats (P14 L0)')
    print('=' * 64)
    print(f'Coverage : {checked:,}/{papers:,} papers references-checked ({pct:.1f}%)')
    print('           → graph is a SUBGRAPH; degrees are a lower bound.\n')
    print('References resolution:')
    print(f'  total        : {total_refs:>8,}')
    print(f'  held (in-lib): {held:>8,}  ({100.0*held/total_refs:.1f}%)' if total_refs else '  held: 0')
    print(f'  external     : {external:>8,}  ({100.0*external/total_refs:.1f}%)' if total_refs else '')
    print(f'  unresolved   : {unresolved:>8,}  ({100.0*unresolved/total_refs:.1f}%)' if total_refs else '')
    print('\nHeld -> held graph (self-citations excluded from degrees):')
    print(f'  directed edges  : {edges:>8,}')
    print(f'  nodes (papers)  : {nodes:>8,}   (citing {n_citing:,} / cited {n_cited:,})')
    print(f'  self-citations  : {self_cites:>8,}   (reported, not in edges above)')
    if nodes:
        print(f'  avg out-degree  : {edges/max(n_citing,1):>8.2f}  per citing paper')
        print(f'  avg in-degree   : {edges/max(n_cited,1):>8.2f}  per cited paper')

    # ---- top most-cited held papers (in-degree) ----
    print(f'\nMost-cited held papers (in-degree, top {args.top}):')
    rows = cur.execute(
        'SELECT resolved_paper_id, COUNT(DISTINCT citing_paper_id) c '
        'FROM reference WHERE resolved_paper_id IS NOT NULL '
        'AND resolved_paper_id <> citing_paper_id '
        'GROUP BY resolved_paper_id ORDER BY c DESC LIMIT ?', (args.top,)).fetchall()
    for pid, c in rows:
        print(f'  {c:>4}  {paper_label(con, pid)}')

    # ---- top citing papers (out-degree) ----
    print(f'\nPapers citing the most held papers (out-degree, top {args.top}):')
    rows = cur.execute(
        'SELECT citing_paper_id, COUNT(DISTINCT resolved_paper_id) c '
        'FROM reference WHERE resolved_paper_id IS NOT NULL '
        'AND resolved_paper_id <> citing_paper_id '
        'GROUP BY citing_paper_id ORDER BY c DESC LIMIT ?', (args.top,)).fetchall()
    for pid, c in rows:
        print(f'  {c:>4}  {paper_label(con, pid)}')

    con.close()


if __name__ == '__main__':
    main()
