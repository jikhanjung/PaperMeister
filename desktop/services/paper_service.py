"""Paper list + paper detail queries."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from peewee import JOIN, fn

from papermeister.models import (
    Author,
    CitedWork,
    Figure,
    Folder,
    Paper,
    PaperBiblio,
    PaperFile,
    PaperFolder,
    Reference,
    Source,
    db,
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
    # True when the Zotero record is the attachment itself (no parent item).
    # Drives the "re-OCR to create parent" right-click action.
    is_standalone: bool = False
    # Search-only: the best matching passage as HTML (matched terms bolded).
    # Empty for normal folder/library listings. Shown as a row tooltip.
    snippet: str = ''
    # The pipeline after OCR, one state per stage (see `Stages`): what the
    # list's Stages column draws and its tooltip explains.
    stages: 'Stages | None' = None


#: Stage states, in order of progress. `STAGE_KEYS` is the column's order.
STAGE_KEYS = ('ocr', 'biblio', 'refs', 'figs')
STAGE_NAMES = {'ocr': 'OCR', 'biblio': 'Bibliography', 'refs': 'References', 'figs': 'Figures'}


@dataclass(frozen=True)
class Stages:
    """Where a paper is in the pipeline, per stage.

    ocr:    none | pending | failed | done
    biblio: none | extracted (an extraction exists, not applied) | review | done
    refs:   none | partial (attempted, not checked) | failed (attempts exhausted) | done
    figs:   none | assembled | linked | split
    """
    ocr: str = 'none'
    biblio: str = 'none'
    refs: str = 'none'
    figs: str = 'none'
    detail: dict = field(default_factory=dict)      # stage -> one line for the tooltip / the card

    def state(self, key: str) -> str:
        return getattr(self, key)

    def tooltip(self) -> str:
        return '\n'.join(f'{STAGE_NAMES[k]}: {self.detail.get(k) or self.state(k)}' for k in STAGE_KEYS)


def _ocr_stage(file_status: str) -> str:
    return {'processed': 'done', 'done': 'done', 'review': 'done', 'pending': 'pending',
            'failed': 'failed'}.get(file_status, 'none')


def _biblio_stage(statuses: set[str]) -> tuple[str, str]:
    if statuses & {'applied', 'auto_committed'}:
        return 'done', 'applied'
    if 'needs_review' in statuses:
        return 'review', 'extracted, needs review'
    if statuses:
        return 'extracted', 'extracted (' + ', '.join(sorted(statuses)) + ')'
    return 'none', 'not extracted'


def _refs_stage(paper: Paper, n_refs: int, n_held: int) -> tuple[str, str]:
    from papermeister.references import MAX_REFS_ATTEMPTS
    if paper.references_checked:
        if n_refs:
            return 'done', f'{n_refs} extracted, {n_held} in library'
        return 'done', 'checked — no references section'
    if (paper.references_attempts or 0) >= MAX_REFS_ATTEMPTS:
        return 'failed', f'gave up after {paper.references_attempts} attempts' + (f' ({n_refs} partial)' if n_refs else '')
    if n_refs or paper.references_attempts:
        return 'partial', f'{n_refs} extracted so far (partial, attempt {paper.references_attempts})'
    return 'none', 'not extracted'


def _figs_stage(n: int, linked: int, split: int, panels: int) -> tuple[str, str]:
    if not n:
        return 'none', 'not assembled'
    if split:
        return 'split', f'{n} figures · {linked} captioned · {split} split into {panels} panels'
    if linked:
        return 'linked', f'{n} figures · {linked} captioned · no panels yet'
    return 'assembled', f'{n} figures assembled · no captions yet'


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
        return ', '.join(names[:2]) + ' et al.'
    return ', '.join(names)


def _is_cjk_name(name: str) -> bool:
    """True if the name is predominantly CJK characters (Korean/Japanese/Chinese)."""
    from desktop.services.biblio_service import _is_cjk_char
    cjk_count = sum(1 for c in name if _is_cjk_char(c))
    alpha_count = sum(1 for c in name if c.isalpha())
    return alpha_count > 0 and cjk_count > alpha_count / 2


def _cite_name(full_name: str) -> str:
    """Display name for citation: surname-first joined for CJK (정직한), lastname
    for Western (Smith).

    Every stored CJK form has the surname first — "Last, First" (Zotero split),
    legacy "Last First", or unspaced "정직한" — so dropping commas/spaces yields
    LastnameFirstname per the Korean/Japanese convention (no separator).
    """
    if _is_cjk_name(full_name):
        return re.sub(r'[\s,]+', '', full_name)
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
    return _cite_names([a.name for a in authors])


def _cite_names(names: list[str]) -> str:
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


class _RowContext:
    """What every row of a list needs, fetched for the whole list at once.

    Per row the list used to ask the DB three or four times — files, biblio
    statuses, authors, and a stub check — so a 500-row list was ~1,500
    queries and half a second on the UI thread, felt at every click on a
    folder. Three queries over the list's paper ids replace them.
    """

    def __init__(self, papers: list[Paper]):
        ids = [p.id for p in papers]
        self.files: dict[int, list[PaperFile]] = {}
        self.biblio: dict[int, set[str]] = {}
        self.authors: dict[int, list[str]] = {}
        if not ids:
            return
        for f in PaperFile.select().where(PaperFile.paper << ids).order_by(PaperFile.id):
            self.files.setdefault(f.paper_id, []).append(f)
        for b in PaperBiblio.select(PaperBiblio.paper, PaperBiblio.status).where(PaperBiblio.paper << ids):
            self.biblio.setdefault(b.paper_id, set()).add(b.status)
        for a in (Author.select(Author.paper, Author.name).where(Author.paper << ids)
                  .order_by(Author.paper, Author.order)):
            self.authors.setdefault(a.paper_id, []).append(a.name)
        # The stages after biblio, two grouped queries: references (count,
        # in library) and figures (count, captioned, split, panels).
        self.refs: dict[int, tuple[int, int]] = {}
        for r in (Reference.select(Reference.citing_paper, fn.COUNT(Reference.id).alias('n'),
                                   fn.SUM(Reference.resolved_paper.is_null(False)).alias('held'))
                  .where(Reference.citing_paper << ids).group_by(Reference.citing_paper).dicts()):
            self.refs[r['citing_paper']] = (int(r['n'] or 0), int(r['held'] or 0))
        self.figs: dict[int, tuple[int, int, int, int]] = {}
        for r in _figure_counts_query(ids).dicts():
            self.figs[r['paper']] = (int(r['n'] or 0), int(r['linked'] or 0), int(r['split'] or 0), int(r['panels'] or 0))

    def stages(self, paper: Paper, file_status: str) -> Stages:
        return _stages_from(paper, file_status, self.biblio_statuses(paper),
                            self.refs.get(paper.id, (0, 0)), self.figs.get(paper.id, (0, 0, 0, 0)))

    def primary_file(self, paper: Paper) -> PaperFile | None:
        return _pick_primary(self.files.get(paper.id, []))

    def biblio_statuses(self, paper: Paper) -> set[str]:
        return self.biblio.get(paper.id, set())

    def author_cite(self, paper: Paper) -> str:
        return _cite_names(self.authors.get(paper.id, []))

    def is_stub(self, paper: Paper) -> bool:
        return ((paper.title or '').strip() == '' or paper.year is None) and not self.authors.get(paper.id)


def _figure_counts_query(ids):
    """Per paper: figures (not folded, not placeholders), captioned, split, panels."""
    from papermeister.figure_store import PAGE
    from papermeister.models import FigurePanel
    panels = (FigurePanel.select(FigurePanel.figure, fn.COUNT(FigurePanel.id).alias('k'))
              .group_by(FigurePanel.figure).alias('pn'))
    return (Figure.select(Figure.paper, fn.COUNT(Figure.id).alias('n'),
                          fn.SUM(Figure.link_key != '').alias('linked'),
                          fn.SUM(Figure.panel_key != '').alias('split'),
                          fn.COALESCE(fn.SUM(panels.c.k), 0).alias('panels'))
            .join(panels, JOIN.LEFT_OUTER, on=(panels.c.figure_id == Figure.id))
            .where((Figure.paper << ids) & (Figure.dismissed == False) & (Figure.assembly != PAGE))  # noqa: E712
            .group_by(Figure.paper))


def _stages_from(paper: Paper, file_status: str, biblio: set[str], refs: tuple[int, int],
                 figs: tuple[int, int, int, int]) -> Stages:
    b_state, b_detail = _biblio_stage(biblio)
    r_state, r_detail = _refs_stage(paper, *refs)
    f_state, f_detail = _figs_stage(*figs)
    o_state = _ocr_stage(file_status)
    return Stages(ocr=o_state, biblio=b_state, refs=r_state, figs=f_state,
                  detail={'ocr': {'done': 'processed', 'pending': 'pending', 'failed': 'failed'}.get(o_state, 'no PDF'),
                          'biblio': b_detail, 'refs': r_detail, 'figs': f_detail})


def load_stages(paper_id: int) -> Stages | None:
    """One paper's pipeline stages (the Metadata tab's card; the single-row refresh)."""
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return None
    pfile = _primary_file(paper)
    biblio = {b.status for b in PaperBiblio.select(PaperBiblio.status).where(PaperBiblio.paper == paper)}
    n_refs = Reference.select().where(Reference.citing_paper == paper).count()
    n_held = Reference.select().where((Reference.citing_paper == paper)
                                      & Reference.resolved_paper.is_null(False)).count()
    figs = (0, 0, 0, 0)
    for r in _figure_counts_query([paper.id]).dicts():
        figs = (int(r['n'] or 0), int(r['linked'] or 0), int(r['split'] or 0), int(r['panels'] or 0))
    return _stages_from(paper, pfile.status if pfile else 'none', biblio, (n_refs, n_held), figs)


def _pick_primary(files: list[PaperFile]) -> PaperFile | None:
    if not files:
        return None
    for f in files:
        if f.path.lower().endswith('.pdf'):
            return f
    for f in files:
        if not f.path.lower().endswith('.json'):
            return f
    return files[0]  # all JSON — return first


def _primary_file(paper) -> PaperFile | None:
    """Return the best PaperFile for a paper.

    Prefer an actual PDF (the OCR target) so a paper's pill reflects its PDF,
    not a skipped supplementary (.txt/.doc) or a derived JSON sibling. Falls
    back to any non-JSON, then the first file.
    """
    return _pick_primary(list(PaperFile.select().where(PaperFile.paper == paper).order_by(PaperFile.id)))


def _row_from_paper(paper: Paper, source_name: str, ctx: _RowContext | None = None) -> PaperRow:
    """One list row. With `ctx` (a whole list) nothing here touches the DB;
    without it (one row, `row_for_paper`) the same facts are queried."""
    pfile = ctx.primary_file(paper) if ctx else _primary_file(paper)
    file_status = pfile.status if pfile else 'none'
    if file_status == 'processed':
        # Derive a richer pill from the paper's biblio state: applied/committed
        # → 'done', else a needs_review extraction → 'review' (distinct from a
        # plain OCR'd paper).
        biblio_statuses = ctx.biblio_statuses(paper) if ctx else {
            b.status for b in
            PaperBiblio.select(PaperBiblio.status).where(PaperBiblio.paper == paper)
        }
        if biblio_statuses & {'applied', 'auto_committed'}:
            file_status = 'done'
        elif 'needs_review' in biblio_statuses:
            file_status = 'review'
    display_title = paper.title or '(untitled)'
    is_standalone = bool(
        paper.zotero_key
        and pfile is not None
        and paper.zotero_key == pfile.zotero_key
    )
    return PaperRow(
        paper_id=paper.id,
        file_id=pfile.id if pfile else None,
        title=display_title,
        authors=ctx.author_cite(paper) if ctx else _author_cite(paper.id),
        year=paper.year,
        journal=paper.journal or '',
        source_name=source_name,
        folder_id=paper.folder_id,
        status=file_status,
        is_stub=ctx.is_stub(paper) if ctx else _is_stub(paper),
        stages=ctx.stages(paper, pfile.status if pfile else 'none') if ctx else load_stages(paper.id),
        is_standalone=is_standalone,
    )


def row_for_paper(paper_id: int) -> PaperRow | None:
    """Build a fresh PaperRow for a single paper — used to refresh one list row
    in place after a biblio apply changed its title/authors/year/status."""
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return None
    source_name = (
        paper.folder.source.name
        if (paper.folder and paper.folder.source) else ''
    )
    return _row_from_paper(paper, source_name)


def list_by_library(key: str, limit: int = 500) -> list[PaperRow]:
    """Paper rows for a Library folder. Cheap-first joins; no N+1 by design.

    All keys except 'trash' filter out trashed papers; 'trash' returns the
    inverse.
    """
    rows: list[PaperRow] = []

    if key == 'all':
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.trashed_at.is_null())
            .order_by(Paper.id.desc())
            .limit(limit)
        )
    elif key in ('pending', 'processed', 'failed'):
        # Distinct paper ids that have at least one PaperFile with this status.
        paper_ids = list({
            pf.paper_id for pf in
            PaperFile.select(PaperFile.paper).where(PaperFile.status == key)
        })
        if not paper_ids:
            return rows
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.id.in_(paper_ids) & Paper.trashed_at.is_null())
            .order_by(Paper.id.desc())
            .limit(limit)
        )
    elif key == 'needs_review':
        # Same helper the Library tree uses for the count — guaranteed
        # to return the identical set of paper_ids (already excludes trashed).
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
            .where((Paper.created_at >= cutoff) & Paper.trashed_at.is_null())
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
    elif key == 'trash':
        query = (
            Paper
            .select(Paper, Folder, Source)
            .join(Folder, JOIN.LEFT_OUTER, on=(Paper.folder == Folder.id))
            .join(Source, JOIN.LEFT_OUTER, on=(Folder.source == Source.id))
            .where(Paper.trashed_at.is_null(False))
            .order_by(Paper.trashed_at.desc())
            .limit(limit)
        )
    else:
        return rows

    papers = list(query)
    ctx = _RowContext(papers)
    for paper in papers:
        source_name = ''
        if paper.folder_id is not None and paper.folder is not None:
            src = paper.folder.source
            if src is not None:
                source_name = src.name
        rows.append(_row_from_paper(paper, source_name, ctx))
    return rows


def list_by_folder(folder_id: int, limit: int = 500) -> list[PaperRow]:
    # Use PaperFolder M2M junction table — Paper.folder is legacy 1:1 and
    # misses papers that belong to multiple collections.
    query = (
        Paper.select()
        .join(PaperFolder, on=(PaperFolder.paper == Paper.id))
        .where(
            (PaperFolder.folder == folder_id)
            & (Paper.trashed_at.is_null())
        )
        .order_by(Paper.id.desc())
        .limit(limit)
    )
    folder = Folder.get_or_none(Folder.id == folder_id)
    source_name = folder.source.name if (folder and folder.source) else ''
    papers = list(query)
    ctx = _RowContext(papers)
    return [_row_from_paper(p, source_name, ctx) for p in papers]


def list_by_source(source_id: int, limit: int = 500) -> list[PaperRow]:
    query = (
        Paper
        .select(Paper, Folder, Source)
        .join(Folder, on=(Paper.folder == Folder.id))
        .join(Source, on=(Folder.source == Source.id))
        .where((Source.id == source_id) & (Paper.trashed_at.is_null()))
        .order_by(Paper.id.desc())
        .limit(limit)
    )
    rows: list[PaperRow] = []
    papers = list(query)
    ctx = _RowContext(papers)
    for p in papers:
        source_name = p.folder.source.name if (p.folder and p.folder.source) else ''
        rows.append(_row_from_paper(p, source_name, ctx))
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
    paper_zotero_key: str
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
        paper_zotero_key=paper.zotero_key or '',
        is_stub=_is_stub(paper),
        latest_biblio=biblio_dict,
        ocr_preview=None,  # Phase 4: read from ocr_json cache
    )


@dataclass
class ReferenceRow:
    """One parsed bibliography entry for the References detail tab (P11)."""
    id: int
    order_index: int
    raw_text: str
    authors: list  # [{"family","given"}, ...] or ["Name", ...]
    year: int | None
    title: str
    container: str
    volume: str
    issue: str
    pages: str
    doi: str
    ref_type: str
    resolved_paper_id: int | None   # set → we own this cited work (held)
    match_method: str               # doi|title|work-*|'' (unresolved)
    # P11 Phase 2: external canonical node + how many OTHER library papers
    # cite the same external work (co-citation).
    resolved_work_id: int | None = None
    cocite_count: int = 0

    def citation(self) -> str:
        """A compact author · year · container line for the card subtitle."""
        names = []
        for a in self.authors[:6]:
            if isinstance(a, dict):
                fam = (a.get('family') or '').strip()
                giv = (a.get('given') or '').strip()
                names.append(f'{fam}, {giv}'.strip(', ') if fam else giv)
            elif a:
                names.append(str(a))
        who = '; '.join(n for n in names if n)
        if len(self.authors) > 6:
            who += ' et al.'
        parts = []
        if who:
            parts.append(who)
        if self.year:
            parts.append(f'({self.year})')
        # container volume(issue), pages
        vol = self.volume + (f'({self.issue})' if self.issue else '')
        bits = [b for b in (vol, self.pages) if b]
        tail = self.container
        if bits:
            tail = f'{tail} {", ".join(bits)}' if tail else ', '.join(bits)
        if tail:
            parts.append(tail)
        return ' '.join(parts)


@dataclass
class CitedByRow:
    """A library paper whose bibliography cites the current paper (P11 reverse)."""
    paper_id: int
    title: str
    year: int | None
    authors: str  # citation-style


def load_cited_by(paper_id: int) -> list[CitedByRow]:
    """Library papers that cite this paper (their Reference resolved to it).

    Deduped by citing paper, trashed papers excluded, newest first.
    """
    citing_ids = [
        r.citing_paper_id for r in
        Reference.select(Reference.citing_paper)
        .where(Reference.resolved_paper == paper_id)
        .distinct()
    ]
    rows: list[CitedByRow] = []
    for pid in citing_ids:
        if pid == paper_id:
            continue  # ignore self-citation artifacts
        p = Paper.get_or_none(Paper.id == pid)
        if p is None or p.trashed_at is not None:
            continue
        rows.append(CitedByRow(
            paper_id=pid,
            title=p.title or '',
            year=p.year,
            authors=_author_cite(pid),
        ))
    rows.sort(key=lambda r: (-(r.year or 0), r.title.lower()))
    return rows


def load_references(paper_id: int) -> list[ReferenceRow]:
    """All parsed references for a citing paper, ordered as in the bibliography."""
    import json
    rows: list[ReferenceRow] = []
    q = (
        Reference.select()
        .where(Reference.citing_paper == paper_id)
        .order_by(Reference.order_index)
    )
    for r in q:
        try:
            authors = json.loads(r.authors_json or '[]')
        except (json.JSONDecodeError, TypeError):
            authors = []
        rows.append(ReferenceRow(
            id=r.id,
            order_index=r.order_index,
            raw_text=r.raw_text or '',
            authors=authors if isinstance(authors, list) else [],
            year=r.year,
            title=r.title or '',
            container=r.container or '',
            volume=r.volume or '',
            issue=r.issue or '',
            pages=r.pages or '',
            doi=r.doi or '',
            ref_type=r.ref_type or 'unknown',
            resolved_paper_id=r.resolved_paper_id,
            match_method=r.match_method or '',
            resolved_work_id=r.resolved_work_id,
        ))

    # Co-citation: for the external works these references point to, how many
    # distinct library papers cite each one. One aggregate query (not N+1).
    # cocite_count excludes this paper itself (it always cites its own refs).
    work_ids = {r.resolved_work_id for r in rows if r.resolved_work_id}
    if work_ids:
        counts: dict[int, int] = {}
        cur = db.execute_sql(
            "SELECT resolved_work_id, COUNT(DISTINCT citing_paper_id) "
            "FROM reference WHERE resolved_work_id IN ({}) "
            "GROUP BY resolved_work_id".format(','.join('?' * len(work_ids))),
            tuple(work_ids),
        )
        for wid, c in cur.fetchall():
            counts[wid] = c
        for r in rows:
            if r.resolved_work_id:
                r.cocite_count = max(0, counts.get(r.resolved_work_id, 1) - 1)
    return rows


# ── Cited works (P11 Phase 2) ────────────────────────────────


@dataclass
class CitedWorkRow:
    """A canonical external work for the Cited Works browser."""
    work_id: int
    title: str
    authors: str
    year: int | None
    container: str
    doi: str
    cite_count: int  # distinct library papers citing it


def _work_authors(authors_json: str) -> str:
    """Compact author string for a CitedWork (first author surname-style)."""
    import json
    try:
        authors = json.loads(authors_json or '[]')
    except (json.JSONDecodeError, TypeError):
        authors = []
    names = []
    for a in authors[:3]:
        if isinstance(a, dict):
            fam = (a.get('family') or '').strip()
            names.append(fam or (a.get('given') or '').strip())
        elif a:
            names.append(str(a))
    who = ', '.join(n for n in names if n)
    if len([a for a in authors if a]) > 3:
        who += ' et al.'
    return who


def top_cited_works(limit: int = 300, min_cites: int = 2, query: str = '') -> list[CitedWorkRow]:
    """External works ranked by how many library papers cite them.

    cite_count is computed live (distinct citing papers) so it's correct even
    if the denormalized CitedWork.cite_count hasn't been recomputed. Tombstoned
    (promoted) works are excluded. `query` filters on title/author substring.
    """
    cur = db.execute_sql(
        "SELECT resolved_work_id, COUNT(DISTINCT citing_paper_id) c "
        "FROM reference WHERE resolved_work_id IS NOT NULL "
        "GROUP BY resolved_work_id HAVING c >= ?",
        (min_cites,),
    )
    counts = dict(cur.fetchall())
    if not counts:
        return []
    ranked = sorted(counts, key=lambda w: -counts[w])
    head = ranked[: max(limit * 3, limit)]  # headroom for filter/tombstone drops
    works = {
        w.id: w for w in
        CitedWork.select().where(
            CitedWork.id.in_(head) & CitedWork.merged_into_paper.is_null(True)
        )
    }
    ql = query.lower().strip()
    out: list[CitedWorkRow] = []
    for wid in ranked:
        w = works.get(wid)
        if w is None:
            continue
        authors = _work_authors(w.authors_json)
        if ql and ql not in (w.title or '').lower() and ql not in authors.lower():
            continue
        out.append(CitedWorkRow(
            work_id=wid,
            title=w.title or '',
            authors=authors,
            year=w.year,
            container=w.container or '',
            doi=w.doi or '',
            cite_count=counts[wid],
        ))
        if len(out) >= limit:
            break
    return out


def load_work_cociters(work_id: int, exclude_paper_id: int | None = None) -> list[CitedByRow]:
    """Library papers that cite a given external work (resolved_work)."""
    citing_ids = [
        r.citing_paper_id for r in
        Reference.select(Reference.citing_paper)
        .where(Reference.resolved_work == work_id)
        .distinct()
    ]
    rows: list[CitedByRow] = []
    for pid in citing_ids:
        if pid == exclude_paper_id:
            continue
        p = Paper.get_or_none(Paper.id == pid)
        if p is None or p.trashed_at is not None:
            continue
        rows.append(CitedByRow(
            paper_id=pid, title=p.title or '', year=p.year, authors=_author_cite(pid),
        ))
    rows.sort(key=lambda r: (-(r.year or 0), r.title.lower()))
    return rows


# ── Citation network (ego graph) ─────────────────────────────────

@dataclass
class EgoNode:
    key: str              # "p{id}" (held paper) or "w{id}" (external CitedWork)
    paper_id: int | None  # Paper.id if held (clickable to re-center), else None
    label: str            # compact "Author Year" for the graph node
    title: str            # full title (tooltip)
    kind: str             # 'held_pdf' | 'held' | 'external'


def _pk(i: int) -> str:
    return f"p{i}"


def _wk(i: int) -> str:
    return f"w{i}"


def load_ego_network(paper_id: int, hops: int = 1, max_nodes: int = 80):
    """Full citation ego network around a held paper.

    Includes both held papers (`reference.resolved_paper`) AND external cited
    works (`reference.resolved_work` — references-extracted, not in the library).
    Only held papers expand (we don't have external works' own reference lists);
    external works are leaves. Held papers are prioritized under `max_nodes`.

    Returns (center_key, nodes: dict[key -> EgoNode], edges: list[(src_key, dst_key)]).
    """
    held = {paper_id}     # reached held Paper ids
    works: set[int] = set()   # reached external CitedWork ids
    frontier = {paper_id}

    for _ in range(max(1, hops)):
        if not frontier or (len(held) + len(works)) >= max_nodes:
            break
        ph = ",".join("?" * len(frontier))
        fp = list(frontier)
        hh = db.execute_sql(
            f"SELECT DISTINCT citing_paper_id, resolved_paper_id FROM reference "
            f"WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id "
            f"AND (citing_paper_id IN ({ph}) OR resolved_paper_id IN ({ph}))",
            fp + fp).fetchall()
        hw = db.execute_sql(
            f"SELECT DISTINCT resolved_work_id FROM reference "
            f"WHERE resolved_work_id IS NOT NULL AND citing_paper_id IN ({ph})",
            fp).fetchall()
        cand_held: set[int] = set()
        for s, d in hh:
            cand_held.update((s, d))
        cand_work = {w for (w,) in hw}
        new_held = sorted(cand_held - held)
        for i in new_held:                       # held first (higher value)
            if len(held) + len(works) >= max_nodes:
                break
            held.add(i)
        for i in sorted(cand_work - works):
            if len(held) + len(works) >= max_nodes:
                break
            works.add(i)
        frontier = held & set(new_held)          # only newly-added held expand

    # Induced edges among the node set.
    edges: set[tuple[str, str]] = set()
    if held:
        ph = ",".join("?" * len(held))
        hp = list(held)
        for s, d in db.execute_sql(
                f"SELECT DISTINCT citing_paper_id, resolved_paper_id FROM reference "
                f"WHERE resolved_paper_id IS NOT NULL AND resolved_paper_id <> citing_paper_id "
                f"AND citing_paper_id IN ({ph}) AND resolved_paper_id IN ({ph})",
                hp + hp).fetchall():
            edges.add((_pk(s), _pk(d)))
        if works:
            wph = ",".join("?" * len(works))
            for s, w in db.execute_sql(
                    f"SELECT DISTINCT citing_paper_id, resolved_work_id FROM reference "
                    f"WHERE resolved_work_id IS NOT NULL AND citing_paper_id IN ({ph}) "
                    f"AND resolved_work_id IN ({wph})",
                    hp + list(works)).fetchall():
                edges.add((_pk(s), _wk(w)))

    # Which held papers actually hold a PDF file.
    pdf_pids: set[int] = set()
    if held:
        ph = ",".join("?" * len(held))
        for (pid,) in db.execute_sql(
                f"SELECT DISTINCT paper_id FROM paperfile "
                f"WHERE paper_id IN ({ph}) AND lower(path) LIKE '%.pdf'",
                list(held)).fetchall():
            pdf_pids.add(pid)

    nodes: dict[str, EgoNode] = {}
    for pid in held:
        p = Paper.get_or_none(Paper.id == pid)
        title = (p.title if p else '') or '(untitled)'
        year = p.year if p else None
        first = (Author.select(Author.name)
                 .where(Author.paper == pid).order_by(Author.order).first())
        who = _cite_name(first.name) if first else '?'
        label = f"{who} {year}".strip() if year else who
        kind = 'held_pdf' if pid in pdf_pids else 'held'
        nodes[_pk(pid)] = EgoNode(key=_pk(pid), paper_id=pid, label=label,
                                  title=title, kind=kind)
    for wid in works:
        w = CitedWork.get_or_none(CitedWork.id == wid)
        title = (w.title if w else '') or '(untitled work)'
        year = w.year if w else None
        who = (w.first_surname if (w and w.first_surname) else '?')
        label = f"{who} {year}".strip() if year else who
        nodes[_wk(wid)] = EgoNode(key=_wk(wid), paper_id=None, label=label,
                                  title=title, kind='external')
    return _pk(paper_id), nodes, list(edges)


@dataclass
class FigureRow:
    """One assembled figure, for the Text tab's figure list (P16)."""
    id: int
    page: int           # 0-based
    name: str
    assembly: str       # single | plate_page_union | caption_group_union
    pieces: int         # picture blocks merged into it
    caption: str        # linked caption (P16 ②), '' until then
    caption_hint: str   # caption block found under it by assembly
    plate_inferred: bool = False   # plate number not printed on its page
    entries: int = 0               # caption entries the linking stage found (P16 ②)
    panels: int = 0                # panels the split stage drew (P16 ③)
    unmatched: int = 0             # entries no panel claims — the reviewer's first stop
    panel_state: str = ''          # '' not run | 'split' | 'single' (not compound) | 'failed'
    bbox_page_1000: list[int] = field(default_factory=list)   # the figure's box on its page (Figures tab)


@dataclass
class PanelInfo:
    """One panel of a split figure, for the tiles under the figure list (P16 ③)."""
    label: str
    bbox_page_1000: list[int]      # already in the page's frame — what the PDF is cropped by
    entries: list[tuple[str, str, str]]   # (label, description, specimen number) it was matched to
    confidence: str = 'high'
    annotation: bool = False       # a scale bar or key, not a specimen
    colour: str = '#7b93ad'        # the box's colour in the reader (panel_colour of its index)


@dataclass
class PanelSet:
    figure_id: int
    name: str
    page: int                      # 0-based
    bbox_page_1000: list[int]
    panels: list[PanelInfo]
    unmatched: list[str]           # entry labels no panel claims


#: One quiet colour for every panel box — the plate is what the eye should
#: be on; the box only says where a panel is. A hovered or chosen panel is
#: lit separately (HIGHLIGHT). Kept as a cycle so a per-panel colour can come
#: back with one line.
PANEL_COLOURS = ('#7b93ad',)


def panel_colour(index: int) -> str:
    return PANEL_COLOURS[index % len(PANEL_COLOURS)]


def load_figure_unions(paper_id: int) -> dict[int, list]:
    """The paper's assembled figures that span several OCR picture blocks,
    by 0-based page, as `ocr_layout.Union`s — so the reader shows a plate
    the OCR cut into photographs as one plate."""
    import json

    from papermeister.figure_store import figures_for_paper
    out: dict[int, list] = {}
    for f in figures_for_paper(paper_id):
        blocks = json.loads(f.blocks_json or '[]')
        if len(blocks) < 2:
            continue
        out.setdefault(f.page, []).append((tuple(json.loads(f.bbox_page_1000)),
                                          frozenset(tuple(b) for b in blocks)))
    return out


def load_entries(figure_id: int) -> tuple[str, list[tuple[str, str, str]]]:
    """A figure's caption entries as (label, description, specimen number),
    for the list under the figure list when the figure has no panels yet."""
    from papermeister.models import Figure, FigureEntry
    row = Figure.get_or_none(Figure.id == figure_id)
    if row is None:
        return '', []
    return row.name, [(e.label, e.description, e.specimen_number)
                      for e in FigureEntry.select().where(FigureEntry.figure == row.id).order_by(FigureEntry.order)]


def load_panels(figure_id: int) -> PanelSet | None:
    import json

    from papermeister.figure_panels import to_page_frame
    from papermeister.models import Figure, FigureEntry, FigurePanel
    row = Figure.get_or_none(Figure.id == figure_id)
    if row is None:
        return None
    box = json.loads(row.bbox_page_1000)
    entries = {e.order: e for e in FigureEntry.select().where(FigureEntry.figure == row.id)}
    claimed: set[int] = set()
    panels = []
    for i, p in enumerate(FigurePanel.select().where(FigurePanel.figure == row.id).order_by(FigurePanel.order)):
        orders = json.loads(p.entry_orders_json or '[]')
        claimed.update(orders)
        panels.append(PanelInfo(
            label=p.label, bbox_page_1000=to_page_frame(box, json.loads(p.bbox_figure_1000)),
            entries=[(entries[o].label, entries[o].description, entries[o].specimen_number)
                     for o in orders if o in entries],
            confidence=p.confidence, annotation=p.annotation, colour=panel_colour(i)))
    if not panels:
        return None
    unmatched = [e.label for o, e in sorted(entries.items()) if o not in claimed]
    return PanelSet(figure_id=row.id, name=row.name, page=row.page, bbox_page_1000=box,
                    panels=panels, unmatched=unmatched)


#: Per file, the `exported_at` of the cache JSON's figures last landed this
#: session — so a tab opened again and again does not re-read a JSON that
#: has not changed, and one another machine changed is read once.
_shared_figures_seen: dict[int, str] = {}


def _import_shared_figures(paper_id: int) -> None:
    """Land what the paper's cache JSON says about its figures, when the
    JSON changed since it was last landed here (figure_share): rows this
    library does not have, and stages another machine ran since."""
    try:
        from papermeister.figure_share import import_from_cache_if_new
        from papermeister.models import PaperFile
        for pf in PaperFile.select().where((PaperFile.paper == paper_id) & (PaperFile.hash != '')
                                           & ~PaperFile.path.endswith('.json')):
            import_from_cache_if_new(pf, _shared_figures_seen)
    except Exception:
        import logging
        logging.getLogger(__name__).debug('shared figures not imported for paper %s', paper_id, exc_info=True)


def load_figures(paper_id: int) -> list[FigureRow]:
    import json

    from papermeister.figure_store import figures_for_paper
    from papermeister.models import Figure, FigureEntry, FigurePanel
    _import_shared_figures(paper_id)
    figures = figures_for_paper(paper_id)
    # Two queries for the whole paper, not two per figure: a plate paper has
    # a hundred rows and the Text tab builds this on every paper switch.
    entry_orders: dict[int, set[int]] = {}
    for e in (FigureEntry.select(FigureEntry.figure, FigureEntry.order).join(Figure)
              .where(Figure.paper == paper_id)):
        entry_orders.setdefault(e.figure_id, set()).add(e.order)
    panel_counts: dict[int, int] = {}
    claimed: dict[int, set[int]] = {}
    for p in (FigurePanel.select(FigurePanel.figure, FigurePanel.entry_orders_json).join(Figure)
              .where(Figure.paper == paper_id)):
        panel_counts[p.figure_id] = panel_counts.get(p.figure_id, 0) + 1
        claimed.setdefault(p.figure_id, set()).update(json.loads(p.entry_orders_json or '[]'))
    rows = []
    for f in figures:
        orders = entry_orders.get(f.id, set())
        panels = panel_counts.get(f.id, 0)
        if panels:
            state = 'split'
        elif f.panel_key and not f.is_compound:
            state = 'single'
        elif f.panel_attempts:
            state = 'failed'
        else:
            state = ''
        rows.append(FigureRow(
            id=f.id, page=f.page, name=f.name, assembly=f.assembly,
            pieces=len(json.loads(f.blocks_json or '[]')),
            caption=f.caption, caption_hint=f.caption_hint, plate_inferred=f.plate_inferred,
            entries=len(orders), panels=panels, unmatched=len(orders - claimed.get(f.id, set())),
            panel_state=state, bbox_page_1000=json.loads(f.bbox_page_1000)))
    return rows
