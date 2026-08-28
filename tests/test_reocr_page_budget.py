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
def test_the_recommendation_is_this_clients_share(reocr, monkeypatch, capsys):
    """The wrapper splits its capacity between attached clients, so the number
    it reports is already this client's own."""
    from papermeister import ocr

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_get_stats', lambda: {
        'recommended_concurrency': 6,
        'clients_active': 2,
        'counts': {'processing': 13, 'queued': 4},
    })

    assert reocr.recommended_queue_depth() == 6
    assert 'shared with 1 other client' in capsys.readouterr().out


@pytest.mark.unit
def test_other_clients_work_is_not_deducted_twice(reocr, monkeypatch):
    """Deducting what other clients have in flight looks careful and is not:
    the server has already deducted it, and doing it again walks this batch
    down to a crawl while its own share sits idle."""
    from papermeister import ocr

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_get_stats', lambda: {
        'recommended_concurrency': 6,
        'counts': {'processing': 40, 'queued': 20},
    })

    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_an_unreachable_server_does_not_stop_the_run(reocr, monkeypatch):
    from papermeister import ocr

    def explode():
        raise OSError('server down')

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_get_stats', explode)

    assert reocr.recommended_queue_depth() == 6
