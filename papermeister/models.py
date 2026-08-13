import datetime
from typing import TYPE_CHECKING

import peewee

db = peewee.DatabaseProxy()


class BaseModel(peewee.Model):
    # peewee creates an implicit `id` primary key and, for every ForeignKeyField
    # `x`, an `x_id` attribute holding the raw key without triggering a fetch.
    # Neither is in peewee 4's type annotations, so mypy rejects code that works
    # — and reaching for `x` instead of `x_id` to satisfy it would silently add
    # a query per row. Declaring them under TYPE_CHECKING documents what peewee
    # generates, with no runtime effect.
    if TYPE_CHECKING:
        id: peewee.AutoField

    class Meta:
        database = db


class Source(BaseModel):
    """A paper source — local directory or Zotero library."""
    name = peewee.TextField()
    source_type = peewee.TextField()  # 'directory', 'zotero'
    path = peewee.TextField(default='')  # root path for directory sources


class Folder(BaseModel):
    """A folder within a source — maps to filesystem dir or Zotero collection."""
    if TYPE_CHECKING:
        source_id: int

    source = peewee.ForeignKeyField(Source, backref='folders', on_delete='CASCADE')
    name = peewee.TextField()
    parent = peewee.ForeignKeyField(
        'self', null=True, backref='children', on_delete='CASCADE')
    path = peewee.TextField(default='')  # full path for directory folders
    zotero_key = peewee.TextField(default='')  # Zotero collection key


class Paper(BaseModel):
    if TYPE_CHECKING:
        folder_id: int

    title = peewee.TextField(default='')
    # date is the raw Zotero `data.date` string (e.g. '08/2017', '2022-12-16',
    # '1865'). Round-trip source of truth for writeback to Zotero.
    date = peewee.TextField(default='')
    # year is derived from `date` (int, indexed for fast filter/sort).
    # Prefer Zotero's `meta.parsedDate` when syncing; fall back to regex.
    year = peewee.IntegerField(null=True)
    journal = peewee.TextField(default='')
    doi = peewee.TextField(default='')
    folder = peewee.ForeignKeyField(Folder, null=True, backref='papers', on_delete='SET NULL')
    zotero_key = peewee.TextField(default='')  # Zotero parent item key
    created_at = peewee.DateTimeField(default=datetime.datetime.now)
    # Set when the corresponding Zotero item is in trash; cleared on restore.
    # Permanent deletion (empty-trash) is a separate concern, not handled yet.
    trashed_at = peewee.DateTimeField(null=True)
    # P11: True once references extraction has been attempted (whether or not a
    # references section was found). Lets batch re-runs skip papers that have no
    # bibliography instead of re-parsing them every time. Existence of Reference
    # rows distinguishes "has refs" from "checked, none found".
    references_checked = peewee.BooleanField(default=False)
    # How many times extraction came back PARTIAL or failed for this paper.
    # A partial result deliberately leaves `references_checked` False so a later
    # run can replace it, but `_refs_targets` orders by paper id descending, so
    # the same unparseable papers resurface at the head of every batch and are
    # retried forever (devlog 076). Counting the attempts lets a full-library
    # run skip the ones that have already proved hopeless while keeping them
    # reachable through an explicit retry. Reset to 0 whenever a paper does
    # come back complete, so a run of server trouble doesn't retire papers that
    # were only ever failing because the server was down.
    references_attempts = peewee.IntegerField(default=0)


class Author(BaseModel):
    if TYPE_CHECKING:
        paper_id: int

    paper = peewee.ForeignKeyField(Paper, backref='authors_list', on_delete='CASCADE')
    name = peewee.TextField()
    order = peewee.IntegerField(default=0)


class PaperFile(BaseModel):
    if TYPE_CHECKING:
        paper_id: int

    paper = peewee.ForeignKeyField(Paper, backref='files', on_delete='CASCADE')
    path = peewee.TextField()
    hash = peewee.TextField(default='')
    status = peewee.TextField(default='pending')  # pending, processed, failed
    failure_reason = peewee.TextField(default='')  # free-form, e.g. ocr_failed|download_failed|encrypted
    zotero_key = peewee.TextField(default='')  # Zotero attachment key
    # Set when the Zotero attachment is in trash; cleared on restore.
    # Independent of the parent Paper's trashed_at (a user can trash a single
    # attachment without trashing the parent item).
    trashed_at = peewee.DateTimeField(null=True)


class PaperBiblio(BaseModel):
    """LLM-extracted bibliographic info. Non-destructive: separate from Paper."""
    if TYPE_CHECKING:
        paper_id: int

    paper = peewee.ForeignKeyField(Paper, backref='biblio_extractions', on_delete='CASCADE')
    file_hash = peewee.TextField(default='')   # PDF hash this extraction came from
    title = peewee.TextField(default='')
    authors_json = peewee.TextField(default='[]')
    year = peewee.IntegerField(null=True)
    journal = peewee.TextField(default='')
    volume = peewee.TextField(default='')      # journal volume
    issue = peewee.TextField(default='')       # journal issue/number
    pages = peewee.TextField(default='')       # page range, e.g. "123-145"
    doi = peewee.TextField(default='')
    abstract = peewee.TextField(default='')
    doc_type = peewee.TextField(default='unknown')
    language = peewee.TextField(default='')
    confidence = peewee.TextField(default='')
    needs_visual_review = peewee.BooleanField(default=False)
    notes = peewee.TextField(default='')
    source = peewee.TextField(default='')      # 'llm-haiku', 'llm-sonnet', etc.
    model_version = peewee.TextField(default='')
    extracted_at = peewee.DateTimeField(default=datetime.datetime.now)
    # P08 reflection policy status: extracted | needs_review | auto_committed | applied | rejected
    status = peewee.TextField(default='extracted')
    review_reason = peewee.TextField(default='')  # missing_title|low_confidence|... (see P08)


class PaperFolder(BaseModel):
    """Many-to-many: a Paper can belong to multiple Folders (Zotero collections)."""
    if TYPE_CHECKING:
        paper_id: int
        folder_id: int

    paper = peewee.ForeignKeyField(Paper, backref='paper_folders', on_delete='CASCADE')
    folder = peewee.ForeignKeyField(Folder, backref='paper_folders', on_delete='CASCADE')

    class Meta:
        indexes = (
            (('paper', 'folder'), True),  # unique together
        )


class Passage(BaseModel):
    if TYPE_CHECKING:
        paper_id: int

    paper = peewee.ForeignKeyField(Paper, backref='passages', on_delete='CASCADE')
    page = peewee.IntegerField()
    text = peewee.TextField()


class CitedWork(BaseModel):
    """P11 Phase 2 — a canonical external work: cited by ≥1 of our papers but
    NOT held in the library. Normalized/derived layer over Reference rows
    (rebuildable from them), so several references to the same external paper
    collapse into one node for the citation network.

    Held papers are never CitedWorks: a reference to a paper we own sets
    `Reference.resolved_paper` instead. `resolved_paper` and `resolved_work` are
    mutually exclusive — held wins (authoritative).
    """
    doi = peewee.TextField(default='')            # normalized; indexed
    title = peewee.TextField(default='')          # representative title
    title_key = peewee.TextField(default='')      # normalized fingerprint; indexed
    year = peewee.IntegerField(null=True)
    authors_json = peewee.TextField(default='[]')
    container = peewee.TextField(default='')
    first_surname = peewee.TextField(default='')  # blocking key for LLM merge pass
    cite_count = peewee.IntegerField(default=0)   # distinct citing held papers (denormalized)
    # Set once this work has been through the pass-2 LLM merge adjudication
    # (whether or not it was merged) so re-runs skip already-judged clusters.
    merge_checked = peewee.BooleanField(default=False)
    # Promotion: set when a held paper matching this work is later acquired —
    # its citations are repointed to that Paper and this row becomes a tombstone
    # (excluded from the active-node set, kept for traceability).
    merged_into_paper = peewee.ForeignKeyField(
        Paper, null=True, backref='absorbed_works', on_delete='SET NULL')
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        indexes = (
            (('title_key',), False),
            (('doi',), False),
        )


class Reference(BaseModel):
    """A single bibliography entry parsed from a citing paper's references
    section (P11). Non-destructive derived layer — the OCR JSON remains the
    source of truth, so a Reference set can always be regenerated.

    held vs cited-only is NOT a separate flag: a reference resolved to a paper
    we own has `resolved_paper` set; an external (cited-only) reference resolves
    to a canonical `resolved_work` (CitedWork) instead. The two are mutually
    exclusive; both null means junk/unparseable.
    """
    if TYPE_CHECKING:
        citing_paper_id: int
        resolved_paper_id: int
        resolved_work_id: int

    citing_paper = peewee.ForeignKeyField(
        Paper, backref='references', on_delete='CASCADE')
    order_index = peewee.IntegerField(default=0)   # position / [n] in the bibliography
    raw_text = peewee.TextField()                   # original entry string — source of truth

    # parsed fields (LLM)
    authors_json = peewee.TextField(default='[]')   # [{"family","given"}, ...]
    year = peewee.IntegerField(null=True)
    title = peewee.TextField(default='')
    container = peewee.TextField(default='')        # journal / book title
    volume = peewee.TextField(default='')
    issue = peewee.TextField(default='')
    pages = peewee.TextField(default='')
    doi = peewee.TextField(default='')
    ref_type = peewee.TextField(default='unknown')  # article|book|chapter|thesis|report|unknown

    # resolution (filled by the resolve pass)
    resolved_paper = peewee.ForeignKeyField(
        Paper, null=True, backref='cited_by', on_delete='SET NULL')
    # external canonical node (Phase 2). Mutually exclusive with resolved_paper.
    resolved_work = peewee.ForeignKeyField(
        CitedWork, null=True, backref='citations', on_delete='SET NULL')
    # doi|title (→ held Paper) | work-doi|work-title|work-new (pass-1 → CitedWork)
    # | work-llm (pass-2 LLM merge) | none (junk)
    match_method = peewee.TextField(default='')
    match_score = peewee.FloatField(null=True)

    # provenance
    source = peewee.TextField(default='')           # 'llm-qwen'
    model_version = peewee.TextField(default='')    # 'qwen3-32b'
    parse_confidence = peewee.TextField(default='') # high|medium|low
    extracted_at = peewee.DateTimeField(default=datetime.datetime.now)
