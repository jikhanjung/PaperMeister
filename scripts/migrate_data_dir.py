#!/usr/bin/env python3
"""Move the data directory from ~/.papermeister to ~/PaleoBytes/PaperMeister.

The app does not do this on its own. A live library here is gigabytes, a batch
may be running against the database, and relocating someone's data is not a
decision a startup path should make. Until this is run the app keeps using the
legacy directory exactly as before (see `papermeister/paths.py`).

Convention: dry-run by default; pass --execute to actually move anything.

Run it with the app CLOSED. On Windows that also means no batch in progress —
moving an open SQLite file is how you get a corrupt one.
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.paths import DEFAULT_DATA_DIR, LEGACY_DATA_DIR


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _human(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f}{unit}' if unit != 'B' else f'{n}B'
        n /= 1024
    return f'{n:.1f}GB'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--execute', action='store_true',
                    help='Actually move the data (default: dry-run preview)')
    ap.add_argument('--copy', action='store_true',
                    help='Copy instead of move, leaving the legacy directory in '
                         'place. Safer, but needs twice the disk space.')
    args = ap.parse_args()

    if not os.path.isdir(LEGACY_DATA_DIR):
        print(f'Nothing to migrate: {LEGACY_DATA_DIR} does not exist.')
        return 0

    if os.path.isdir(DEFAULT_DATA_DIR) and os.listdir(DEFAULT_DATA_DIR):
        print(f'ERROR: {DEFAULT_DATA_DIR} already exists and is not empty.')
        print('       Merging two libraries is not something this script will')
        print('       guess at — move or remove it first, then re-run.')
        return 1

    entries = sorted(os.listdir(LEGACY_DATA_DIR))
    print(f'From: {LEGACY_DATA_DIR}')
    print(f'To:   {DEFAULT_DATA_DIR}')
    print()
    total = 0
    for name in entries:
        path = os.path.join(LEGACY_DATA_DIR, name)
        size = _size(path)
        total += size
        kind = 'dir ' if os.path.isdir(path) else 'file'
        print(f'  {kind}  {name:<40} {_human(size):>10}')
    print(f'\n  {"total":<47}{_human(total):>10}')

    if not args.execute:
        print('\nDRY-RUN (no --execute). Nothing was moved.')
        print('Close the app first, then re-run with --execute.')
        return 0

    os.makedirs(os.path.dirname(DEFAULT_DATA_DIR), exist_ok=True)
    if args.copy:
        print('\nCopying...')
        shutil.copytree(LEGACY_DATA_DIR, DEFAULT_DATA_DIR, dirs_exist_ok=True)
        print(f'Copied. The legacy directory is still at {LEGACY_DATA_DIR};')
        print('remove it once the app has started cleanly from the new location.')
    else:
        print('\nMoving...')
        shutil.move(LEGACY_DATA_DIR, DEFAULT_DATA_DIR)
        print('Moved.')

    print(f'\nThe app will now use {DEFAULT_DATA_DIR}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
