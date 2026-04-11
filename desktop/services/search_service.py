"""Full-text search wrapper for the desktop app.

Thin adapter on top of `papermeister.search.search()` (FTS5 + BM25 with
title ×10, authors ×5, text ×1 weights). Converts the match dict the core
function returns into `PaperRow` objects the existing PaperListView can
render without a new schema.
"""
from papermeister import search as core_search

from .paper_service import PaperRow, _row_from_paper


def search_papers(query: str, limit: int = 200) -> list[PaperRow]:
    """Run a full-text search and return rows in BM25 rank order.

    Empty / whitespace-only queries return an empty list so callers can
    safely wire this to a live text box without guarding.
    """
    query = (query or '').strip()
    if not query:
        return []

    results = core_search.search(query, limit=limit)
    rows: list[PaperRow] = []
    for entry in results[:limit]:
        paper = entry['paper']
        source_name = ''
        try:
            if paper.folder_id is not None and paper.folder is not None:
                src = paper.folder.source
                if src is not None:
                    source_name = src.name
        except Exception:
            # Folder/Source rows missing shouldn't break the result list.
            source_name = ''
        rows.append(_row_from_paper(paper, source_name))
    return rows
