"""Where user data lives.

Getting this wrong is the expensive kind of bug: pointing at a directory that
does not hold the library makes the app come up empty and start building a fresh
one beside the real data. Modan2 hit exactly that once.

Resolution is deliberately unconditional — the location is a constant, with an
env override for tests. The pre-0.1.4 directory is not read; it is only reported,
so that same failure cannot happen quietly on a machine that still has one.
"""
import importlib
import os
import sys

import pytest


def _resolve(monkeypatch, home, *, override=None):
    """Re-resolve paths.py under a fake HOME."""
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))     # Windows
    if override is None:
        monkeypatch.delenv('PAPERMEISTER_DATA_DIR', raising=False)
    else:
        monkeypatch.setenv('PAPERMEISTER_DATA_DIR', str(override))
    for name in [m for m in sys.modules if m.startswith('papermeister.paths')]:
        del sys.modules[name]
    return importlib.import_module('papermeister.paths')


@pytest.mark.unit
def test_fresh_install_uses_the_paleobytes_location(monkeypatch, tmp_path):
    paths = _resolve(monkeypatch, tmp_path)
    assert paths.DATA_DIR == os.path.join(str(tmp_path), 'PaleoBytes', 'PaperMeister')


@pytest.mark.unit
def test_a_legacy_directory_does_not_change_where_data_goes(monkeypatch, tmp_path):
    """No fallback: the location stays a constant even if old data is present."""
    (tmp_path / '.papermeister').mkdir()

    paths = _resolve(monkeypatch, tmp_path)

    assert paths.DATA_DIR == os.path.join(str(tmp_path), 'PaleoBytes', 'PaperMeister')


@pytest.mark.unit
def test_stray_legacy_data_is_reported(monkeypatch, tmp_path, caplog):
    """Starting an empty library beside real data looks exactly like data loss,
    so it has to be said out loud rather than found later."""
    import logging
    (tmp_path / '.papermeister').mkdir()
    paths = _resolve(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING, logger='papermeister'):
        assert paths.warn_if_legacy_dir() is True

    text = '\n'.join(r.getMessage() for r in caplog.records)
    assert '.papermeister' in text and 'migrate_data_dir' in text


@pytest.mark.unit
def test_nothing_is_reported_once_migrated(monkeypatch, tmp_path):
    """Both directories can exist after a migration — that is not a warning."""
    (tmp_path / '.papermeister').mkdir()
    (tmp_path / 'PaleoBytes' / 'PaperMeister').mkdir(parents=True)

    paths = _resolve(monkeypatch, tmp_path)

    assert paths.warn_if_legacy_dir() is False


@pytest.mark.unit
def test_env_override_beats_both(monkeypatch, tmp_path):
    (tmp_path / '.papermeister').mkdir()
    elsewhere = tmp_path / 'elsewhere'

    paths = _resolve(monkeypatch, tmp_path, override=elsewhere)

    assert paths.DATA_DIR == str(elsewhere)


@pytest.mark.unit
def test_the_library_sits_under_the_data_dir(monkeypatch, tmp_path):
    """Everything belonging to the library stays under DATA_DIR — that is what
    makes moving it one operation. Settings are deliberately not in this list:
    they are machine-local and live in the OS config location instead (see
    test_config_location)."""
    paths = _resolve(monkeypatch, tmp_path)

    for value in (paths.DB_PATH, paths.ZOTERO_COLLECTIONS_PATH,
                  paths.OCR_JSON_DIR, paths.PDF_CACHE_DIR, paths.LOG_DIR,
                  paths.TMP_DIR):
        assert value.startswith(paths.DATA_DIR), value

    assert not paths.PREFS_PATH.startswith(paths.DATA_DIR)


@pytest.mark.unit
def test_ensure_directories_is_repeatable(monkeypatch, tmp_path):
    paths = _resolve(monkeypatch, tmp_path)

    paths.ensure_directories()
    paths.ensure_directories()          # must not raise on the second call

    for d in (paths.DATA_DIR, paths.OCR_JSON_DIR, paths.PDF_CACHE_DIR,
              paths.LOG_DIR, paths.TMP_DIR):
        assert os.path.isdir(d), d
