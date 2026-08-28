"""The re-OCR batch shares its OCR server with another machine.

A wrapper job is a whole PDF, so "N papers at once" is not a measure of load:
at this library's median of 13 pages, twelve papers is 156 pages queued against
a server asking for twelve. The batch has to hold itself to a page budget, and
to take only what the server has free — the other machine's run is the one that
cannot afford to wait.
"""
import importlib.util
import pathlib
import threading
import time

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / 'scripts' / 'reocr_legacy_ocr.py'


@pytest.fixture(scope='module')
def reocr():
    spec = importlib.util.spec_from_file_location('reocr_legacy_ocr', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_server(monkeypatch, capacity, jobs, active_clients=0, share=None):
    """`share` is what the server answers when asked about *this* client;
    None models an older wrapper that answers with the whole machine."""
    from papermeister import ocr, preferences

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_get_stats', lambda *a, **k: {
        'concurrency': capacity,
        'recommended_concurrency': capacity if share is None else share,
        'active_clients': active_clients,
    })
    monkeypatch.setattr(ocr, 'wrapper_list_jobs', lambda: jobs)
    monkeypatch.setattr(preferences, 'get_client_id', lambda: 'papermeister-mine')


@pytest.mark.unit
def test_pages_in_flight_stay_under_the_budget(reocr):
    budget = reocr.PageBudget(12)
    peak = [0]
    live = [0]
    guard = threading.Lock()

    def paper(pages):
        budget.acquire(pages)
        with guard:
            live[0] += pages
            peak[0] = max(peak[0], live[0])
        time.sleep(0.02)
        with guard:
            live[0] -= pages
        budget.release(pages)

    threads = [threading.Thread(target=paper, args=(5,)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] <= 12


@pytest.mark.unit
def test_a_paper_larger_than_the_budget_still_runs(reocr):
    """A 832-page plate volume against a 12-page budget must not deadlock —
    it runs on its own instead."""
    budget = reocr.PageBudget(12)
    done = threading.Event()

    thread = threading.Thread(target=lambda: (budget.acquire(832), done.set()))
    thread.start()
    thread.join(timeout=2)

    assert done.is_set()


@pytest.mark.unit
def test_an_oversized_paper_does_not_let_others_in(reocr):
    budget = reocr.PageBudget(12)
    budget.acquire(832)
    joined = threading.Event()

    thread = threading.Thread(target=lambda: (budget.acquire(1), joined.set()))
    thread.daemon = True
    thread.start()
    thread.join(timeout=0.3)

    assert not joined.is_set()
    budget.release(832)
    thread.join(timeout=2)
    assert joined.is_set()


@pytest.mark.unit
def test_the_arriving_client_counts_itself_in(reocr, monkeypatch, capsys):
    """The server can only divide by the clients it can see, and this one is
    not one of them until it submits. Reading the recommendation straight off
    an idle-looking server hands over the whole machine."""
    _stub_server(monkeypatch, capacity=12, jobs=[
        {'status': 'processing', 'client_id': 'papermeister-other'},
        {'status': 'processing', 'client_id': 'papermeister-other'},
    ])

    assert reocr.recommended_queue_depth() == 6          # 12 // (1 other + me)
    assert 'with 1 other client' in capsys.readouterr().out


@pytest.mark.unit
def test_an_empty_server_is_still_shared_with_nobody(reocr, monkeypatch):
    _stub_server(monkeypatch, capacity=12, jobs=[
        {'status': 'done', 'client_id': 'papermeister-other'},
    ])
    assert reocr.recommended_queue_depth() == 12


@pytest.mark.unit
def test_this_clients_own_jobs_are_not_mistaken_for_a_rival(reocr, monkeypatch):
    """A resumed run has its previous jobs still finishing. Counting them as
    another client halves the share for no reason."""
    _stub_server(monkeypatch, capacity=12, jobs=[
        {'status': 'processing', 'client_id': 'papermeister-mine'},
        {'status': 'queued', 'client_id': 'papermeister-mine'},
    ])
    assert reocr.recommended_queue_depth() == 12


@pytest.mark.unit
def test_three_clients_get_a_third_each(reocr, monkeypatch):
    _stub_server(monkeypatch, capacity=12, jobs=[
        {'status': 'processing', 'client_id': 'papermeister-a'},
        {'status': 'processing', 'client_id': 'papermeister-b'},
    ])
    assert reocr.recommended_queue_depth() == 4


@pytest.mark.unit
def test_without_a_job_list_the_servers_own_count_is_used(reocr, monkeypatch):
    _stub_server(monkeypatch, capacity=12, jobs=[], active_clients=1)
    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_an_unreachable_server_does_not_stop_the_run(reocr, monkeypatch):
    from papermeister import ocr

    def explode():
        raise OSError('server down')

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_get_stats', explode)

    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_the_servers_own_answer_for_this_client_is_used(reocr, monkeypatch):
    """Wrapper 0.2.4 answers ?client_id= with that client's share. It knows
    better than any count we can do from outside."""
    _stub_server(monkeypatch, capacity=12, share=6, jobs=[])
    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_an_older_wrapper_does_not_get_to_hand_over_the_machine(reocr, monkeypatch):
    """A wrapper that ignores the client_id parameter answers with the whole
    server. A batch of 58,000 pages must not quietly accept that."""
    _stub_server(monkeypatch, capacity=12, share=None, jobs=[
        {'status': 'processing', 'client_id': 'papermeister-other'},
    ])
    assert reocr.recommended_queue_depth() == 6
