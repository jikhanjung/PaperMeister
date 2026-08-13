"""Persistence + resolution helpers for parsed references (P11).

Extraction lives in `biblio.py` (`extract_references_llm`); this module owns
the DB write (`save_references`) and the resolution pass (matching a Reference
to a held Paper) so the CLI scripts and the desktop app share one implementation.
"""
import json
import re
from collections import defaultdict
from typing import TypedDict

from .models import Author, CitedWork, Paper, PaperBiblio, Reference, db

#: PARTIAL/failed attempts after which a paper drops out of a full-library run.
#: A partial parse leaves `references_checked` False on purpose so a later run
#: can replace it, but target selection orders by paper id descending, so the
#: same unparseable papers come back at the head of every batch and are retried
#: forever (devlog 076) — a handful of hopeless documents can occupy the front
#: of the queue indefinitely. Three is enough to ride out a server outage (which
#: fails papers that are perfectly fine) without grinding on the hopeless ones.
MAX_REFS_ATTEMPTS = 3


def record_refs_attempt(paper_id: int, complete: bool) -> None:
    """Update the give-up counter after one extraction attempt.

    Reset on a complete parse rather than merely not incrementing: a paper that
    failed twice during an outage and then succeeded is not two-thirds retired,
    and without the reset a long-lived library would slowly retire everything.
    """
    if complete:
        Paper.update(references_attempts=0).where(
            (Paper.id == paper_id) & (Paper.references_attempts > 0)).execute()
    else:
        Paper.update(references_attempts=Paper.references_attempts + 1).where(
            Paper.id == paper_id).execute()


def exhausted_paper_ids() -> set:
    """Papers that have used up their attempts, for excluding from a full run."""
    return {p.id for p in Paper.select(Paper.id).where(
        Paper.references_attempts >= MAX_REFS_ATTEMPTS)}


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
            rows.append({
                'citing_paper': paper_id,
                'order_index': i,
                'raw_text': (e.get('raw', '') or '')[:4000],
                'authors_json': json.dumps(e.get('authors', []) or [], ensure_ascii=False),
                'year': year if isinstance(year, int) else None,
                'title': e.get('title', '') or '',
                'container': e.get('container', '') or '',
                'volume': str(e.get('volume', '') or ''),
                'issue': str(e.get('issue', '') or ''),
                'pages': str(e.get('pages', '') or ''),
                'doi': e.get('doi', '') or '',
                'ref_type': e.get('type', 'unknown') or 'unknown',
                'source': source,
                'model_version': model_version,
                'parse_confidence': e.get('parse_confidence', '') or '',
            })
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


class PaperIndexEntry(TypedDict):
    """One held paper as the resolver sees it.

    Declared rather than left as a plain dict so `entry['tokens']` is known to
    be a set: in a heterogeneous dict every value collapses to the union of all
    value types, and iterating it then looks like iterating an int.
    """
    tokens: set[str]
    year: int | None
    surname: str
    title: str


def build_resolution_index() -> dict:
    """Index of held papers for resolution. Plain data — safe to reuse across
    threads/papers within a batch (rebuild when the paper set may have changed).

    Returns {'doi_map': {doi: pid}, 'papers': {pid: {tokens,year,surname,title}},
             'inverted': {token: set(pid)}}.
    """
    papers: dict[int, PaperIndexEntry] = {}
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

    doi_map: dict[str, int] = {}
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
    """Similarity score between a reference and a held paper's title.

    Pure containment (inter/min) let a SHORT reference embedded in a LONG paper
    title score a perfect 1.0 (e.g. "On Growth and Form" inside "...the growth
    and form of teeth..."), a common false positive. We blend containment with
    Jaccard (symmetric) so a match must cover a fair share of BOTH titles —
    unless the token sets are near-identical, which is a confident same-title
    signal that also survives a missing/disagreeing year (recovers false
    negatives like exact-title refs left unresolved).
    """
    if not ref_toks or not info['tokens']:
        return 0.0
    rset = set(ref_toks)
    pset = info['tokens']
    inter = rset & pset
    if not inter:
        return 0.0
    ni, nr, npv = len(inter), len(rset), len(pset)
    # Near-identical token sets (allow one token off on the larger side, e.g. a
    # subtitle or OCR slip). A strong structural signal — trust it on its own.
    near_exact = ni >= 3 and ni >= max(nr, npv) - 1
    if near_exact:
        base = 0.95
    else:
        containment = ni / min(nr, npv)
        jaccard = ni / (nr + npv - ni)
        base = 0.5 * containment + 0.5 * jaccard

    score = base
    if ref_year and info['year']:
        if ref_year == info['year']:
            score += 0.1
        elif not near_exact:        # a near-identical title isn't vetoed by year
            score -= 0.3
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


def resolve_paper_references(paper_id, index=None, work_index=None,
                            threshold=0.7, min_tokens=2) -> dict:
    """Resolve all of a citing paper's references and write the result.

    Builds the held-paper index if not supplied (pass a shared one for batch
    efficiency). If `work_index` is given (see build_work_index), references that
    don't resolve to a held paper are canonicalized to a CitedWork (Phase 2
    pass-1 exact dedup); otherwise they're left unresolved (Phase 1 behaviour).

    Returns a dict keyed by match_method ('doi'/'title'/'work-*'/'none').
    """
    if index is None:
        index = build_resolution_index()
    counts: dict[str, int] = {}
    rows = list(Reference.select().where(Reference.citing_paper == paper_id))
    with db.atomic():
        for r in rows:
            pid, method, score = resolve_one(
                r.doi, r.title, r.year, r.authors_json, index,
                threshold=threshold, min_tokens=min_tokens)
            if pid is not None:
                Reference.update(
                    resolved_paper=pid, resolved_work=None,
                    match_method=method, match_score=score
                ).where(Reference.id == r.id).execute()
            elif work_index is not None:
                wid, method = canonicalize_reference(r, work_index)
                Reference.update(
                    resolved_paper=None, resolved_work=wid,
                    match_method=method, match_score=None
                ).where(Reference.id == r.id).execute()
            else:
                Reference.update(
                    resolved_paper=None, match_method=method, match_score=score
                ).where(Reference.id == r.id).execute()
            counts[method] = counts.get(method, 0) + 1
    return counts


# ===========================================================================
# Phase 2 — external work canonicalization.
# Pass 1 (here): exact dedup (DOI / title_key) into CitedWork nodes.
# Pass 2 (here): cluster + LLM merge of near-duplicates the exact pass missed.
# ===========================================================================

_DOI_RE = re.compile(r'^10\.\d{4,9}/\S+$')


def well_formed_doi(doi: str) -> bool:
    """Trust a DOI for matching only if it looks structurally valid (OCR often
    mangles them). Conservative: better to miss a match than merge wrongly."""
    return bool(_DOI_RE.match(normalize_doi(doi)))


def work_title_key(title: str) -> str:
    """Normalized title fingerprint for exact dedup — sorted unique content
    tokens. Same normalization as resolution (lowercase, stopwords, CJK kept)."""
    return ' '.join(sorted(set(title_tokens(title))))


def build_work_index() -> dict:
    """In-memory index of active CitedWorks for pass-1 exact dedup.

    Returns {'doi_map': {doi: wid}, 'key_map': {(title_key, year): wid}}.
    Mutated in place by canonicalize_reference so a batch dedupes against works
    it just created. Excludes promoted (merged_into_paper) tombstones.
    """
    doi_map: dict[str, int] = {}
    key_map: dict[tuple, int] = {}
    for w in CitedWork.select(
            CitedWork.id, CitedWork.doi, CitedWork.title_key, CitedWork.year
    ).where(CitedWork.merged_into_paper.is_null(True)):
        nd = normalize_doi(w.doi)
        if nd:
            doi_map.setdefault(nd, w.id)
        if w.title_key:
            key_map.setdefault((w.title_key, w.year), w.id)
    return {'doi_map': doi_map, 'key_map': key_map}


def canonicalize_reference(ref, work_index) -> tuple:
    """Pass-1 exact dedup of an unresolved (external) reference into a CitedWork.

    Links to an existing work by exact well-formed DOI or (title_key, year),
    else creates a new CitedWork. Mutates work_index so later refs in the same
    run dedupe against it. Caller must have already failed held-paper matching.

    Returns (work_id|None, method) — 'work-doi'|'work-title'|'work-new'|'none'.
    """
    has_doi = well_formed_doi(ref.doi)
    nd = normalize_doi(ref.doi) if has_doi else ''
    if nd and nd in work_index['doi_map']:
        return work_index['doi_map'][nd], 'work-doi'

    key = work_title_key(ref.title or '')
    if not key and not nd:
        return None, 'none'   # nothing to identify this entry by → junk

    if key:
        hit = work_index['key_map'].get((key, ref.year))
        if hit:
            return hit, 'work-title'

    w = CitedWork.create(
        doi=nd,
        title=ref.title or '',
        title_key=key,
        year=ref.year,
        authors_json=ref.authors_json or '[]',
        container=ref.container or '',
        first_surname=ref_surname(ref.authors_json),
    )
    if nd:
        work_index['doi_map'][nd] = w.id
    if key:
        work_index['key_map'].setdefault((key, ref.year), w.id)
    return w.id, 'work-new'


def recompute_cite_counts() -> int:
    """Recompute CitedWork.cite_count = # distinct citing papers. Returns the
    number of works with at least one citation."""
    rows = db.execute_sql(
        "SELECT resolved_work_id, COUNT(DISTINCT citing_paper_id) "
        "FROM reference WHERE resolved_work_id IS NOT NULL "
        "GROUP BY resolved_work_id"
    ).fetchall()
    with db.atomic():
        CitedWork.update(cite_count=0).where(CitedWork.cite_count != 0).execute()
        for wid, c in rows:
            CitedWork.update(cite_count=c).where(CitedWork.id == wid).execute()
    return len(rows)


def cluster_works_by_block(max_cluster: int = 25) -> list:
    """Group active CitedWorks by blocking key (first_surname, year) into
    candidate clusters for pass-2 LLM merge.

    Returns clusters (lists of CitedWork) with ≥2 members where at least one is
    not yet merge_checked. Works without a surname are skipped (no reliable
    block key). Oversized blocks (> max_cluster) are dropped here and reported
    by the caller via cluster_overflow().
    """
    blocks = defaultdict(list)
    for w in CitedWork.select().where(CitedWork.merged_into_paper.is_null(True)):
        if not w.first_surname:
            continue
        blocks[(w.first_surname, w.year)].append(w)
    out = []
    for ws in blocks.values():
        if len(ws) < 2 or len(ws) > max_cluster:
            continue
        if all(w.merge_checked for w in ws):
            continue
        out.append(ws)
    return out


def merge_works(keep_id: int, ids: list) -> int:
    """Merge duplicate CitedWorks into keep_id: repoint their citations and
    delete the duplicate rows (works are rebuildable, so no tombstone needed).
    Returns the number of works removed."""
    dups = [i for i in ids if i != keep_id]
    if not dups:
        return 0
    with db.atomic():
        Reference.update(resolved_work=keep_id, match_method='work-llm').where(
            Reference.resolved_work.in_(dups)).execute()
        CitedWork.delete().where(CitedWork.id.in_(dups)).execute()
    return len(dups)


def mark_merge_checked(work_ids: list) -> None:
    """Flag works as adjudicated by the pass-2 LLM merge (so re-runs skip them)."""
    if work_ids:
        CitedWork.update(merge_checked=True).where(
            CitedWork.id.in_(list(work_ids))).execute()


def reconcile_works_with_papers(index=None) -> int:
    """Promote any CitedWork that now matches a held paper: repoint its
    citations to that Paper (resolved_paper) and mark the work as a tombstone
    (merged_into_paper). Run after importing new papers. Returns # promoted."""
    if index is None:
        index = build_resolution_index()
    promoted = 0
    works = list(CitedWork.select().where(CitedWork.merged_into_paper.is_null(True)))
    with db.atomic():
        for w in works:
            pid, method, score = resolve_one(
                w.doi, w.title, w.year, w.authors_json, index)
            if pid is not None:
                Reference.update(
                    resolved_paper=pid, resolved_work=None,
                    match_method=method, match_score=score
                ).where(Reference.resolved_work == w.id).execute()
                CitedWork.update(merged_into_paper=pid).where(
                    CitedWork.id == w.id).execute()
                promoted += 1
    return promoted
