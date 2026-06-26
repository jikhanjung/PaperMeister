import os
import peewee
from .models import (db, Source, Folder, Paper, Author, PaperFile, PaperFolder,
                     Passage, PaperBiblio, Reference, CitedWork)

DB_PATH = os.path.join(os.path.expanduser('~'), '.papermeister', 'papermeister.db')

ALL_TABLES = [Source, Folder, Paper, Author, PaperFile, PaperFolder, Passage,
              PaperBiblio, Reference, CitedWork]

# ---------------------------------------------------------------------------
# FTS5 (devlog P13). `passage_fts` is EXTERNAL-CONTENT (text-only) over the
# `passage` table — it stores only the inverted index, reading the original text
# back from `passage` by rowid, so the OCR fulltext is NOT duplicated (~1.75 GB
# saved). `paper_fts` is a small standalone index over paper title + authors so
# title/author-only terms (absent from the body) stay searchable. Both are kept
# in sync by triggers — never INSERT/DELETE the FTS tables by hand.
# ---------------------------------------------------------------------------
_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5("
    "text, content='passage', content_rowid='id', tokenize='unicode61')",
    "CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5("
    "title, authors, tokenize='unicode61')",
)
_FTS_TRIGGERS = (
    # passage -> passage_fts (external content: deletes must replay old values).
    "CREATE TRIGGER IF NOT EXISTS passage_fts_ai AFTER INSERT ON passage BEGIN "
    "INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text); END",
    "CREATE TRIGGER IF NOT EXISTS passage_fts_ad AFTER DELETE ON passage BEGIN "
    "INSERT INTO passage_fts(passage_fts, rowid, text) "
    "VALUES ('delete', old.id, old.text); END",
    "CREATE TRIGGER IF NOT EXISTS passage_fts_au AFTER UPDATE OF text ON passage BEGIN "
    "INSERT INTO passage_fts(passage_fts, rowid, text) "
    "VALUES ('delete', old.id, old.text); "
    "INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text); END",
    # paper/author -> paper_fts (standalone: ordinary DELETE/UPDATE allowed).
    "CREATE TRIGGER IF NOT EXISTS paper_fts_ai AFTER INSERT ON paper BEGIN "
    "INSERT INTO paper_fts(rowid, title, authors) VALUES (new.id, new.title, ''); END",
    "CREATE TRIGGER IF NOT EXISTS paper_fts_ad AFTER DELETE ON paper BEGIN "
    "DELETE FROM paper_fts WHERE rowid = old.id; END",
    "CREATE TRIGGER IF NOT EXISTS paper_fts_au AFTER UPDATE OF title ON paper BEGIN "
    "UPDATE paper_fts SET title = new.title WHERE rowid = new.id; END",
    "CREATE TRIGGER IF NOT EXISTS author_fts_ai AFTER INSERT ON author BEGIN "
    "UPDATE paper_fts SET authors = "
    "(SELECT group_concat(name, ', ') FROM author WHERE paper_id = new.paper_id) "
    "WHERE rowid = new.paper_id; END",
    "CREATE TRIGGER IF NOT EXISTS author_fts_ad AFTER DELETE ON author BEGIN "
    "UPDATE paper_fts SET authors = "
    "COALESCE((SELECT group_concat(name, ', ') FROM author WHERE paper_id = old.paper_id), '') "
    "WHERE rowid = old.paper_id; END",
    "CREATE TRIGGER IF NOT EXISTS author_fts_au AFTER UPDATE OF name ON author BEGIN "
    "UPDATE paper_fts SET authors = "
    "(SELECT group_concat(name, ', ') FROM author WHERE paper_id = new.paper_id) "
    "WHERE rowid = new.paper_id; END",
)
# One-time (re)population from the base tables; triggers only fire on subsequent
# changes. Used by init_db (fresh DB) and the P13 migration script.
_FTS_POPULATE = (
    "INSERT INTO passage_fts(passage_fts) VALUES('rebuild')",
    "INSERT INTO paper_fts(rowid, title, authors) "
    "SELECT p.id, COALESCE(p.title, ''), "
    "COALESCE((SELECT group_concat(a.name, ', ') FROM author a "
    "WHERE a.paper_id = p.id), '') FROM paper p",
)


def create_fts(database):
    """Create the FTS tables + sync triggers (idempotent, IF NOT EXISTS)."""
    for stmt in _FTS_SCHEMA + _FTS_TRIGGERS:
        database.execute_sql(stmt)


def _require_external_fts(database):
    """Halt if `passage_fts` is the pre-P13 standalone schema.

    The new search/sync code assumes external-content FTS; running it against the
    old self-contained table would silently misbehave. A one-time migration
    converts it — see scripts/migrate_fts_external_content.py.
    """
    row = database.execute_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='passage_fts'"
    ).fetchone()
    if row and row[0] and "content='passage'" not in row[0]:
        raise RuntimeError(
            'passage_fts is the pre-P13 (standalone) schema. Run '
            '`python scripts/migrate_fts_external_content.py --execute` once to '
            'upgrade to external-content FTS (devlog P13).')


def _migrate(database):
    """Add missing columns to existing tables."""
    cursor = database.execute_sql("PRAGMA table_info('paper')").fetchall()
    columns = {row[1] for row in cursor}
    if 'folder_id' not in columns:
        database.execute_sql('ALTER TABLE paper ADD COLUMN folder_id INTEGER REFERENCES folder(id)')

    # Zotero integration columns
    cursor = database.execute_sql("PRAGMA table_info('folder')").fetchall()
    columns = {row[1] for row in cursor}
    if 'zotero_key' not in columns:
        database.execute_sql("ALTER TABLE folder ADD COLUMN zotero_key TEXT DEFAULT ''")

    cursor = database.execute_sql("PRAGMA table_info('paper')").fetchall()
    columns = {row[1] for row in cursor}
    if 'zotero_key' not in columns:
        database.execute_sql("ALTER TABLE paper ADD COLUMN zotero_key TEXT DEFAULT ''")
    # Raw Zotero `data.date` string (round-trip source of truth for writeback).
    # Paper.year remains as the derived int index.
    if 'date' not in columns:
        database.execute_sql("ALTER TABLE paper ADD COLUMN date TEXT DEFAULT ''")
    # P11: references-extraction marker. Backfill papers that already have
    # Reference rows so they aren't needlessly re-parsed on the first run.
    if 'references_checked' not in columns:
        database.execute_sql("ALTER TABLE paper ADD COLUMN references_checked INTEGER DEFAULT 0")
        database.execute_sql(
            "UPDATE paper SET references_checked = 1 WHERE id IN "
            "(SELECT DISTINCT citing_paper_id FROM reference)"
        )

    cursor = database.execute_sql("PRAGMA table_info('paperfile')").fetchall()
    columns = {row[1] for row in cursor}
    if 'zotero_key' not in columns:
        database.execute_sql("ALTER TABLE paperfile ADD COLUMN zotero_key TEXT DEFAULT ''")

    # PaperBiblio: needs_visual_review column
    cursor = database.execute_sql("PRAGMA table_info('paperbiblio')").fetchall()
    bib_columns = {row[1] for row in cursor}
    if bib_columns and 'needs_visual_review' not in bib_columns:
        database.execute_sql("ALTER TABLE paperbiblio ADD COLUMN needs_visual_review INTEGER DEFAULT 0")

    # P08 reflection policy: PaperBiblio.status + review_reason
    if bib_columns and 'status' not in bib_columns:
        database.execute_sql("ALTER TABLE paperbiblio ADD COLUMN status TEXT DEFAULT 'extracted'")
    if bib_columns and 'review_reason' not in bib_columns:
        database.execute_sql("ALTER TABLE paperbiblio ADD COLUMN review_reason TEXT DEFAULT ''")

    # Journal-article detail fields: volume / issue / pages
    for col in ('volume', 'issue', 'pages'):
        if bib_columns and col not in bib_columns:
            database.execute_sql(f"ALTER TABLE paperbiblio ADD COLUMN {col} TEXT DEFAULT ''")

    # PaperFile.failure_reason
    cursor = database.execute_sql("PRAGMA table_info('paperfile')").fetchall()
    pf_columns = {row[1] for row in cursor}
    if 'failure_reason' not in pf_columns:
        database.execute_sql("ALTER TABLE paperfile ADD COLUMN failure_reason TEXT DEFAULT ''")

    # P11 Phase 2: Reference.resolved_work → canonical external CitedWork.
    # The citedwork table is created by create_tables() before _migrate runs.
    cursor = database.execute_sql("PRAGMA table_info('reference')").fetchall()
    ref_columns = {row[1] for row in cursor}
    if ref_columns and 'resolved_work_id' not in ref_columns:
        database.execute_sql(
            "ALTER TABLE reference ADD COLUMN resolved_work_id INTEGER "
            "REFERENCES citedwork(id)")
        database.execute_sql(
            "CREATE INDEX IF NOT EXISTS reference_resolved_work_id "
            "ON reference (resolved_work_id)")

    # trashed_at on Paper and PaperFile (Zotero trash flag, NULL = not trashed)
    cursor = database.execute_sql("PRAGMA table_info('paper')").fetchall()
    columns = {row[1] for row in cursor}
    if 'trashed_at' not in columns:
        database.execute_sql('ALTER TABLE paper ADD COLUMN trashed_at DATETIME')
    cursor = database.execute_sql("PRAGMA table_info('paperfile')").fetchall()
    pf_columns = {row[1] for row in cursor}
    if 'trashed_at' not in pf_columns:
        database.execute_sql('ALTER TABLE paperfile ADD COLUMN trashed_at DATETIME')

    # PaperFolder backfill: seed from Paper.folder for existing data.
    # After backfill, flag for full item sync to populate multi-collection membership.
    tables = [t[0] for t in database.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if 'paperfolder' in tables:
        existing = database.execute_sql('SELECT COUNT(*) FROM paperfolder').fetchone()[0]
        if existing == 0:
            count = database.execute_sql(
                'INSERT OR IGNORE INTO paperfolder (paper_id, folder_id) '
                'SELECT id, folder_id FROM paper WHERE folder_id IS NOT NULL'
            ).rowcount
            if count > 0:
                from .preferences import set_pref
                set_pref('paperfolder_needs_full_sync', True)

    # One-time fix: Zotero author names were stored as "Last First" (no comma).
    # Convert to "Last, First" so split_author_name() can parse unambiguously.
    # Only touches Zotero-sourced papers (zotero_key != '').
    from .preferences import get_pref, set_pref
    if not get_pref('author_comma_migrated', False):
        rows = database.execute_sql(
            "SELECT a.id, a.name FROM author a "
            "JOIN paper p ON a.paper_id = p.id "
            "WHERE p.zotero_key != '' AND a.name NOT LIKE '%,%'"
        ).fetchall()
        for author_id, name in rows:
            parts = name.split(' ', 1)
            if len(parts) == 2 and parts[1]:
                new_name = f'{parts[0]}, {parts[1]}'
                database.execute_sql(
                    'UPDATE author SET name = ? WHERE id = ?',
                    (new_name, author_id),
                )
        set_pref('author_comma_migrated', True)

    # Drop unique index on paperfile.hash (Zotero files start with empty hash)
    indexes = database.execute_sql("PRAGMA index_list('paperfile')").fetchall()
    for idx in indexes:
        idx_name = idx[1]
        idx_unique = idx[2]
        if idx_unique:
            cols = database.execute_sql(f"PRAGMA index_info('{idx_name}')").fetchall()
            col_names = [c[2] for c in cols]
            if col_names == ['hash']:
                database.execute_sql(f'DROP INDEX "{idx_name}"')


def init_db(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    real_db = peewee.SqliteDatabase(path, pragmas={
        'journal_mode': 'wal',
        'foreign_keys': 1,
    })
    db.initialize(real_db)
    db.create_tables(ALL_TABLES)
    _migrate(db)
    _require_external_fts(db)   # block app on a pre-P13 DB until it's migrated
    create_fts(db)             # external-content passage_fts + paper_fts (fresh DB)
    return db
