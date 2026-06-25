#!/usr/bin/env python3
"""P11 — resolve parsed references to papers we own (Phase 1).

For each Reference, try to link it to a held Paper:
  1. DOI exact match (normalized) against Paper.doi / PaperBiblio.doi.
  2. Title match: token-overlap candidate generation, then score by title
     similarity + year agreement + first-author surname.

held vs cited-only falls out of this: `resolved_paper` set => we own it;
null => external (cited-only).

This pass is independent of extraction and re-runnable: it clears prior
resolution and recomputes. Convention: dry-run unless --execute.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, Author, PaperBiblio, Reference, db


def normalize_doi(doi):
    if not doi:
        return ''
    d = doi.strip().lower()
    d = re.sub(r'^(https?://)?(dx\.)?doi\.org/', '', d)
    d = re.sub(r'^doi:\s*', '', d)
    return d.strip()


_WORD_RE = re.compile(r'\w+', re.UNICODE)
_STOP = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'for', 'to', 'with',
         'from', 'der', 'die', 'das', 'und', 'von', 'la', 'le', 'les', 'des'}


def title_tokens(title):
    toks = _WORD_RE.findall((title or '').lower())
    return [t for t in toks if t not in _STOP and (len(t) >= 3 or not t.isascii())]


def surname(name):
    """First-author surname from a stored 'Last, First' / 'First Last' string."""
    if not name:
        return ''
    if ',' in name:
        return name.split(',')[0].strip().lower()
    parts = name.split()
    return parts[-1].strip().lower() if parts else ''


def ref_surname(authors_json):
    try:
        authors = json.loads(authors_json or '[]')
    except json.JSONDecodeError:
        return ''
    if not authors:
        return ''
    a = authors[0]
    if isinstance(a, dict):
        return (a.get('family', '') or '').strip().lower()
    return surname(str(a))


def build_index():
    """Return (doi_map, papers) for held papers.

    doi_map: normalized doi -> paper_id (from Paper and PaperBiblio).
    papers:  paper_id -> {'tokens': set, 'year': int|None, 'surname': str, 'title': str}
    """
    papers = {}
    for p in Paper.select(Paper.id, Paper.title, Paper.year).where(
            Paper.trashed_at.is_null(True)):
        papers[p.id] = {
            'tokens': set(title_tokens(p.title)),
            'year': p.year,
            'surname': '',
            'title': p.title or '',
        }

    # first-author surname per paper
    first = {}
    for a in Author.select(Author.paper, Author.name, Author.order).order_by(
            Author.paper, Author.order):
        if a.paper_id not in first:
            first[a.paper_id] = a.name
    for pid, name in first.items():
        if pid in papers:
            papers[pid]['surname'] = surname(name)

    doi_map = {}
    for p in Paper.select(Paper.id, Paper.doi).where(Paper.doi != ''):
        nd = normalize_doi(p.doi)
        if nd:
            doi_map.setdefault(nd, p.id)
    for b in PaperBiblio.select(PaperBiblio.paper, PaperBiblio.doi).where(PaperBiblio.doi != ''):
        nd = normalize_doi(b.doi)
        if nd:
            doi_map.setdefault(nd, b.paper_id)

    # token inverted index for candidate generation
    inverted = defaultdict(set)
    for pid, info in papers.items():
        for tok in info['tokens']:
            inverted[tok].add(pid)

    return doi_map, papers, inverted


def score_title(ref_toks, info, ref_year, ref_sn):
    """Similarity score in [0,1] between a reference and a held paper."""
    if not ref_toks or not info['tokens']:
        return 0.0
    rset = set(ref_toks)
    inter = rset & info['tokens']
    if not inter:
        return 0.0
    # containment: how much of the (shorter) title is covered
    containment = len(inter) / min(len(rset), len(info['tokens']))
    score = containment
    # year agreement nudges; disagreement penalizes
    if ref_year and info['year']:
        score += 0.1 if ref_year == info['year'] else -0.3
    # first-author surname agreement
    if ref_sn and info['surname'] and ref_sn == info['surname']:
        score += 0.15
    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--threshold', type=float, default=0.7,
                        help='Min title score to accept a non-DOI match')
    parser.add_argument('--min-tokens', type=int, default=2,
                        help='Min shared title tokens to even consider a candidate')
    parser.add_argument('--reresolve', action='store_true',
                        help='Recompute even references already resolved')
    parser.add_argument('--execute', action='store_true',
                        help='Write resolution to the DB (default: dry-run)')
    args = parser.parse_args()

    init_db()
    doi_map, papers, inverted = build_index()
    print(f'Held papers indexed: {len(papers)} | DOIs: {len(doi_map)}')

    q = Reference.select()
    if not args.reresolve:
        q = q.where(Reference.match_method == '')
    refs = list(q)
    print(f'References to resolve: {len(refs)}')

    by_doi = by_title = unresolved = 0
    updates = []  # (ref_id, paper_id, method, score)
    for r in refs:
        nd = normalize_doi(r.doi)
        if nd and nd in doi_map:
            updates.append((r.id, doi_map[nd], 'doi', 1.0))
            by_doi += 1
            continue

        ref_toks = title_tokens(r.title)
        if not ref_toks:
            updates.append((r.id, None, 'none', None))
            unresolved += 1
            continue

        # candidate generation via inverted index
        counts = defaultdict(int)
        for tok in set(ref_toks):
            for pid in inverted.get(tok, ()):
                counts[pid] += 1
        candidates = [pid for pid, c in counts.items() if c >= args.min_tokens]

        rsn = ref_surname(r.authors_json)
        best_pid, best_score = None, 0.0
        for pid in candidates:
            s = score_title(ref_toks, papers[pid], r.year, rsn)
            if s > best_score:
                best_pid, best_score = pid, s

        if best_pid is not None and best_score >= args.threshold:
            updates.append((r.id, best_pid, 'title', round(best_score, 3)))
            by_title += 1
        else:
            updates.append((r.id, None, 'none', None))
            unresolved += 1

    print(f'\nResolved by DOI:   {by_doi}')
    print(f'Resolved by title: {by_title}')
    print(f'Unresolved:        {unresolved}')

    if not args.execute:
        print('\nDRY-RUN (no --execute). Sample title matches:')
        shown = 0
        for ref_id, pid, method, score in updates:
            if method == 'title' and shown < 15:
                r = Reference.get_by_id(ref_id)
                print(f'  ref="{(r.title or r.raw_text)[:50]}" -> '
                      f'paper={pid} "{papers[pid]["title"][:50]}" (score={score})')
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
