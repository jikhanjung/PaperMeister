#!/usr/bin/env python3
"""Write a consistent, gzipped snapshot of a live SQLite DB.

Uses the SQLite online-backup API — safe to run WHILE the app is writing (WAL
allows concurrent readers, and the backup restarts any pages changed mid-copy),
so it never produces the torn/stale image a raw file copy of a live WAL DB can.
The consistent snapshot is then gzipped. Intended for scheduled off-machine
backups; driven by scripts/backup-papermeister.ps1.

    python scripts/_db_snapshot.py <source.db> <output.db.gz>

Restore: gunzip -c output.db.gz > papermeister.db
"""

import gzip
import os
import shutil
import sqlite3
import sys
import tempfile


def main():
    if len(sys.argv) != 3:
        print('usage: _db_snapshot.py <source.db> <output.db.gz>')
        sys.exit(2)
    src, out_gz = sys.argv[1], sys.argv[2]

    # sqlite3.connect() CREATES a missing database, so a wrong source path would
    # otherwise snapshot an empty one and report success — the failure mode that
    # matters here, since nobody reads a scheduled task's output.
    if not os.path.exists(src):
        print(f'source database does not exist: {src}', file=sys.stderr)
        sys.exit(1)

    fd, tmp = tempfile.mkstemp(suffix='.db', dir=os.path.dirname(out_gz) or None)
    os.close(fd)
    try:
        s = sqlite3.connect(src)
        d = sqlite3.connect(tmp)
        s.backup(d)                  # consistent hot backup of the live DB
        d.close()
        s.close()
        with open(tmp, 'rb') as f_in, \
                gzip.open(out_gz, 'wb', compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out, length=8 << 20)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == '__main__':
    main()
