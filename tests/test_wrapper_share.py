"""Asking the OCR wrapper how much of it is ours.

Wrapper 0.2.4 splits its capacity between the clients using it, and counts a
client as "using it" only while that client has pages in flight. A batch about
to start therefore has to say who it is, or the server answers with the whole
machine and the batch takes it — which is not a rounding error: it is the
difference between 12 pages and 6 while another PC is working.
"""
import pytest

from papermeister import ocr

MINE = 'papermeister-mine'


@pytest.fixture
def server(monkeypatch):
    """Install a /api/stats response and return the recorded call."""
    monkeypatch.setattr('papermeister.preferences.get_client_id', lambda: MINE)

    def install(payload):
        monkeypatch.setattr(ocr, 'wrapper_get_stats', lambda *a, **k: payload)

    return install


@pytest.mark.unit
def test_the_share_the_server_computed_for_us_wins(server):
    """The echoed client_id is how we know it counted us in."""
    server({'client_id': MINE, 'recommended_concurrency': 6,
            'recommended_concurrency_new_client': 6, 'concurrency': 12})
    assert ocr.wrapper_client_concurrency() == 6


@pytest.mark.unit
def test_unidentified_takes_the_new_client_figure(server):
    """Without our id the server answers for the clients already there — 12,
    the share of the one machine currently working. Taking that starves it."""
    server({'client_id': None, 'recommended_concurrency': 12,
            'recommended_concurrency_new_client': 6, 'concurrency': 12})
    assert ocr.wrapper_client_concurrency() == 6


@pytest.mark.unit
def test_someone_elses_id_is_not_ours(server):
    server({'client_id': 'papermeister-other', 'recommended_concurrency': 12,
            'recommended_concurrency_new_client': 6, 'concurrency': 12})
    assert ocr.wrapper_client_concurrency() == 6


@pytest.mark.unit
def test_an_idle_server_is_all_ours(server):
    server({'client_id': MINE, 'recommended_concurrency': 12,
            'recommended_concurrency_new_client': 12, 'concurrency': 12})
    assert ocr.wrapper_client_concurrency() == 12


@pytest.mark.unit
def test_a_wrapper_predating_the_contract_is_split_by_hand(server):
    """No echo and no new-client figure: divide what it does report by the
    clients it reports, plus us."""
    server({'recommended_concurrency': 12, 'concurrency': 12, 'active_clients': 1})
    assert ocr.wrapper_client_concurrency() == 6


@pytest.mark.unit
def test_an_older_wrapper_alone_on_the_machine(server):
    server({'recommended_concurrency': 12, 'concurrency': 12, 'active_clients': 0})
    assert ocr.wrapper_client_concurrency() == 12


@pytest.mark.unit
def test_no_answer_at_all_still_gives_a_workable_number(server):
    server({})
    assert ocr.wrapper_client_concurrency() == 6


@pytest.mark.unit
def test_stats_identifies_this_client_by_default(monkeypatch):
    """The whole contract rests on the request carrying our id."""
    monkeypatch.setattr('papermeister.preferences.get_client_id', lambda: MINE)
    monkeypatch.setattr(ocr, '_ensure_config', lambda: None)
    monkeypatch.setattr(ocr, '_WRAPPER_URL', 'http://ocr.invalid')
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'recommended_concurrency': 6}

    def fake_get(url, params=None, timeout=None):
        seen['params'] = params
        return _Resp()

    monkeypatch.setattr(ocr.requests, 'get', fake_get)

    ocr.wrapper_get_stats()
    assert seen['params'] == {'client_id': MINE}

    ocr.wrapper_get_stats(for_this_client=False)
    assert seen['params'] == {}
