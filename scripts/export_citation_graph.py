#!/usr/bin/env python3
"""P14 L1 — export the in-library citation graph (read-only).

Materialises the held->held citation graph (from `reference.resolved_paper_id`)
as `nodes.csv` + `edges.csv` + `citation.gexf`, ready for Gephi / Cytoscape.
No in-app graph engine needed. Optionally adds external `CitedWork` nodes as a
second layer (`--with-external`).

READ-ONLY on the DB (`mode=ro`); writes only the output files. Run on native
Windows (WAL), not WSL against `/mnt/c` (devlog 068). Pure stdlib.

    python scripts/export_citation_graph.py --out graph_out
    python scripts/export_citation_graph.py --out graph_out --all-nodes --self-loops
    python scripts/export_citation_graph.py --out graph_out --with-external --min-cites 2

Edges are distinct directed (citing -> cited); self-citations excluded unless
--self-loops. Nodes default to papers that participate in >=1 edge; --all-nodes
adds isolated references-checked held papers too. The graph is only as complete
as extraction (references_checked %).
"""
import argparse
import csv
import os
import sqlite3
import sys
from xml.sax.saxutils import escape

DEFAULT_DB = os.path.expanduser('~/.papermeister/papermeister.db')


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
    if not row or not row[0]:
        return ''
    name = row[0]
    return name.split(',')[0].strip() if ',' in name else name.split()[-1]


def build_graph(con, self_loops, all_nodes):
    """Return (paper_nodes: dict[id]->attrs, edges: list[(src,dst)])."""
    self_clause = '' if self_loops else 'AND resolved_paper_id <> citing_paper_id'
    edge_rows = con.execute(
        f'SELECT DISTINCT citing_paper_id, resolved_paper_id FROM reference '
        f'WHERE resolved_paper_id IS NOT NULL {self_clause}').fetchall()
    edges = [(s, d) for s, d in edge_rows]

    indeg, outdeg = {}, {}
    node_ids = set()
    for s, d in edges:
        node_ids.add(s)
        node_ids.add(d)
        outdeg[s] = outdeg.get(s, 0) + 1
        indeg[d] = indeg.get(d, 0) + 1

    if all_nodes:
        for (pid,) in con.execute(
                'SELECT id FROM paper WHERE references_checked = 1').fetchall():
            node_ids.add(pid)

    nodes = {}
    for pid in node_ids:
        row = con.execute('SELECT title, year FROM paper WHERE id = ?',
                          (pid,)).fetchone()
        title, year = (row if row else ('(missing)', None))
        nodes[pid] = {
            'title': (title or '').strip(),
            'year': year if year is not None else '',
            'author': first_author(con, pid),
            'indeg': indeg.get(pid, 0),
            'outdeg': outdeg.get(pid, 0),
        }
    return nodes, edges


def build_external(con, min_cites):
    """Return (work_nodes: dict[id]->attrs, edges: list[(citing_paper, work_id)])."""
    rows = con.execute(
        'SELECT resolved_work_id, COUNT(DISTINCT citing_paper_id) c FROM reference '
        'WHERE resolved_work_id IS NOT NULL GROUP BY resolved_work_id '
        'HAVING c >= ?', (min_cites,)).fetchall()
    keep = {wid for wid, _ in rows}
    cites = dict(rows)
    if not keep:
        return {}, []
    edge_rows = con.execute(
        'SELECT DISTINCT citing_paper_id, resolved_work_id FROM reference '
        'WHERE resolved_work_id IS NOT NULL').fetchall()
    edges = [(s, w) for s, w in edge_rows if w in keep]
    works = {}
    for wid in keep:
        row = con.execute('SELECT title, year, first_surname FROM citedwork '
                          'WHERE id = ?', (wid,)).fetchone()
        title, year, surn = (row if row else ('(missing)', None, ''))
        works[wid] = {
            'title': (title or '').strip(),
            'year': year if year is not None else '',
            'author': surn or '',
            'cites': cites.get(wid, 0),
        }
    return works, edges


def write_csv(out, nodes, edges, works, ext_edges):
    with open(os.path.join(out, 'nodes.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id', 'kind', 'label', 'author', 'year', 'title',
                    'in_degree', 'out_degree', 'ext_cites'])
        for pid, a in nodes.items():
            label = f"{a['author']} {a['year']}".strip() or a['title'][:40]
            w.writerow([f'p{pid}', 'held', label, a['author'], a['year'],
                        a['title'], a['indeg'], a['outdeg'], ''])
        for wid, a in works.items():
            label = f"{a['author']} {a['year']}".strip() or a['title'][:40]
            w.writerow([f'w{wid}', 'external', label, a['author'], a['year'],
                        a['title'], '', '', a['cites']])
    with open(os.path.join(out, 'edges.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['source', 'target', 'kind'])
        for s, d in edges:
            w.writerow([f'p{s}', f'p{d}', 'cites-held'])
        for s, wid in ext_edges:
            w.writerow([f'p{s}', f'w{wid}', 'cites-external'])


def write_gexf(out, nodes, edges, works, ext_edges):
    def node_xml(nid, label, attrs):
        av = ''.join(
            f'<attvalue for="{k}" value="{escape(str(v))}"/>' for k, v in attrs)
        return (f'<node id="{nid}" label="{escape(label)}">'
                f'<attvalues>{av}</attvalues></node>')

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gexf xmlns="http://gexf.net/1.2" version="1.2">',
             '<graph mode="static" defaultedgetype="directed">',
             '<attributes class="node">',
             '<attribute id="kind" title="kind" type="string"/>',
             '<attribute id="author" title="author" type="string"/>',
             '<attribute id="year" title="year" type="string"/>',
             '<attribute id="indeg" title="in_degree" type="integer"/>',
             '<attribute id="outdeg" title="out_degree" type="integer"/>',
             '<attribute id="cites" title="ext_cites" type="integer"/>',
             '</attributes>', '<nodes>']
    for pid, a in nodes.items():
        label = f"{a['author']} {a['year']}".strip() or a['title'][:40] or f'p{pid}'
        parts.append(node_xml(f'p{pid}', label, [
            ('kind', 'held'), ('author', a['author']), ('year', a['year']),
            ('indeg', a['indeg']), ('outdeg', a['outdeg'])]))
    for wid, a in works.items():
        label = f"{a['author']} {a['year']}".strip() or a['title'][:40] or f'w{wid}'
        parts.append(node_xml(f'w{wid}', label, [
            ('kind', 'external'), ('author', a['author']), ('year', a['year']),
            ('cites', a['cites'])]))
    parts.append('</nodes><edges>')
    eid = 0
    for s, d in edges:
        parts.append(f'<edge id="{eid}" source="p{s}" target="p{d}"/>')
        eid += 1
    for s, wid in ext_edges:
        parts.append(f'<edge id="{eid}" source="p{s}" target="w{wid}"/>')
        eid += 1
    parts.append('</edges></graph></gexf>')
    with open(os.path.join(out, 'citation.gexf'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--out', default='citation_graph', help='output directory')
    ap.add_argument('--all-nodes', action='store_true',
                    help='include isolated references-checked held papers')
    ap.add_argument('--self-loops', action='store_true',
                    help='keep self-citations as edges')
    ap.add_argument('--with-external', action='store_true',
                    help='add external CitedWork nodes as a second layer')
    ap.add_argument('--min-cites', type=int, default=2,
                    help='min citing papers for an external work (with --with-external)')
    args = ap.parse_args()

    con = connect_ro(args.db)
    os.makedirs(args.out, exist_ok=True)

    nodes, edges = build_graph(con, args.self_loops, args.all_nodes)
    works, ext_edges = ({}, [])
    if args.with_external:
        works, ext_edges = build_external(con, args.min_cites)
    con.close()

    write_csv(args.out, nodes, edges, works, ext_edges)
    write_gexf(args.out, nodes, edges, works, ext_edges)

    print(f'Wrote to {args.out}/')
    print(f'  held nodes     : {len(nodes):,}')
    print(f'  held->held edges: {len(edges):,}')
    if args.with_external:
        print(f'  external nodes : {len(works):,}  (>= {args.min_cites} cites)')
        print(f'  ->external edges: {len(ext_edges):,}')
    print('  files: nodes.csv, edges.csv, citation.gexf')


if __name__ == '__main__':
    main()
