import peewee

from .models import db, Source, Folder, Paper, PaperFile, Passage


def search(query, limit=50):
    """Full-text search using FTS5 with BM25 ranking.
    Returns list of {'paper': Paper, 'matches': [{'page', 'snippet', 'rank'}]}.
    """
    if not query.strip():
        return []

    try:
        rows = db.execute_sql(
            'SELECT paper_id, page, passage_id, '
            "snippet(passage_fts, 2, '**', '**', '...', 32) as snippet, "
            'bm25(passage_fts, 10.0, 5.0, 1.0) as rank '
            'FROM passage_fts WHERE passage_fts MATCH ? '
            'ORDER BY rank LIMIT ?',
            [query.strip(), limit],
        ).fetchall()
    except Exception:
        try:
            rows = db.execute_sql(
                'SELECT paper_id, page, passage_id, '
                "snippet(passage_fts, 2, '**', '**', '...', 32) as snippet, "
                'bm25(passage_fts, 10.0, 5.0, 1.0) as rank '
                'FROM passage_fts WHERE passage_fts MATCH ? '
                'ORDER BY rank LIMIT ?',
                [f'"{query.strip()}"', limit],
            ).fetchall()
        except Exception:
            return []

    seen_papers = {}
    for paper_id, page, passage_id, snippet, rank in rows:
        if paper_id not in seen_papers:
            paper = Paper.get_by_id(paper_id)
            seen_papers[paper_id] = {'paper': paper, 'matches': []}
        seen_papers[paper_id]['matches'].append({
            'page': page,
            'passage_id': passage_id,
            'snippet': snippet,
            'rank': rank,
        })

    return sorted(seen_papers.values(), key=lambda x: x['matches'][0]['rank'])


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
