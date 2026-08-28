"""TLS on a network that inspects TLS.

The lab network re-signs every connection with its own root CA. That CA is in
the OS trust store, so the browser is fine, but httpx and requests verify
against certifi's bundle and every Zotero call dies with
CERTIFICATE_VERIFY_FAILED. The old answer was to patch requests into
`verify=False`; the current one is to verify against the OS store instead.

Two things are worth pinning down: the injection happens once and never takes
the app down with it, and the discarded `verify=False` patch does not creep
back — it disabled verification for every host, and it silently stopped
covering Zotero at all when pyzotero moved to httpx.
"""
import pathlib

import pytest

from papermeister import nettls


class _FakeTruststore:
    def __init__(self):
        self.calls = 0

    def inject_into_ssl(self):
        self.calls += 1


@pytest.fixture
def fresh(monkeypatch):
    """nettls with its install-once latch reset."""
    monkeypatch.setattr(nettls, '_installed', False)
    return nettls


@pytest.mark.unit
def test_injects_once(fresh, monkeypatch):
    fake = _FakeTruststore()
    monkeypatch.setattr(fresh, 'truststore', fake)

    assert fresh.install_system_trust() is True
    assert fresh.install_system_trust() is True
    assert fake.calls == 1        # process-global: injecting twice is pointless


@pytest.mark.unit
def test_missing_truststore_is_not_fatal(fresh, monkeypatch):
    monkeypatch.setattr(fresh, 'truststore', None)
    assert fresh.install_system_trust() is False   # certifi keeps working


@pytest.mark.unit
def test_injection_failure_is_not_fatal(fresh, monkeypatch):
    class Broken:
        def inject_into_ssl(self):
            raise RuntimeError('no platform trust store here')

    monkeypatch.setattr(fresh, 'truststore', Broken())
    assert fresh.install_system_trust() is False
    assert fresh._installed is False   # not latched, so a later call may retry


@pytest.mark.unit
def test_real_truststore_installs():
    """The dependency is present and usable on this platform."""
    nettls._installed = False
    try:
        assert nettls.install_system_trust() is True
    finally:
        nettls._installed = True


ROOT = pathlib.Path(__file__).resolve().parent.parent


# The two files that discuss the old patch in prose rather than running it.
_PROSE = {'papermeister/nettls.py', 'tests/test_nettls.py'}


def _disables_verification(source):
    # Both spellings of the discarded patch: the keyword, and the setdefault
    # that fed it into every requests call.
    return 'verify=False' in source or "'verify', False" in source


def _first_party_sources():
    for spot in ('papermeister', 'desktop', 'scripts', 'main.py', 'cli.py'):
        path = ROOT / spot
        yield from ([path] if path.is_file() else path.rglob('*.py'))


@pytest.mark.unit
def test_nobody_turns_verification_off_again():
    offenders = [
        str(path.relative_to(ROOT))
        for path in _first_party_sources()
        if str(path.relative_to(ROOT)).replace('\\', '/') not in _PROSE
        and _disables_verification(path.read_text(encoding='utf-8'))
    ]
    assert not offenders, f'TLS verification disabled in: {offenders}'


@pytest.mark.unit
@pytest.mark.parametrize('entry', ['main.py', 'cli.py', 'desktop/app.py'])
def test_entry_points_install_system_trust(entry):
    source = (ROOT / entry).read_text(encoding='utf-8')
    assert 'install_system_trust' in source
