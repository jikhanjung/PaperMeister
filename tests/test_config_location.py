"""Settings live in the OS config location, not with the library.

They are machine-local state — and hold API keys in plain text — so they do not
belong in a directory the user may later move, copy between machines, or point
at a synced drive. Keeping them out is also what lets the data directory become
configurable later: the setting that records where the data is cannot itself
live there.
"""
import importlib
import json
import os
import sys

import pytest

DATA_DIR_ENV_VAR = 'PAPERMEISTER_DATA_DIR'
CONFIG_DIR_ENV_VAR = 'PAPERMEISTER_CONFIG_DIR'


def _reimport():
    for name in [m for m in sys.modules if m.startswith('papermeister')]:
        del sys.modules[name]
    return importlib.import_module('papermeister.paths')


def _resolve(monkeypatch, home):
    """Re-resolve paths.py with both locations pointed inside `home`.

    The config directory is pinned through the product's own override rather
    than the environment the OS reads. On Windows `platformdirs` resolves via
    ctypes, so `%LOCALAPPDATA%` cannot be redirected — an earlier version of this
    helper set `XDG_CONFIG_HOME`, which isolated Linux only and left the Windows
    run reading and writing the live profile. These tests then became
    order-dependent there: one wrote settings to the real location and the next
    read them back instead of migrating (devlog 086).
    """
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.setenv(CONFIG_DIR_ENV_VAR, str(home / 'config'))
    return _reimport()


@pytest.mark.unit
def test_the_config_location_is_isolated_from_the_real_profile(monkeypatch, tmp_path):
    """Guards the helper above. Without it these tests touch the developer's (or
    the runner's) actual settings, which shows up as nothing on Linux and as an
    order-dependent failure on Windows."""
    paths = _resolve(monkeypatch, tmp_path)

    assert paths.CONFIG_DIR.startswith(str(tmp_path)), paths.CONFIG_DIR


@pytest.mark.unit
def test_the_config_override_names_the_directory_itself(monkeypatch, tmp_path):
    """No vendor segment is appended to an override — the same meaning the
    sibling projects give theirs, so one habit works across the family."""
    elsewhere = tmp_path / 'somewhere' / 'else'
    monkeypatch.setenv(CONFIG_DIR_ENV_VAR, str(elsewhere))

    paths = _reimport()

    assert paths.CONFIG_DIR == str(elsewhere)
    assert paths.PREFS_PATH == os.path.join(str(elsewhere), 'preferences.json')


@pytest.mark.unit
def test_settings_are_outside_the_data_directory(monkeypatch, tmp_path):
    """Asserted with both overrides cleared, so the real resolution runs.

    Pointing the two somewhere different and then asserting they differ would
    restate what the test just did rather than check the layout.
    """
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(CONFIG_DIR_ENV_VAR, raising=False)

    paths = _reimport()

    assert not paths.PREFS_PATH.startswith(paths.DATA_DIR), (
        'settings in the library would have to travel with it')


@pytest.mark.unit
def test_vendor_grouping_is_applied(monkeypatch, tmp_path):
    """platformdirs drops `appauthor` on macOS and Linux, so the PaleoBytes
    segment is appended by hand — the suite shares it on every platform.

    Checked against real resolution: the override names a directory outright, so
    asserting the tail while one is set would only measure the override.
    """
    monkeypatch.delenv(CONFIG_DIR_ENV_VAR, raising=False)

    paths = _reimport()

    assert paths.CONFIG_DIR.endswith(os.path.join('PaleoBytes', 'PaperMeister'))


@pytest.mark.unit
def test_legacy_settings_are_copied_forward(monkeypatch, tmp_path):
    paths = _resolve(monkeypatch, tmp_path)
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    with open(paths.LEGACY_PREFS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'zotero_api_key': 'secret', 'ocr_pod_url': 'http://x'}, f)

    assert paths.migrate_legacy_config() is True

    with open(paths.PREFS_PATH, encoding='utf-8') as f:
        assert json.load(f)['zotero_api_key'] == 'secret'
    assert os.path.exists(paths.LEGACY_PREFS_PATH), (
        'the original is kept so an older build still finds its settings')


@pytest.mark.unit
def test_migration_never_overwrites_current_settings(monkeypatch, tmp_path):
    """Once settings exist in the new location they are the live ones; copying a
    stale legacy file over them would silently revert configuration."""
    paths = _resolve(monkeypatch, tmp_path)
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(paths.LEGACY_PREFS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'ocr_pod_url': 'old'}, f)
    with open(paths.PREFS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'ocr_pod_url': 'current'}, f)

    assert paths.migrate_legacy_config() is False

    with open(paths.PREFS_PATH, encoding='utf-8') as f:
        assert json.load(f)['ocr_pod_url'] == 'current'


@pytest.mark.unit
def test_reading_a_preference_triggers_the_migration(monkeypatch, tmp_path):
    """Scripts and the CLI reach settings without the app's startup path, so the
    migration hangs off the first read rather than an entry point."""
    paths = _resolve(monkeypatch, tmp_path)
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    with open(paths.LEGACY_PREFS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'ocr_pod_url': 'http://server'}, f)

    from papermeister import preferences

    assert preferences.get_pref('ocr_pod_url') == 'http://server'
    assert os.path.exists(paths.PREFS_PATH)
