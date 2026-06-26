#!/usr/bin/env python3
"""P13 — migrate passage_fts to external-content (text-only) + add paper_fts.

The pre-P13 `passage_fts` was a standalone FTS5 that stored its OWN copy of every
passage's text (~1.75 GB duplicate of `passage.text`). This converts it to an
EXTERNAL-CONTENT index over `passage` (index only; text read back by rowid) and
adds a small standalone `paper_fts(title, authors)` so title/author-only terms
stay searchable. Both indexes are rebuilt from the base tables; sync afterwards
is by trigger (see papermeister/database.py). A final VACUUM shrinks the file.

Run on Windows (live DB) AFTER any extraction batch has STOPPED — never with the
desktop app or another writer open. Uses raw sqlite3 (bypasses init_db's
external-content guard). Convention: dry-run by default; pass --execute to write.

  python scripts/migrate_fts_external_content.py            # preview
  python scripts/migrate_fts_external_content.py --execute  # do it
"""

import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import (
    DB_PATH, _FTS_SCHEMA, _FTS_TRIGGERS, _FTS_POPULATE)


def _table_sql(conn, name):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB_PATH, help='DB path (default: live DB)')
    ap.add_argument('--no-vacuum', action='store_true',
                    help='Skip the final VACUUM (space freed internally but the '
                    'file stays large)')
    ap.add_argument('--no-backup', action='store_true',
                    help='Skip the automatic pre-migration backup (NOT advised — '
                    'only if you already made your own copy)')
    ap.add_argument('--execute', action='store_true',
                    help='Write to the DB (default: dry-run preview)')
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f'DB not found: {args.db}')
        return
    size0 = os.path.getsize(args.db)
    print(f'DB: {args.db}\nsize: {size0 / 1e9:.2f} GB')

    conn = sqlite3.connect(args.db)
    conn.isolation_level = None        # explicit BEGIN/COMMIT; no implicit DDL commit
    conn.execute('PRAGMA foreign_keys=ON')

    cur_sql = _table_sql(conn, 'passage_fts')
    if cur_sql is None:
        print('No passage_fts table — nothing to migrate.')
        return
    if "content='passage'" in cur_sql:
        print('passage_fts is ALREADY external-content. Nothing to do.')
        return

    print('Checking integrity (full read scan, ~1 min)…')
    ic = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(f'integrity_check: {ic}')
    if ic != 'ok':
        print('ABORT: DB is not clean. Repair first (e.g. REINDEX) before migrating.')
        return

    npass = conn.execute('SELECT COUNT(*) FROM passage').fetchone()[0]
    npaper = conn.execute('SELECT COUNT(*) FROM paper').fetchone()[0]
    print(f'passages: {npass:,} | papers: {npaper:,}')

    backup = args.db + '.pre-p13-backup'
    if not args.execute:
        print('\nDRY-RUN (no --execute). Would:')
        if not args.no_backup:
            print(f'  0. BACK UP -> {backup} (consistent copy via VACUUM INTO)')
        print('  1. DROP standalone passage_fts (+ paper_fts if present)')
        print('  2. CREATE external-content passage_fts + standalone paper_fts + triggers')
        print(f'  3. rebuild passage_fts ({npass:,} passages), populate paper_fts ({npaper:,} papers)')
        print('  4. VACUUM (shrink file)' if not args.no_vacuum else '  4. (skip VACUUM)')
        print('\nExpected: file ~40% smaller. Re-run with --execute to apply.')
        return

    # Safety backup FIRST — a consistent, compact copy of the live DB. VACUUM
    # INTO refuses to overwrite, so an existing backup blocks (intentional).
    if not args.no_backup:
        if os.path.exists(backup):
            print(f'ABORT: backup already exists: {backup}\n'
                  '       Rename/remove it first (refusing to overwrite).')
            return
        print(f'Backing up -> {backup} (VACUUM INTO, ~1-2 min)…')
        conn.execute("VACUUM INTO '%s'" % backup.replace("'", "''"))
        print(f'  backup OK: {os.path.getsize(backup) / 1e9:.2f} GB')

    print('\nMigrating…')
    t0 = time.time()
    conn.execute('BEGIN')
    conn.execute('DROP TABLE IF EXISTS passage_fts')
    conn.execute('DROP TABLE IF EXISTS paper_fts')
    for stmt in _FTS_SCHEMA + _FTS_TRIGGERS:
        conn.execute(stmt)
    for stmt in _FTS_POPULATE:
        print(f'  running: {stmt[:54]}…')
        conn.execute(stmt)
    conn.execute('COMMIT')
    print(f'  rebuild + populate: {time.time() - t0:.0f}s')

    ic = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(f'integrity_check (post): {ic}')
    pf = conn.execute('SELECT COUNT(*) FROM paper_fts').fetchone()[0]
    print(f'paper_fts rows: {pf:,}')

    if not args.no_vacuum:
        print('VACUUM (shrinks file; needs ~2x temp space)…')
        conn.execute('VACUUM')
    conn.close()

    size1 = os.path.getsize(args.db)
    print(f'\nDONE. size: {size0 / 1e9:.2f} GB -> {size1 / 1e9:.2f} GB '
          f'({100 * (size0 - size1) / size0:.0f}% smaller)')
    print('Sanity: open the app and search — confirm body hits AND a title/'
          'author-only term still returns its paper.')


if __name__ == '__main__':
    main()
