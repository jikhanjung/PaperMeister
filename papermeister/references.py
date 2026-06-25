"""Persistence helpers for parsed references (P11).

Extraction lives in `biblio.py` (`extract_references_llm`); this module owns
the DB write so the CLI script and the desktop app share one mapping.
"""
import json

from .models import Reference, db


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
