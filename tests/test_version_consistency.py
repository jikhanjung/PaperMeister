"""version.py is the single source of truth — nothing else may drift from it.

Cheap insurance against the bump-one-file-forget-another release: a bad state
fails a test instead of shipping a mislabeled build.
"""
import re
from pathlib import Path

import pytest

from version import __version__

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_version_is_semverish():
    assert re.match(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.?\d*)?$", __version__), __version__


@pytest.mark.unit
def test_changelog_has_entry_for_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog, (
        f"CHANGELOG.md has no '## [{__version__}]' section — add one before tagging")


@pytest.mark.unit
def test_installer_template_uses_placeholder_not_hardcoded_version():
    # The Inno Setup version is injected at build time; it must never be hardcoded.
    tpl = (ROOT / "installer" / "PaperMeister.iss.template").read_text(encoding="utf-8")
    assert "{{VERSION}}" in tpl


@pytest.mark.unit
def test_pyproject_does_not_hardcode_a_diverging_version():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', pyproject)
    assert m is None or m.group(1) == __version__, (
        f"pyproject version {m.group(1) if m else None} != version.py {__version__}")


@pytest.mark.unit
def test_the_window_title_carries_the_current_version():
    """It is what a user reads back when reporting a problem, so it must not
    be able to drift from version.py."""
    from papermeister import about

    assert about.window_title() == f"PaperMeister v{__version__}"


@pytest.mark.unit
@pytest.mark.parametrize("window", [
    "desktop/windows/main_window.py",
    "papermeister/ui/main_window.py",
])
def test_neither_main_window_hardcodes_its_title(window):
    source = (ROOT / window).read_text(encoding="utf-8")
    assert "about.window_title()" in source
    assert "setWindowTitle('PaperMeister')" not in source
