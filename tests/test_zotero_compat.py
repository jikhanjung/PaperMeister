"""Zotero write-back must survive pyzotero's version differences.

pyzotero 1.13 renamed every error class with an `Error` suffix and swapped its
HTTP backend from requests to httpx. Both changes are invisible until something
fails, and then they fail in the worst way:

  * naming a missing error class in an `except` clause raises AttributeError
    *while the real exception is in flight*, replacing the actual Zotero error
    with a confusing one
  * a connection blip arriving as an httpx type instead of a requests type is
    simply not recognised as transient, so it is never retried
"""
import pytest

from papermeister import zotero_writeback as zw


@pytest.mark.unit
def test_error_lookup_prefers_the_new_name(monkeypatch):
    class UserNotAuthorisedError(Exception):
        pass

    class Stub:
        pass

    stub = Stub()
    stub.UserNotAuthorisedError = UserNotAuthorisedError
    monkeypatch.setattr('pyzotero.zotero_errors', stub, raising=False)

    assert zw._zotero_error('UserNotAuthorisedError',
                            'UserNotAuthorised') is UserNotAuthorisedError


@pytest.mark.unit
def test_error_lookup_falls_back_to_the_old_name(monkeypatch):
    """pyzotero < 1.13 has no `Error` suffix."""
    class UserNotAuthorised(Exception):
        pass

    class Stub:
        pass

    stub = Stub()
    stub.UserNotAuthorised = UserNotAuthorised
    monkeypatch.setattr('pyzotero.zotero_errors', stub, raising=False)

    assert zw._zotero_error('UserNotAuthorisedError',
                            'UserNotAuthorised') is UserNotAuthorised


@pytest.mark.unit
def test_error_lookup_of_an_unknown_name_never_fires(monkeypatch):
    """A future rename must degrade to 'not specially handled', not explode.
    An empty tuple is a valid except target that matches nothing."""
    class Stub:
        pass

    monkeypatch.setattr('pyzotero.zotero_errors', Stub(), raising=False)
    caught = zw._zotero_error('NoSuchError')
    assert caught == ()

    with pytest.raises(ValueError):
        try:
            raise ValueError('the real error')
        except caught:            # matches nothing — the original propagates
            pytest.fail('empty tuple should never catch')


@pytest.mark.unit
def test_requests_connection_errors_are_retryable():
    import requests

    assert zw._is_retryable_zotero_error(requests.exceptions.ConnectionError())
    assert zw._is_retryable_zotero_error(requests.exceptions.Timeout())


@pytest.mark.unit
def test_httpx_transport_errors_are_retryable():
    """pyzotero >= 1.13 raises these instead."""
    httpx = pytest.importorskip('httpx')

    assert zw._is_retryable_zotero_error(httpx.ConnectError('boom'))
    assert zw._is_retryable_zotero_error(httpx.ReadTimeout('boom'))


@pytest.mark.unit
def test_httpx2_transport_errors_are_retryable():
    """pyzotero >= 1.15 raises these instead."""
    httpx2 = pytest.importorskip('httpx2')

    assert zw._is_retryable_zotero_error(httpx2.ConnectError('boom'))
    assert zw._is_retryable_zotero_error(httpx2.ReadTimeout('boom'))


@pytest.mark.unit
def test_the_backend_pyzotero_installs_is_covered():
    """Each pyzotero minor so far swapped its HTTP library (requests → httpx →
    httpx2); the two tests above skip when theirs is absent. This one does
    not: whatever pyzotero brought in, its transport errors are retried."""
    import importlib.util
    present = [n for n in ('httpx', 'httpx2') if importlib.util.find_spec(n)]
    assert present, 'pyzotero brought a third HTTP library — add its TransportError'
    covered = {t.__module__.split('.')[0] for t in zw._transient_network_errors()}
    assert set(present) <= covered


@pytest.mark.unit
def test_client_errors_are_not_retryable():
    """429 and 4xx are decisions, not blips — retrying them is wrong."""
    assert not zw._is_retryable_zotero_error(Exception('Code: 429'))
    assert not zw._is_retryable_zotero_error(Exception('Code: 403'))
    assert zw._is_retryable_zotero_error(Exception('Code: 503'))
