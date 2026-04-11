import os
import peewee
from .models import db, Source, Folder, Paper, Author, PaperFile, Passage, PaperBiblio

DB_PATH = os.path.join(os.path.expanduser('~'), '.papermeister', 'papermeister.db')

ALL_TABLES = [Source, Folder, Paper, Author, PaperFile, Passage, PaperBiblio]


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

    # PaperFile.failure_reason
    cursor = database.execute_sql("PRAGMA table_info('paperfile')").fetchall()
    pf_columns = {row[1] for row in cursor}
    if 'failure_reason' not in pf_columns:
        database.execute_sql("ALTER TABLE paperfile ADD COLUMN failure_reason TEXT DEFAULT ''")

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
    db.execute_sql('''
        CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
            title, authors, text,
            paper_id UNINDEXED, page UNINDEXED, passage_id UNINDEXED,
            tokenize='unicode61'
        )
    ''')
    return db
