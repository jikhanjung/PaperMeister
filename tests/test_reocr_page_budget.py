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
def test_the_depth_comes_from_this_clients_share(reocr, monkeypatch):
    """The script does not compute the split itself — `ocr` asks the server
    with our id attached and that answer is the budget."""
    from papermeister import ocr

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', lambda: 6)

    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_an_unreachable_server_does_not_stop_the_run(reocr, monkeypatch):
    from papermeister import ocr

    def explode():
        raise OSError('server down')

    monkeypatch.setattr(ocr, 'is_wrapper_mode', lambda: True)
    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', explode)

    assert reocr.recommended_queue_depth() == 6


@pytest.mark.unit
def test_the_budget_can_change_mid_run(reocr):
    """The share moves as clients come and go, and this run lasts days."""
    budget = reocr.PageBudget(6)
    budget.acquire(6)
    let_in = threading.Event()

    waiter = threading.Thread(target=lambda: (budget.acquire(4), let_in.set()))
    waiter.daemon = True
    waiter.start()
    waiter.join(timeout=0.2)
    assert not let_in.is_set()          # 6 + 4 does not fit in 6

    budget.set_limit(12)                # the other machine finished
    waiter.join(timeout=2)
    assert let_in.is_set()              # ...and the waiter is let straight in


@pytest.mark.unit
def test_the_watcher_follows_the_server(reocr, monkeypatch):
    from papermeister import ocr

    monkeypatch.setattr(reocr, '_SHARE_REFRESH', 0.01)
    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', lambda: 6)

    budget = reocr.PageBudget(12)
    stop = threading.Event()
    watcher = threading.Thread(target=reocr.follow_the_share, args=(budget, stop))
    watcher.daemon = True
    watcher.start()
    deadline = time.time() + 2
    while time.time() < deadline and budget.limit != 6:
        time.sleep(0.01)
    stop.set()

    assert budget.limit == 6


@pytest.mark.unit
def test_a_failed_check_leaves_the_budget_alone(reocr, monkeypatch):
    from papermeister import ocr

    monkeypatch.setattr(reocr, '_SHARE_REFRESH', 0.01)

    def explode():
        raise OSError('stats unreachable')

    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', explode)

    budget = reocr.PageBudget(6)
    stop = threading.Event()
    watcher = threading.Thread(target=reocr.follow_the_share, args=(budget, stop))
    watcher.daemon = True
    watcher.start()
    time.sleep(0.1)
    stop.set()

    assert budget.limit == 6
