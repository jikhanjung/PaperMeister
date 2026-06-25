import datetime
import peewee

db = peewee.DatabaseProxy()


class BaseModel(peewee.Model):
    class Meta:
        database = db


class Source(BaseModel):
    """A paper source — local directory or Zotero library."""
    name = peewee.TextField()
    source_type = peewee.TextField()  # 'directory', 'zotero'
    path = peewee.TextField(default='')  # root path for directory sources


class Folder(BaseModel):
    """A folder within a source — maps to filesystem dir or Zotero collection."""
    source = peewee.ForeignKeyField(Source, backref='folders', on_delete='CASCADE')
    name = peewee.TextField()
    parent = peewee.ForeignKeyField('self', null=True, backref='children', on_delete='CASCADE')
    path = peewee.TextField(default='')  # full path for directory folders
    zotero_key = peewee.TextField(default='')  # Zotero collection key


class Paper(BaseModel):
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


class Author(BaseModel):
    paper = peewee.ForeignKeyField(Paper, backref='authors_list', on_delete='CASCADE')
    name = peewee.TextField()
    order = peewee.IntegerField(default=0)


class PaperFile(BaseModel):
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
    paper = peewee.ForeignKeyField(Paper, backref='paper_folders', on_delete='CASCADE')
    folder = peewee.ForeignKeyField(Folder, backref='paper_folders', on_delete='CASCADE')

    class Meta:
        indexes = (
            (('paper', 'folder'), True),  # unique together
        )


class Passage(BaseModel):
    paper = peewee.ForeignKeyField(Paper, backref='passages', on_delete='CASCADE')
    page = peewee.IntegerField()
    text = peewee.TextField()


class Reference(BaseModel):
    """A single bibliography entry parsed from a citing paper's references
    section (P11). Non-destructive derived layer — the OCR JSON remains the
    source of truth, so a Reference set can always be regenerated.

    held vs cited-only is NOT a separate flag: a reference resolved to a paper
    we own has `resolved_paper` set; an external (cited-only) reference leaves
    it null.
    """
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
    match_method = peewee.TextField(default='')     # doi|title|none
    match_score = peewee.FloatField(null=True)

    # provenance
    source = peewee.TextField(default='')           # 'llm-qwen'
    model_version = peewee.TextField(default='')    # 'qwen3-32b'
    parse_confidence = peewee.TextField(default='') # high|medium|low
    extracted_at = peewee.DateTimeField(default=datetime.datetime.now)
