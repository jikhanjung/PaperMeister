#!/usr/bin/env python3
"""Comprehensive snapshot of the local PaperMeister DB.

Reports:
  - Sources / Folders
  - Papers by various slicings (Zotero vs filesystem, has-PDF, stub, etc.)
  - PaperFile status breakdown (PDF vs JSON sibling)
  - Standalone PDFs remaining (Paper.zotero_key == PaperFile.zotero_key)
  - Multi-PDF parents
  - PaperBiblio status pipeline (extracted → needs_review/auto_committed/applied)
  - Passage / FTS row counts
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import peewee
from papermeister.database import init_db
from papermeister.models import (
    Source, Folder, Paper, Author, PaperFile, PaperFolder,
    PaperBiblio, Passage, db,
)


def fmt(n, total=None):
    if total and total > 0:
        return f'{n:>7,} ({100 * n / total:5.1f}%)'
    return f'{n:>7,}'


def section(title):
    print(f'\n=== {title} ===')


def main():
    init_db()

    # ── Sources / Folders ────────────────────────────────────
    section('Sources / Folders')
    print(f'  Sources:               {Source.select().count()}')
    print(f'  Folders (total):       {Folder.select().count()}')
    print(f'  Folders w/ zotero_key: '
          f'{Folder.select().where(Folder.zotero_key != "").count()}')

    # ── Papers ───────────────────────────────────────────────
    section('Papers')
    paper_total = Paper.select().count()
    paper_zotero = Paper.select().where(Paper.zotero_key != '').count()
    paper_local = paper_total - paper_zotero
    print(f'  Total Papers:            {fmt(paper_total)}')
    print(f'  Zotero-sourced:          {fmt(paper_zotero, paper_total)}')
    print(f'  Local (no zotero_key):   {fmt(paper_local, paper_total)}')

    # Stub papers: empty title or null year AND no authors
    stub_count = 0
    for p in Paper.select(Paper.id, Paper.title, Paper.year):
        if (not (p.title or '').strip() or p.year is None):
            if not Author.select().where(Author.paper == p).exists():
                stub_count += 1
    print(f'  Stub (no title/yr/auth): {fmt(stub_count, paper_total)}')

    # Papers with no PaperFile at all
    has_pf_subq = PaperFile.select(PaperFile.paper).distinct()
    no_files = Paper.select().where(~(Paper.id << has_pf_subq)).count()
    print(f'  No PaperFile at all:     {fmt(no_files, paper_total)}')

    # ── PaperFiles ───────────────────────────────────────────
    section('PaperFiles')
    pf_total = PaperFile.select().count()
    is_pdf = ~PaperFile.path.endswith('.json')
    is_json = PaperFile.path.endswith('.json')
    pdf_total = PaperFile.select().where(is_pdf).count()
    json_total = PaperFile.select().where(is_json).count()
    print(f'  Total PaperFiles:      {fmt(pf_total)}')
    print(f'    PDFs:                {fmt(pdf_total, pf_total)}')
    print(f'    JSON siblings:       {fmt(json_total, pf_total)}')

    print('\n  PDF status breakdown:')
    for status in ('pending', 'processed', 'failed'):
        n = PaperFile.select().where(is_pdf & (PaperFile.status == status)).count()
        print(f'    {status:<12} {fmt(n, pdf_total)}')

    n_hash = PaperFile.select().where(is_pdf & (PaperFile.hash != '')).count()
    print(f'  PDFs with hash:        {fmt(n_hash, pdf_total)}')
    n_zk = PaperFile.select().where(is_pdf & (PaperFile.zotero_key != '')).count()
    print(f'  PDFs with zotero_key:  {fmt(n_zk, pdf_total)}')

    # ── Standalone PDFs ──────────────────────────────────────
    section('Standalone PDFs (Paper.zotero_key == PaperFile.zotero_key)')
    standalone_q = (
        PaperFile.select(PaperFile.id)
        .join(Paper)
        .where(
            (Paper.zotero_key != '')
            & (Paper.zotero_key == PaperFile.zotero_key)
            & is_pdf
        )
    )
    standalone_total = standalone_q.count()
    print(f'  Total standalone PDFs:    {fmt(standalone_total)}')
    for status in ('pending', 'processed', 'failed'):
        n = (
            PaperFile.select()
            .join(Paper)
            .where(
                (Paper.zotero_key != '')
                & (Paper.zotero_key == PaperFile.zotero_key)
                & is_pdf
                & (PaperFile.status == status)
            ).count()
        )
        print(f'    {status:<12} {fmt(n, standalone_total)}')

    # ── Multi-PDF parents ────────────────────────────────────
    section('Multi-PDF parents (≥2 PDFs per Paper)')
    multi_pdf_q = (
        PaperFile
        .select(PaperFile.paper, peewee.fn.COUNT(PaperFile.id).alias('n'))
        .where(is_pdf)
        .group_by(PaperFile.paper)
        .having(peewee.fn.COUNT(PaperFile.id) >= 2)
    )
    rows = list(multi_pdf_q)
    print(f'  Papers with ≥2 PDFs:   {fmt(len(rows))}')
    if rows:
        max_pdfs = max(r.n for r in rows)
        total_extra_pdfs = sum(r.n for r in rows) - len(rows)  # PDFs beyond 1st
        print(f'  Max PDFs in one Paper: {max_pdfs}')
        print(f'  Extra PDFs total:      {total_extra_pdfs}')

    # ── PaperBiblio pipeline ────────────────────────────────
    section('PaperBiblio (LLM extractions)')
    biblio_total = PaperBiblio.select().count()
    distinct_papers_with_biblio = (
        PaperBiblio.select(PaperBiblio.paper).distinct().count()
    )
    print(f'  Total biblio rows:           {fmt(biblio_total)}')
    print(f'  Distinct papers w/ biblio:   {fmt(distinct_papers_with_biblio)}')

    print('\n  Status pipeline (P08):')
    for status in ('extracted', 'needs_review', 'auto_committed', 'applied', 'rejected'):
        n = PaperBiblio.select().where(PaperBiblio.status == status).count()
        print(f'    {status:<16} {fmt(n, biblio_total)}')

    print('\n  By source (model):')
    for row in (
        PaperBiblio
        .select(PaperBiblio.source, peewee.fn.COUNT(PaperBiblio.id).alias('n'))
        .group_by(PaperBiblio.source)
        .order_by(peewee.fn.COUNT(PaperBiblio.id).desc())
    ):
        print(f'    {(row.source or "(empty)"):<20} {fmt(row.n, biblio_total)}')

    # Latest applied biblio per paper — the "done" count
    applied_papers = (
        PaperBiblio.select(PaperBiblio.paper).distinct()
        .where(PaperBiblio.status == 'applied').count()
    )
    auto_committed_papers = (
        PaperBiblio.select(PaperBiblio.paper).distinct()
        .where(PaperBiblio.status == 'auto_committed').count()
    )
    print(f'\n  Papers with applied biblio:       {fmt(applied_papers, paper_total)}')
    print(f'  Papers with auto_committed:       {fmt(auto_committed_papers, paper_total)}')

    # ── Passages / FTS ───────────────────────────────────────
    section('Passages / FTS')
    passage_total = Passage.select().count()
    print(f'  Passages:              {fmt(passage_total)}')
    cur = db.execute_sql('SELECT COUNT(*) FROM passage_fts').fetchone()
    fts_count = cur[0] if cur else 0
    print(f'  passage_fts rows:      {fmt(fts_count)}')
    distinct_papers_with_passages = (
        Passage.select(Passage.paper).distinct().count()
    )
    print(f'  Distinct papers w/ passages:  {fmt(distinct_papers_with_passages, paper_total)}')

    # ── Overall pipeline summary ─────────────────────────────
    section('Overall pipeline summary')
    print(f'  Papers in DB:                       {paper_total:>7,}')
    print(f'  → with PDF PaperFile:               '
          f'{(paper_total - no_files):>7,}')
    pdf_processed_papers = (
        Paper
        .select(Paper.id)
        .join(PaperFile)
        .where(is_pdf & (PaperFile.status == 'processed'))
        .distinct().count()
    )
    print(f'  → OCR processed:                    {pdf_processed_papers:>7,}')
    print(f'  → biblio extracted (any status):    {distinct_papers_with_biblio:>7,}')
    print(f'  → biblio applied or auto_committed: '
          f'{(applied_papers + auto_committed_papers):>7,}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
