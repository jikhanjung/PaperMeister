"""Where user data lives — the single source of truth for every path.

Layout follows the PaleoBytes convention shared with Modan2 and CTHarvester::

    ~/PaleoBytes/PaperMeister/
    ├── papermeister.db
    ├── zotero_collections.json
    ├── ocr_json/          cached OCR output, one file per PDF
    ├── pdf_cache/         PDFs fetched from Zotero
    ├── logs/
    └── tmp/

Settings are the exception: ``preferences.json`` lives in the OS config location
instead, because it is machine-local state (and holds API keys in plain text)
rather than part of the library. Keeping it out also means the data directory can
later be moved or pointed elsewhere without the setting that records where it is
having to travel with it.

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
import shutil

import platformdirs

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
ZOTERO_COLLECTIONS_PATH = os.path.join(DATA_DIR, 'zotero_collections.json')

#: OS config location, with the PaleoBytes grouping appended on every platform:
#:   Windows  %LOCALAPPDATA%\PaleoBytes\PaperMeister
#:   macOS    ~/Library/Application Support/PaleoBytes/PaperMeister
#:   Linux    ~/.config/PaleoBytes/PaperMeister
#:
#: platformdirs resolves the root — hand-rolling it breaks on XDG_CONFIG_HOME and
#: on localized Windows. Qt's QStandardPaths would do the same job, but paths.py
#: is imported by cli.py and every script, and pulling PyQt6 into those would end
#: the CLI's freedom from Qt. The vendor segment is appended by hand because
#: platformdirs drops `appauthor` on macOS and Linux, where it is not the
#: convention — the PaleoBytes grouping is shared with the rest of the suite, and
#: each of the three paths is a legitimate location for its platform.
CONFIG_DIR = os.path.join(
    platformdirs.user_config_dir(), COMPANY_NAME, PROGRAM_NAME)
PREFS_PATH = os.path.join(CONFIG_DIR, 'preferences.json')
#: Where settings lived before 0.1.5. Copied forward by `migrate_legacy_config`.
LEGACY_PREFS_PATH = os.path.join(DATA_DIR, 'preferences.json')

OCR_JSON_DIR = os.path.join(DATA_DIR, 'ocr_json')
PDF_CACHE_DIR = os.path.join(DATA_DIR, 'pdf_cache')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
TMP_DIR = os.path.join(DATA_DIR, 'tmp')


class DataDirUnavailable(RuntimeError):
    """A configured data directory is not there to be used."""


def check_configured_data_dir() -> None:
    """Refuse to start when a configured data directory has gone missing.

    An external drive that is not plugged in looks exactly like a first run, and
    the two want opposite responses: create the library, or do not touch
    anything and say so. Guess wrong in the second case and the user is shown an
    empty window, which reads as having lost everything.

    Only `PAPERMEISTER_DATA_DIR` is checked. The default location is ours to
    create; one the user named is theirs to provide, so its absence is a fact to
    report rather than a directory to make.

    The test is on the parent rather than the directory itself, so that pointing
    at a new location for the first time still works. What it catches is the
    drive or share that is not mounted at all.
    """
    if not os.environ.get('PAPERMEISTER_DATA_DIR'):
        return
    parent = os.path.dirname(DATA_DIR.rstrip(os.sep))
    if parent and not os.path.isdir(parent):
        raise DataDirUnavailable(
            f'The configured data directory is not available:\n  {DATA_DIR}\n\n'
            f'{parent} does not exist — is the drive connected?\n\n'
            'Check PAPERMEISTER_DATA_DIR, or unset it to use the default '
            f'location:\n  {DEFAULT_DATA_DIR}')


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


def migrate_legacy_config() -> bool:
    """Copy settings forward from the data directory. True if copied.

    Unlike the library, this is under a kilobyte, so moving it automatically is
    reasonable — the same line devlog 084 drew for the data directory, on the
    other side of it.

    The original is left in place rather than deleted: it costs nothing, and an
    older build started against the same machine still finds its settings
    instead of coming up unconfigured.
    """
    if os.path.exists(PREFS_PATH) or not os.path.exists(LEGACY_PREFS_PATH):
        return False
    os.makedirs(CONFIG_DIR, exist_ok=True)
    shutil.copy2(LEGACY_PREFS_PATH, PREFS_PATH)
    logging.getLogger('papermeister').info(
        'Copied settings from %s to %s; the original is left in place and can '
        'be deleted once this build is known good.',
        LEGACY_PREFS_PATH, PREFS_PATH)
    return True


def ensure_directories() -> None:
    """Create the data directories. Safe to call repeatedly."""
    for d in (DATA_DIR, OCR_JSON_DIR, PDF_CACHE_DIR, LOG_DIR, TMP_DIR, CONFIG_DIR):
        os.makedirs(d, exist_ok=True)
