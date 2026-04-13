"""Paper list + paper detail queries."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from peewee import JOIN, fn

from papermeister.models import (
    Author, Folder, Paper, PaperBiblio, PaperFile, PaperFolder, Source,
)


@dataclass
class PaperRow:
    paper_id: int
    file_id: int | None
    title: str
    authors: str
    year: int | None
    journal: str
    source_name: str
    folder_id: int | None  # used by Ctrl+click → reveal in SourceNav
    status: str  # PaperFile.status — pending/processed/failed, or 'none'
    is_stub: bool


def _author_string(paper_id: int) -> str:
    authors = (
        Author.select(Author.name)
        .where(Author.paper == paper_id)
        .order_by(Author.order)
    )
    names = [a.name for a in authors]
    if not names:
        return ''
    if len(names) > 3:
        return ', '.join(names[:2]) + f' et al.'
    return ', '.join(names)


def _is_cjk_name(name: str) -> bool:
    """True if the name is predominantly CJK characters (Korean/Japanese/Chinese)."""
    from desktop.services.biblio_service import _is_cjk_char
    cjk_count = sum(1 for c in name if _is_cjk_char(c))
    alpha_count = sum(1 for c in name if c.isalpha())
    return alpha_count > 0 and cjk_count > alpha_count / 2


def _cite_name(full_name: str) -> str:
    """Display name for citation: full name for CJK, lastname for Western."""
    if _is_cjk_name(full_name):
        return full_name.strip()
    from desktop.services.biblio_service import split_author_name
    _first, last = split_author_name(full_name)
    return last


def _author_cite(paper_id: int) -> str:
    """Citation-style author string.

    CJK names use full name + Korean conjunctions:
      1: 정직한,  2: 정직한과 최덕근,  3+: 정직한 외
    Western names use lastname + English conjunctions:
      1: Smith,  2: Smith and Kim,  3+: Smith et al.
    Mixed: follows the first author's locale.
    """
    authors = (
        Author.select(Author.name)
        .where(Author.paper == paper_id)
        .order_by(Author.order)
    )
    names = [a.name for a in authors]
    if not names:
        return ''
    cites = [_cite_name(n) for n in names]
    cjk = _is_cjk_name(names[0])
    if len(cites) == 1:
        return cites[0]
    if len(cites) == 2:
        conj = '과 ' if cjk else ' and '
        return f'{cites[0]}{conj}{cites[1]}'
    suffix = ' 외' if cjk else ' et al.'
    return f'{cites[0]}{suffix}'


def _is_stub(paper: Paper) -> bool:
    return (
        (paper.title or '').strip() == '' or
        paper.year is None
    ) and Author.select().where(Author.paper == paper).count() == 0


def _primary_file(paper) -> PaperFile | None:
    """Return the best PaperFile for a paper, preferring PDFs over JSON."""
    files = list(PaperFile.select().where(PaperFile.paper == paper).order_by(PaperFile.id))
    if not files:
        return None
    for f in files:
        if not f.path.lower().endswith('.json'):
            return f
    return files[0]  # all JSON — return first


def _row_from_paper(paper: Paper, source_name: str) -> PaperRow:
    pfile = _primary_file(paper)
    file_status = pfile.status if pfile else 'none'
    if file_status == 'processed':
        has_applied = (
            PaperBiblio.select()
            .where(PaperBiblio.paper == paper, PaperBiblio.status == 'applied')
            .exists()
        )
        if has_applied:
            file_status = 'done'
    display_title = paper.title or '(untitled)'
    return PaperRow(
        paper_id=paper.id,
        file_id=pfile.id if pfile else None,
        title=display_title,
        authors=_author_cite(paper.id),
        year=paper.year,
        journal=paper.journal or '',
        source_name=source_name,
        folder_id=paper.folder_id,
        status=file_status,
        is_stub=_is_stub(paper),
    )


def list_by_library(key: str, limit: int = 500) -> list[PaperRow]:
    """Paper rows for a Library folder. Cheap-first joins; no N+1 by design."""
    rows: list[PaperRow] = []

    if key == 'all':
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .order_by(Paper.id.desc())
            .limit(limit)
        )
    elif key in ('pending', 'processed', 'failed'):
        paper_ids = [
            pf.paper_id for pf in (
                PaperFile
                .select(PaperFile.paper)
                .where(PaperFile.status == key)
                .order_by(PaperFile.id.desc())
                .limit(limit)
            )
        ]
        if not paper_ids:
            return rows
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.id.in_(paper_ids))
            .order_by(Paper.id.desc())
        )
    elif key == 'needs_review':
        # Same helper the Library tree uses for the count — guaranteed
        # to return the identical set of paper_ids.
        from .library import needs_review_paper_ids
        biblio_paper_ids = needs_review_paper_ids()
        if not biblio_paper_ids:
            return rows
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.id.in_(biblio_paper_ids))
            .order_by(Paper.id.desc())
            .limit(limit)
        )
    elif key == 'recent':
        cutoff = datetime.now() - timedelta(days=30)
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.created_at >= cutoff)
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
    else:
        return rows

    for paper in query:
        source_name = ''
        if paper.folder_id is not None and paper.folder is not None:
            src = paper.folder.source
            if src is not None:
                source_name = src.name
        rows.append(_row_from_paper(paper, source_name))
    return rows


def list_by_folder(folder_id: int, limit: int = 500) -> list[PaperRow]:
    query = (
        Paper.select()
        .where(Paper.folder == folder_id)
        .order_by(Paper.id.desc())
        .limit(limit)
    )
    folder = Folder.get_or_none(Folder.id == folder_id)
    source_name = folder.source.name if (folder and folder.source) else ''
    return [_row_from_paper(p, source_name) for p in query]


def list_by_source(source_id: int, limit: int = 500) -> list[PaperRow]:
    query = (
        Paper
        .select(Paper, Folder, Source)
        .join(Folder, on=(Paper.folder == Folder.id))
        .join(Source, on=(Folder.source == Source.id))
        .where(Source.id == source_id)
        .order_by(Paper.id.desc())
        .limit(limit)
    )
    rows: list[PaperRow] = []
    for p in query:
        source_name = p.folder.source.name if (p.folder and p.folder.source) else ''
        rows.append(_row_from_paper(p, source_name))
    return rows


@dataclass
class PaperDetail:
    paper_id: int
    title: str
    authors: str
    year: int | None
    journal: str
    doi: str
    source_name: str
    folder_name: str
    folder_id: int | None  # primary folder (Paper.folder)
    collections: list[tuple[int, str]]  # [(folder_id, "Parent › Child › Leaf"), ...]
    file_path: str
    file_status: str
    file_hash: str
    file_zotero_key: str
    is_stub: bool
    latest_biblio: dict | None  # flattened PaperBiblio or None
    ocr_preview: str | None


def load_detail(paper_id: int) -> PaperDetail | None:
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return None
    authors = _author_string(paper.id)
    folder = paper.folder
    source_name = folder.source.name if folder and folder.source else ''
    folder_name = folder.name if folder else ''
    folder_id = folder.id if folder else None
    # Build all collection paths from PaperFolder junction table.
    collections: list[tuple[int, str]] = []
    pf_rows = (
        PaperFolder.select(PaperFolder.folder)
        .where(PaperFolder.paper == paper)
    )
    for pf in pf_rows:
        f = pf.folder
        path_parts: list[str] = []
        cursor = f
        while cursor is not None:
            path_parts.append(cursor.name)
            cursor = cursor.parent
        path_parts.reverse()
        collections.append((f.id, ' \u203a '.join(path_parts)))
    # If PaperFolder is empty (not yet populated), fall back to Paper.folder.
    if not collections and folder:
        path_parts = []
        cursor = folder
        while cursor is not None:
            path_parts.append(cursor.name)
            cursor = cursor.parent
        path_parts.reverse()
        collections.append((folder.id, ' \u203a '.join(path_parts)))
    pfile = _primary_file(paper)
    file_path = pfile.path if pfile else ''
    file_status = pfile.status if pfile else 'none'
    file_hash = pfile.hash if pfile else ''
    file_zotero_key = pfile.zotero_key if pfile else ''

    latest = (
        PaperBiblio.select()
        .where(PaperBiblio.paper == paper)
        .order_by(PaperBiblio.extracted_at.desc())
        .first()
    )
    biblio_dict = None
    if latest:
        biblio_dict = {
            'title':      latest.title,
            'authors_json': latest.authors_json,
            'year':       latest.year,
            'journal':    latest.journal,
            'doi':        latest.doi,
            'doc_type':   latest.doc_type,
            'confidence': latest.confidence,
            'needs_visual_review': latest.needs_visual_review,
            'source':     latest.source,
            'model_version': latest.model_version,
        }

    return PaperDetail(
        paper_id=paper.id,
        title=paper.title or '',
        authors=authors,
        year=paper.year,
        journal=paper.journal or '',
        doi=paper.doi or '',
        source_name=source_name,
        folder_name=folder_name,
        folder_id=folder_id,
        collections=collections,
        file_path=file_path,
        file_status=file_status,
        file_hash=file_hash,
        file_zotero_key=file_zotero_key,
        is_stub=_is_stub(paper),
        latest_biblio=biblio_dict,
        ocr_preview=None,  # Phase 4: read from ocr_json cache
    )
