"""Where user data lives — the single source of truth for every path.

Layout follows the PaleoBytes convention shared with Modan2 and CTHarvester::

    ~/PaleoBytes/PaperMeister/
    ├── papermeister.db
    ├── preferences.json
    ├── zotero_collections.json
    ├── ocr_json/          cached OCR output, one file per PDF
    ├── pdf_cache/         PDFs fetched from Zotero
    ├── logs/
    └── tmp/

Until this module existed the same ``os.path.join(expanduser('~'),
'.papermeister', ...)`` was spelled out in 23 files, which is why moving it was a
chore rather than a constant.

Data used to live in ``~/.papermeister``. There is no fallback to it: the only
installation that had one has been migrated, so resolution stays a plain
constant rather than something conditional that every doc has to explain. A
stray legacy directory is only reported, in `warn_if_legacy_dir` — silently
building a fresh library beside real data is the one outcome worth ruling out.
"""
import logging
import os

COMPANY_NAME = 'PaleoBytes'
PROGRAM_NAME = 'PaperMeister'

#: Where new installations put everything.
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser('~'), COMPANY_NAME, PROGRAM_NAME)
#: Pre-0.1.4 location. Not used — only reported by `warn_if_legacy_dir`.
LEGACY_DATA_DIR = os.path.join(os.path.expanduser('~'), '.papermeister')

#: `PAPERMEISTER_DATA_DIR` overrides it — handy for tests, and for pointing a
#: second machine at a copied library without moving anything.
DATA_DIR = os.path.expanduser(
    os.environ.get('PAPERMEISTER_DATA_DIR') or DEFAULT_DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, 'papermeister.db')
PREFS_PATH = os.path.join(DATA_DIR, 'preferences.json')
ZOTERO_COLLECTIONS_PATH = os.path.join(DATA_DIR, 'zotero_collections.json')

OCR_JSON_DIR = os.path.join(DATA_DIR, 'ocr_json')
PDF_CACHE_DIR = os.path.join(DATA_DIR, 'pdf_cache')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
TMP_DIR = os.path.join(DATA_DIR, 'tmp')


def warn_if_legacy_dir() -> bool:
    """Log if pre-0.1.4 data is sitting unused. True when it is.

    Nothing reads that directory any more, so a machine that still has one gets
    a brand-new empty library instead — which looks exactly like data loss. Say
    so rather than letting it be discovered later.
    """
    if not os.path.isdir(LEGACY_DATA_DIR) or os.path.isdir(DEFAULT_DATA_DIR):
        return False
    logging.getLogger('papermeister').warning(
        'Found data in %s, which is no longer used. This session will start an '
        'empty library in %s. To keep the old one, close the app and run: '
        'python scripts/migrate_data_dir.py --execute',
        LEGACY_DATA_DIR, DATA_DIR)
    return True


def ensure_directories() -> None:
    """Create the data directories. Safe to call repeatedly."""
    for d in (DATA_DIR, OCR_JSON_DIR, PDF_CACHE_DIR, LOG_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)
