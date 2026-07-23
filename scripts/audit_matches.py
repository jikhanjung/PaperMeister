#!/usr/bin/env python3
"""P14 A2 — audit reference->held-paper matching quality (read-only).

Surfaces likely errors in `resolve_references` so the 0.7 title threshold can be
tuned with evidence, BEFORE the citation graph is frozen (bad matches = bad
edges). Two probes:

  * FALSE POSITIVES — title-matched references (match_method='title') whose
    stored fields disagree with the matched paper (year gap, surname mismatch)
    or whose score sits near the threshold. These may be wrong links.
  * FALSE NEGATIVES — references left external/unresolved whose normalised
    title equals a held paper's title. These probably SHOULD be held links.

READ-ONLY (`mode=ro`); prints candidates for human (or later LLM) review — it
never edits resolutions. Run on native Windows (WAL), not WSL (devlog 068).
Pure stdlib. The title normaliser here is a lightweight approximation of
`references.work_title_key` (kept dependency-free), so treat it as a probe, not
ground truth.

    python scripts/audit_matches.py                 # summary + both probes
    python scripts/audit_matches.py --sample 40      # more examples each
    python scripts/audit_matches.py --threshold 0.7  # flag title matches below
"""
import argparse
import json
import os
import re
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser('~/.papermeister/papermeister.db')
_STOP = {'the', 'and', 'for', 'from', 'with', 'una', 'der', 'die', 'und',
         'des', 'les', 'del', 'las', 'los', 'new', 'note', 'notes'}
_TOKEN = re.compile(r'[a-z0-9一-鿿가-힣぀-ヿ]+')


def connect_ro(db_path):
    if not os.path.exists(db_path):
        sys.exit(f'DB not found: {db_path}')
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    con.execute('PRAGMA query_only = 1')
    return con


def title_key(title):
    """Lightweight normalised title fingerprint (approx work_title_key)."""
    if not title:
        return ''
    # strip HTML tags (some titles carry <i>...</i>)
    title = re.sub(r'<[^>]+>', ' ', title)
    toks = [t for t in _TOKEN.findall(title.lower())
            if t not in _STOP and (len(t) >= 3 or not t.isascii())]
    return ' '.join(sorted(toks))


def surname_of(authors_json):
    """First-author surname from a Reference.authors_json blob (best effort)."""
    if not authors_json:
        return ''
    try:
        data = json.loads(authors_json)
    except (ValueError, TypeError):
        data = authors_json
    first = data[0] if isinstance(data, list) and data else data
    if isinstance(first, dict):
        name = first.get('family') or first.get('last') or first.get('name') or ''
    else:
        name = str(first or '')
    if ',' in name:
        return name.split(',')[0].strip().lower()
    parts = name.split()
    return parts[-1].strip().lower() if parts else ''


def paper_surname(con, paper_id):
    row = con.execute(
        'SELECT name FROM author WHERE paper_id = ? ORDER BY "order" LIMIT 1',
        (paper_id,)).fetchone()
    if not row or not row[0]:
        return ''
    name = row[0]
    if ',' in name:
        return name.split(',')[0].strip().lower()
    parts = name.split()
    return parts[-1].strip().lower() if parts else ''


def year_gap(a, b):
    try:
        return abs(int(str(a)[:4]) - int(str(b)[:4]))
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--sample', type=int, default=20, help='examples per probe')
    ap.add_argument('--threshold', type=float, default=0.7,
                    help='flag title matches scoring below this')
    args = ap.parse_args()

    con = connect_ro(args.db)
    cur = con.cursor()

    # ---- match-method breakdown ----
    print('=' * 64)
    print('Reference matching audit (P14 A2)')
    print('=' * 64)
    print('match_method breakdown:')
    for method, c in cur.execute(
            "SELECT COALESCE(NULLIF(match_method,''),'(empty)'), COUNT(*) "
            'FROM reference GROUP BY 1 ORDER BY 2 DESC').fetchall():
        print(f'  {method:<14} {c:>8,}')

    # ---- FALSE POSITIVES: title matches that look shaky ----
    print('\n--- Possible FALSE POSITIVES (title matches) ---')
    rows = cur.execute(
        'SELECT id, resolved_paper_id, title, year, authors_json, match_score '
        "FROM reference WHERE match_method = 'title' "
        'ORDER BY match_score ASC').fetchall()
    flagged = []
    for rid, pid, rtitle, ryear, rauth, score in rows:
        prow = cur.execute('SELECT title, year FROM paper WHERE id = ?',
                           (pid,)).fetchone()
        if not prow:
            continue
        ptitle, pyear = prow
        yg = year_gap(ryear, pyear)
        rs, ps = surname_of(rauth), paper_surname(con, pid)
        reasons = []
        if score is not None and score < args.threshold:
            reasons.append(f'score {score:.2f}<{args.threshold}')
        if yg is not None and yg > 1:
            reasons.append(f'year gap {yg}')
        if rs and ps and rs != ps and rs not in ps and ps not in rs:
            reasons.append(f'surname {rs!r}!={ps!r}')
        if reasons:
            flagged.append((score or 0, rid, pid, rtitle, ptitle, reasons))
    print(f'flagged {len(flagged):,} of {len(rows):,} title matches')
    for _score, rid, pid, rtitle, ptitle, reasons in flagged[:args.sample]:
        print(f'  ref#{rid} -> paper#{pid}  [{", ".join(reasons)}]')
        print(f'      ref  : {(rtitle or "")[:70]}')
        print(f'      paper: {(ptitle or "")[:70]}')

    # ---- FALSE NEGATIVES: title matches a held paper but not linked ----
    print('\n--- Possible FALSE NEGATIVES (unlinked but title matches a held paper) ---')
    key_map = {}
    for pid, title, year in cur.execute(
            'SELECT id, title, year FROM paper WHERE references_checked = 1 '
            'OR id IN (SELECT DISTINCT resolved_paper_id FROM reference '
            'WHERE resolved_paper_id IS NOT NULL)').fetchall():
        k = title_key(title)
        if len(k) >= 8:  # avoid trivially short keys
            key_map.setdefault(k, (pid, title, year))
    # scan references not linked to a held paper
    fn = []
    for rid, cpid, rtitle, rwork in cur.execute(
            'SELECT id, citing_paper_id, title, resolved_work_id FROM reference '
            'WHERE resolved_paper_id IS NULL AND title IS NOT NULL '
            "AND title <> ''").fetchall():
        k = title_key(rtitle)
        if len(k) >= 8 and k in key_map:
            pid, ptitle, _ = key_map[k]
            if pid != cpid:  # not a self-match artifact
                fn.append((rid, pid, rtitle, ptitle, rwork))
    print(f'found {len(fn):,} references whose title matches a held paper but '
          f'are not linked to it')
    for rid, pid, rtitle, ptitle, rwork in fn[:args.sample]:
        tag = f'(currently external work#{rwork})' if rwork else '(unresolved)'
        print(f'  ref#{rid} ~= paper#{pid}  {tag}')
        print(f'      ref  : {(rtitle or "")[:70]}')
        print(f'      paper: {(ptitle or "")[:70]}')

    print('\nNote: probes use an approximate title normaliser; review before '
          'acting. Tune resolve_references.py --threshold from the FP rate, and '
          're-run resolve to capture the FN set.')
    con.close()


if __name__ == '__main__':
    main()
