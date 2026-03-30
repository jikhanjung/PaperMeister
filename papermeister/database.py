import os
import peewee
from .models import db, Source, Folder, Paper, Author, PaperFile, Passage

DB_PATH = os.path.join(os.path.expanduser('~'), '.papermeister', 'papermeister.db')

ALL_TABLES = [Source, Folder, Paper, Author, PaperFile, Passage]


def _migrate(database):
    """Add missing columns to existing tables."""
    cursor = database.execute_sql("PRAGMA table_info('paper')").fetchall()
    columns = {row[1] for row in cursor}
    if 'folder_id' not in columns:
        database.execute_sql('ALTER TABLE paper ADD COLUMN folder_id INTEGER REFERENCES folder(id)')


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
