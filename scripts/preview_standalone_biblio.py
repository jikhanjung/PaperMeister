#!/usr/bin/env python3
"""Print a review table of LLM-extracted bibliographic info for standalone PDFs.

Read-only — does NOT modify Zotero or DB.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Paper, PaperFile, PaperBiblio


def main():
    init_db()

    # Standalone papers (Paper.zotero_key == PaperFile.zotero_key) with biblio extractions
    rows = []
    q = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
            & (Paper.zotero_key == PaperFile.zotero_key)
        )
    )

    for pf in q:
        p = pf.paper
        biblio = (
            PaperBiblio.select()
            .where((PaperBiblio.paper == p) & (PaperBiblio.file_hash == pf.hash))
            .order_by(PaperBiblio.extracted_at.desc())
            .first()
        )
        rows.append((p, pf, biblio))

    print(f'Standalone PDFs: {len(rows)}\n')

    have_biblio = sum(1 for r in rows if r[2])
    print(f'With LLM extraction: {have_biblio}/{len(rows)}\n')

    print('=' * 100)
    for i, (p, pf, b) in enumerate(rows, 1):
        gt_authors = list(Author.select().where(Author.paper == p).order_by(Author.order))
        print(f'\n[{i}] paper_id={p.id}  zotero_key={pf.zotero_key}  doc_type={b.doc_type if b else "—"}  conf={b.confidence if b else "—"}')
        print(f'    Current title:  {p.title[:90] or "(empty)"}')
        print(f'    Current year:   {p.year or "—"}    journal: {p.journal or "—"}    doi: {p.doi or "—"}')
        print(f'    Current authors: {", ".join(a.name for a in gt_authors) or "(none)"}')
        if b:
            authors = json.loads(b.authors_json or '[]')
            print(f'    LLM title:      {b.title[:90]}')
            print(f'    LLM year:       {b.year or "—"}    journal: {b.journal or "—"}    doi: {b.doi or "—"}')
            print(f'    LLM authors:    {", ".join(authors[:6])}{"..." if len(authors) > 6 else ""}')
            if b.notes:
                print(f'    Notes:          {b.notes[:100]}')
        else:
            print(f'    (no LLM extraction yet)')


if __name__ == '__main__':
    main()
