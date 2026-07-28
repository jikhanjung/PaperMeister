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

**Existing installations keep working untouched.** If the legacy
``~/.papermeister`` directory exists and the new one does not, that is used
instead — the data is not moved. A live library here is gigabytes and a batch may
be running against it, so relocating it at startup is not something the app
should decide on its own. ``scripts/migrate_data_dir.py`` does the move when the
user asks for it, and once the new directory exists it takes over.

Until this module existed the same ``os.path.join(expanduser('~'),
'.papermeister', ...)`` was spelled out in 23 files, which is why moving it was a
chore rather than a constant.
"""
import os

COMPANY_NAME = 'PaleoBytes'
PROGRAM_NAME = 'PaperMeister'

#: Where new installations put everything.
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser('~'), COMPANY_NAME, PROGRAM_NAME)
#: Pre-0.1.4 location, still honoured when it is the one that exists.
LEGACY_DATA_DIR = os.path.join(os.path.expanduser('~'), '.papermeister')


def _resolve_data_dir() -> str:
    """Pick the directory to use, preferring the new one.

    `PAPERMEISTER_DATA_DIR` overrides both — handy for tests and for pointing a
    second machine at a copied library without moving anything.
    """
    override = os.environ.get('PAPERMEISTER_DATA_DIR')
    if override:
        return os.path.expanduser(override)
    if not os.path.isdir(DEFAULT_DATA_DIR) and os.path.isdir(LEGACY_DATA_DIR):
        return LEGACY_DATA_DIR
    return DEFAULT_DATA_DIR


DATA_DIR = _resolve_data_dir()

DB_PATH = os.path.join(DATA_DIR, 'papermeister.db')
PREFS_PATH = os.path.join(DATA_DIR, 'preferences.json')
ZOTERO_COLLECTIONS_PATH = os.path.join(DATA_DIR, 'zotero_collections.json')

OCR_JSON_DIR = os.path.join(DATA_DIR, 'ocr_json')
PDF_CACHE_DIR = os.path.join(DATA_DIR, 'pdf_cache')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
TMP_DIR = os.path.join(DATA_DIR, 'tmp')


def using_legacy_dir() -> bool:
    """True when running against the pre-0.1.4 location."""
    return DATA_DIR == LEGACY_DATA_DIR


def ensure_directories() -> None:
    """Create the data directories. Safe to call repeatedly."""
    for d in (DATA_DIR, OCR_JSON_DIR, PDF_CACHE_DIR, LOG_DIR, TMP_DIR):
        os.makedirs(d, exist_ok=True)
