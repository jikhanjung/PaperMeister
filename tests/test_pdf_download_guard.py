"""A Zotero PDF download is checked before it is cached: KOPRI's web filter
now and then answers with its own HTML block page, and asking again goes
through. Unchecked, that page was stored in pdf_cache as the paper's PDF,
hashed, and reused by the PDF tab and the figure lanes (devlog 116)."""
import os
from types import SimpleNamespace

import pytest
import requests

from papermeister.file_utils import looks_like_pdf
from papermeister.zotero_client import NotAPdfError, ZoteroClient

PDF = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n'
BLOCK_PAGE = b'<html><script>location.href="http://warning.example/warning.html"</script></html>'


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda s: None)


def _client(monkeypatch, *answers):
    """A client whose file endpoint gives these answers in turn (bytes are
    returned, exceptions raised); `calls` counts the requests."""
    client = ZoteroClient('1', 'k')
    client.calls = 0
    queue = list(answers)

    def download_file_content(key):
        client.calls += 1
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client, 'download_file_content', download_file_content)
    return client


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    resp.reason = 'Not Found' if status == 404 else 'Service Unavailable'
    return requests.HTTPError(f'{status} {"Client" if status < 500 else "Server"} Error: {resp.reason}',
                              response=resp)


@pytest.mark.unit
@pytest.mark.parametrize('content, expected', [
    (PDF, True),
    (b'\r\n\xef\xbb\xbfjunk' + PDF, True),       # junk before the header, as readers allow
    (b'x' * 1100 + PDF, False),                   # too far in to be a header
    (BLOCK_PAGE, False),
    (b'', False),
])
def test_looks_like_pdf(content, expected):
    assert looks_like_pdf(content) is expected


@pytest.mark.unit
def test_block_page_is_retried_until_the_pdf_comes(monkeypatch):
    client = _client(monkeypatch, BLOCK_PAGE, PDF)
    assert client.download_pdf_content('KEY') == PDF
    assert client.calls == 2


@pytest.mark.unit
def test_dropped_connection_is_retried(monkeypatch):
    client = _client(monkeypatch, requests.ConnectionError('Remote end closed connection'), PDF)
    assert client.download_pdf_content('KEY') == PDF
    assert client.calls == 2


@pytest.mark.unit
def test_server_error_is_retried(monkeypatch):
    client = _client(monkeypatch, _http_error(503), PDF)
    assert client.download_pdf_content('KEY') == PDF


@pytest.mark.unit
def test_missing_file_is_not_retried(monkeypatch):
    client = _client(monkeypatch, _http_error(404), PDF)
    with pytest.raises(requests.HTTPError):
        client.download_pdf_content('KEY')
    assert client.calls == 1


@pytest.mark.unit
def test_gives_up_with_a_reason(monkeypatch):
    client = _client(monkeypatch, BLOCK_PAGE, BLOCK_PAGE, BLOCK_PAGE)
    with pytest.raises(NotAPdfError, match=r'KEY: not a PDF \(\d+ bytes, HTML'):
        client.download_pdf_content('KEY')
    assert client.calls == 3


@pytest.mark.unit
def test_empty_body_says_the_file_is_missing(monkeypatch):
    client = _client(monkeypatch, b'', b'', b'')
    with pytest.raises(NotAPdfError, match='missing from Zotero web storage'):
        client.download_pdf_content('KEY')


@pytest.fixture
def resolve(monkeypatch, tmp_path):
    """_resolve_filepath with a temp pdf_cache, credentials set, and the
    Zotero file endpoint answering with `answers`."""
    from papermeister import preferences, text_extract
    monkeypatch.setattr(text_extract, 'PDF_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(preferences, 'get_pref', lambda key, default=None: 'x')

    def run(*answers):
        queue = list(answers)
        monkeypatch.setattr(ZoteroClient, 'download_file_content', lambda self, key: queue.pop(0))
        pf = SimpleNamespace(zotero_key='KEY', path='a.pdf')
        return text_extract._resolve_filepath(pf)

    return run, tmp_path


@pytest.mark.integration
def test_resolve_caches_the_pdf_after_a_block_page(resolve):
    run, cache = resolve
    path, is_temp = run(BLOCK_PAGE, PDF)
    assert path == os.path.join(str(cache), 'KEY', 'a.pdf') and not is_temp
    with open(path, 'rb') as f:
        assert f.read() == PDF


@pytest.mark.integration
def test_resolve_caches_nothing_when_no_pdf_comes(resolve):
    run, cache = resolve
    with pytest.raises(RuntimeError, match='not a PDF'):
        run(BLOCK_PAGE, BLOCK_PAGE, BLOCK_PAGE)
    assert not os.path.exists(os.path.join(str(cache), 'KEY', 'a.pdf'))
