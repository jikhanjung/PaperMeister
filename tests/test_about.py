"""The About tab's licensing claims have to stay true.

The application is distributed under the AGPL-3.0 because it links PyQt6
(GPL-3.0) and PyMuPDF (AGPL-3.0). That conclusion is only as good as the
dependency list it rests on, so a dependency whose licence changes — or a new
copyleft one arriving — should fail a test rather than quietly make the About
tab and the LICENSE file wrong. See devlog/20260813_R03_License_Audit.md.
"""
import pathlib
import re
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

import pytest

from papermeister import about

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_version_matches_the_single_source():
    from version import __version__
    assert about.APP_VERSION == __version__


@pytest.mark.unit
def test_license_file_is_the_gpl_and_not_the_agpl():
    """The GPL and the AGPL share nearly all their text and differ at §13, so
    shipping the wrong one is not something you would catch by eye. Assert in
    both directions: the right title, and the absence of the clause that only
    the AGPL has.
    """
    text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
    head = text[:200]
    assert 'GNU GENERAL PUBLIC LICENSE' in head
    assert 'AFFERO' not in head, 'this is the AGPL, not the GPL'
    assert '13. Remote Network Interaction' not in text, 'AGPL §13 present'
    assert '13. Use with the GNU Affero General Public License' in text
    assert len(text) > 30_000, 'looks truncated, not the full licence text'


@pytest.mark.unit
def test_declared_license_matches_the_license_file():
    assert about.APP_LICENSE.startswith('GPL-3.0')


def _declared_by(name: str) -> str:
    """Everything the installed distribution says about its own licence.

    Metadata first, then any bundled licence file — several packages (peewee)
    carry no licence metadata at all and the file is the only evidence there is.
    """
    md = metadata(name)                       # raises if not installed
    parts = [md.get('License-Expression') or '', md.get('License') or '']
    parts += [c for c in (md.get_all('Classifier') or []) if c.startswith('License ::')]
    try:
        from importlib.metadata import distribution
        root = pathlib.Path(distribution(name)._path)
        for f in root.rglob('*'):
            if f.is_file() and f.name.upper().startswith(('LICENSE', 'COPYING')):
                parts.append(f.read_text(errors='ignore')[:4000])
    except Exception:
        pass
    return ' '.join(parts).lower()


@pytest.mark.unit
@pytest.mark.parametrize('name,displayed,pattern', about.THIRD_PARTY)
def test_third_party_licenses_match_what_is_installed(name, displayed, pattern):
    """Compare against the installed distribution's own declaration."""
    try:
        haystack = _declared_by(name)
    except PackageNotFoundError:
        pytest.skip(f'{name} not installed in this environment')

    assert re.search(pattern, haystack), (
        f'about.py shows {displayed!r} for {name}, but nothing matching '
        f'{pattern!r} appears in what {name} declares about itself')


@pytest.mark.unit
def test_every_runtime_dependency_is_listed():
    """A new dependency has to be triaged into the table, because a copyleft one
    would change what licence the whole application can be distributed under."""
    req = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    declared = {row[0].lower() for row in about.THIRD_PARTY}
    for line in req.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        pkg = re.split(r'[<>=~!\[]', line)[0].strip().lower()
        assert pkg in declared, (
            f'{pkg} is a runtime dependency but is missing from about.THIRD_PARTY '
            f'— check its licence before adding it')


@pytest.mark.unit
def test_the_copyleft_components_are_named_in_the_summary():
    """The summary should say *why* the app is AGPL, not merely assert it."""
    summary = about.license_summary()
    for component in about.COPYLEFT_COMPONENTS:
        assert component in summary
    assert about.APP_URL in summary, 'AGPL distribution has to point at the source'
