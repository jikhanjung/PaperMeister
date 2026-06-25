"""Persistence + resolution helpers for parsed references (P11).

Extraction lives in `biblio.py` (`extract_references_llm`); this module owns
the DB write (`save_references`) and the resolution pass (matching a Reference
to a held Paper) so the CLI scripts and the desktop app share one implementation.
"""
import json
import re
from collections import defaultdict

from .models import Author, Paper, PaperBiblio, Reference, db


def save_references(paper_id: int, entries: list, source: str, model_version: str) -> int:
    """Replace this paper's Reference rows for `source` with `entries`.

    Delete-and-replace keyed on (citing_paper, source) → idempotent re-runs.
    Returns the number of rows written.
    """
    with db.atomic():
        Reference.delete().where(
            (Reference.citing_paper == paper_id)
            & (Reference.source == source)
        ).execute()
        rows = []
        for i, e in enumerate(entries):
            year = e.get('year')
            rows.append(dict(
                citing_paper=paper_id,
                order_index=i,
                raw_text=(e.get('raw', '') or '')[:4000],
                authors_json=json.dumps(e.get('authors', []) or [], ensure_ascii=False),
                year=year if isinstance(year, int) else None,
                title=e.get('title', '') or '',
                container=e.get('container', '') or '',
                volume=str(e.get('volume', '') or ''),
                issue=str(e.get('issue', '') or ''),
                pages=str(e.get('pages', '') or ''),
                doi=e.get('doi', '') or '',
                ref_type=e.get('type', 'unknown') or 'unknown',
                source=source,
                model_version=model_version,
                parse_confidence=e.get('parse_confidence', '') or '',
            ))
        if rows:
            Reference.insert_many(rows).execute()
    return len(rows)


# ===========================================================================
# Resolution: match a Reference to a held Paper (DOI exact, else title score).
# held vs cited-only falls out of this — resolved_paper set ⇒ we own it.
# ===========================================================================

_WORD_RE = re.compile(r'\w+', re.UNICODE)
_STOP = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'for', 'to', 'with',
         'from', 'der', 'die', 'das', 'und', 'von', 'la', 'le', 'les', 'des'}


def normalize_doi(doi: str) -> str:
    if not doi:
        return ''
    d = doi.strip().lower()
    d = re.sub(r'^(https?://)?(dx\.)?doi\.org/', '', d)
    d = re.sub(r'^doi:\s*', '', d)
    return d.strip()


def title_tokens(title: str) -> list:
    toks = _WORD_RE.findall((title or '').lower())
    return [t for t in toks if t not in _STOP and (len(t) >= 3 or not t.isascii())]


def surname(name: str) -> str:
    """First-author surname from a stored 'Last, First' / 'First Last' string."""
    if not name:
        return ''
    if ',' in name:
        return name.split(',')[0].strip().lower()
    parts = name.split()
    return parts[-1].strip().lower() if parts else ''


def ref_surname(authors_json: str) -> str:
    try:
        authors = json.loads(authors_json or '[]')
    except (json.JSONDecodeError, TypeError):
        return ''
    if not authors:
        return ''
    a = authors[0]
    if isinstance(a, dict):
        return (a.get('family', '') or '').strip().lower()
    return surname(str(a))


def build_resolution_index() -> dict:
    """Index of held papers for resolution. Plain data — safe to reuse across
    threads/papers within a batch (rebuild when the paper set may have changed).

    Returns {'doi_map': {doi: pid}, 'papers': {pid: {tokens,year,surname,title}},
             'inverted': {token: set(pid)}}.
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

    inverted = defaultdict(set)
    for pid, info in papers.items():
        for tok in info['tokens']:
            inverted[tok].add(pid)

    return {'doi_map': doi_map, 'papers': papers, 'inverted': inverted}


def _score_title(ref_toks, info, ref_year, ref_sn) -> float:
    """Similarity score between a reference and a held paper's title."""
    if not ref_toks or not info['tokens']:
        return 0.0
    rset = set(ref_toks)
    inter = rset & info['tokens']
    if not inter:
        return 0.0
    score = len(inter) / min(len(rset), len(info['tokens']))   # containment
    if ref_year and info['year']:
        score += 0.1 if ref_year == info['year'] else -0.3
    if ref_sn and info['surname'] and ref_sn == info['surname']:
        score += 0.15
    return score


def resolve_one(doi, title, year, authors_json, index,
                threshold=0.7, min_tokens=2):
    """Resolve a single reference against the index.

    Returns (paper_id|None, method, score|None) — method is 'doi'|'title'|'none'.
    """
    nd = normalize_doi(doi)
    if nd and nd in index['doi_map']:
        return index['doi_map'][nd], 'doi', 1.0

    toks = title_tokens(title)
    if not toks:
        return None, 'none', None

    counts = defaultdict(int)
    for tok in set(toks):
        for pid in index['inverted'].get(tok, ()):
            counts[pid] += 1
    rsn = ref_surname(authors_json)
    best_pid, best = None, 0.0
    for pid, c in counts.items():
        if c < min_tokens:
            continue
        s = _score_title(toks, index['papers'][pid], year, rsn)
        if s > best:
            best_pid, best = pid, s
    if best_pid is not None and best >= threshold:
        return best_pid, 'title', round(best, 3)
    return None, 'none', None


def resolve_paper_references(paper_id, index=None,
                            threshold=0.7, min_tokens=2) -> dict:
    """Resolve all of a citing paper's references and write the result.

    Builds the index if not supplied (pass a shared one for batch efficiency).
    Returns {'doi': n, 'title': n, 'none': n}.
    """
    if index is None:
        index = build_resolution_index()
    counts = {'doi': 0, 'title': 0, 'none': 0}
    rows = list(Reference.select().where(Reference.citing_paper == paper_id))
    with db.atomic():
        for r in rows:
            pid, method, score = resolve_one(
                r.doi, r.title, r.year, r.authors_json, index,
                threshold=threshold, min_tokens=min_tokens)
            counts[method] = counts.get(method, 0) + 1
            Reference.update(
                resolved_paper=pid, match_method=method, match_score=score
            ).where(Reference.id == r.id).execute()
    return counts
