import re

import peewee

from .models import Folder, Paper, PaperFile, Passage, db


def query_terms(query):
    """Lowercased word tokens from a query, stripped of FTS5 syntax.

    Used for the document-level title boost (below) and for UI highlighting.
    Keeps tokens ≥2 chars or any non-ASCII run (so CJK queries survive).
    """
    toks = re.findall(r'\w+', (query or '').lower(), re.UNICODE)
    stop = {'and', 'or', 'not', 'near'}
    return [t for t in toks if t not in stop and (len(t) >= 2 or not t.isascii())]


def search(query, limit=50, max_passages=200_000):
    """Full-text search using FTS5 with BM25 ranking.

    `limit` is the maximum number of **distinct papers** to return, not the
    number of passages. Prior to 2026-04-12 this was a passage-row limit,
    which meant dense queries (e.g., "trilobite" with ~75k hits) silently
    collapsed to a handful of papers because the top passages clustered on
    a few documents. We now fetch matching passages in BM25 order up to
    `max_passages` and dedupe by paper_id in Python, keeping each paper's
    best-ranked match as its representative.

    Returns list of {'paper': Paper, 'matches': [{'page', 'snippet', 'rank'}]}.
    """
    if not query.strip():
        return []

    def _run_body(q):
        # passage_fts is external content over `passage` (text only): JOIN back
        # to passage for paper_id/page; text is column 0 for snippet().
        return db.execute_sql(
            'SELECT p.paper_id, p.page, p.id AS passage_id, '
            "snippet(passage_fts, 0, '**', '**', '...', 32) as snippet, "
            'bm25(passage_fts) as rank '
            'FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid '
            'WHERE passage_fts MATCH ? '
            'ORDER BY rank LIMIT ?',
            [q, max_passages],
        ).fetchall()

    def _run_meta(q):
        # Document-level title/author matches. Since passage_fts indexes only
        # body text, terms appearing solely in a paper's title or author list
        # would otherwise be unfindable — paper_fts restores that recall.
        return db.execute_sql(
            'SELECT rowid, bm25(paper_fts) as rank '
            'FROM paper_fts WHERE paper_fts MATCH ? '
            'ORDER BY rank LIMIT ?',
            [q, max(limit * 4, 50)],
        ).fetchall()

    try:
        rows = _run_body(query.strip())
        meta_rows = _run_meta(query.strip())
    except Exception:
        # FTS5 syntax error → retry with the query quoted as a literal phrase.
        try:
            q = f'"{query.strip()}"'
            rows = _run_body(q)
            meta_rows = _run_meta(q)
        except Exception:
            return []

    # Dedupe body matches by paper_id, preserving BM25 rank order (first hit =
    # best rank). We stop adding new papers once we hit `limit`, but still
    # collect additional snippets for already-seen papers for the detail view.
    # Trashed papers are skipped (Paper.trashed_at IS NOT NULL); the FTS index
    # itself doesn't track trash state, so we filter post-hoc.
    seen_papers: dict[int, dict] = {}
    skipped_trashed: set[int] = set()
    for paper_id, page, passage_id, snippet, rank in rows:
        if paper_id in skipped_trashed:
            continue
        entry = seen_papers.get(paper_id)
        if entry is None:
            if len(seen_papers) >= limit:
                continue
            paper = Paper.get_by_id(paper_id)
            if paper.trashed_at is not None:
                skipped_trashed.add(paper_id)
                continue
            entry = {'paper': paper, 'matches': [], 'rank': rank}
            seen_papers[paper_id] = entry
        if len(entry['matches']) < 5:  # cap per-paper snippets
            entry['matches'].append({
                'page': page,
                'passage_id': passage_id,
                'snippet': snippet,
                'rank': rank,
            })

    # Fold in title/author-only matches (papers with no body hit). They carry no
    # snippet; the title boost below floats them to the right place.
    for paper_id, rank in meta_rows:
        if paper_id in seen_papers or paper_id in skipped_trashed:
            continue
        if len(seen_papers) >= limit:
            break
        paper = Paper.get_by_id(paper_id)
        if paper.trashed_at is not None:
            skipped_trashed.add(paper_id)
            continue
        seen_papers[paper_id] = {'paper': paper, 'matches': [], 'rank': rank}

    # Document-level title boost. Re-rank into three tiers by how the title
    # matches, ordered by BM25-ish rank within each: all query terms in the
    # title → top, some → middle, none → bottom. A paper whose query is in its
    # TITLE but sparse in the body still ranks above body-heavy papers (the
    # classic "trilobite" problem).
    terms = query_terms(query)

    def _title_tier(paper):
        if not terms:
            return 2
        title = (paper.title or '').lower()
        hits = sum(1 for t in terms if t in title)
        if hits == len(terms):
            return 0
        if hits:
            return 1
        return 2

    return sorted(
        seen_papers.values(),
        key=lambda x: (_title_tier(x['paper']), x['rank']),
    )


def get_paper_passages(paper_id):
    return list(
        Passage.select()
        .where(Passage.paper_id == paper_id)
        .order_by(Passage.page)
    )


def get_papers_in_folder(folder_id):
    return list(
        Paper.select(Paper, PaperFile.status)
        .join(PaperFile, peewee.JOIN.LEFT_OUTER)
        .where(Paper.folder_id == folder_id)
        .order_by(Paper.title)
    )


def get_papers_in_source(source_id):
    return list(
        Paper.select(Paper, PaperFile.status)
        .join(PaperFile, peewee.JOIN.LEFT_OUTER)
        .switch(Paper)
        .join(Folder)
        .where(Folder.source_id == source_id)
        .order_by(Paper.title)
    )


def get_all_papers():
    return list(
        Paper.select(Paper, PaperFile.status)
        .join(PaperFile)
        .order_by(Paper.created_at.desc())
    )
