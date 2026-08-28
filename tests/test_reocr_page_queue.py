"""How much the re-OCR batch keeps queued on a server it shares.

A wrapper job is a whole PDF, so "N papers at once" is not a measure of load:
at this library's median of 13 pages, twelve papers is 156 pages against a
server that runs twelve. Pages are the unit.

The target is a floor to submit up to, not a ceiling to stay under. The server
admits only this client's share regardless, so a little queued behind that
share is what keeps it from going idle between papers — and cannot take
anything from the other machine, whose admission is capped the same way.
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
def test_the_queue_stays_near_the_target(reocr):
    """Bounded, but not strictly under: one paper may cross the line, which is
    the buffer that keeps the share busy."""
    queue = reocr.PageQueue(12)
    peak = [0]
    live = [0]
    guard = threading.Lock()

    def paper(pages):
        queue.acquire(pages)
        with guard:
            live[0] += pages
            peak[0] = max(peak[0], live[0])
        time.sleep(0.02)
        with guard:
            live[0] -= pages
        queue.release(pages)

    threads = [threading.Thread(target=paper, args=(5,)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] <= 12 + 5        # the target, plus at most one more paper


@pytest.mark.unit
def test_a_full_share_still_has_something_queued_behind_it(reocr):
    """in-flight + waiting stays strictly above the share.

    The bug this fixes: stopping at exactly the share leaves nothing queued
    behind it, so the first page to finish empties a slot with no replacement
    waiting — visible as in-flight dipping 6 → 5 → 3 while the server has work
    to hand over."""
    queue = reocr.PageQueue(6)
    queue.acquire(6)                # the share is full...

    buffered = threading.Event()
    ahead = threading.Thread(target=lambda: (queue.acquire(2), buffered.set()))
    ahead.daemon = True
    ahead.start()
    ahead.join(timeout=1)

    assert buffered.is_set()        # ...and one more paper goes in behind it


@pytest.mark.unit
def test_the_buffer_is_one_paper_and_no_more(reocr):
    queue = reocr.PageQueue(6)
    queue.acquire(6)
    queue.acquire(2)                # the buffer

    third = threading.Event()
    more = threading.Thread(target=lambda: (queue.acquire(1), third.set()))
    more.daemon = True
    more.start()
    more.join(timeout=0.3)

    assert not third.is_set()       # 8 outstanding against a share of 6 is enough


@pytest.mark.unit
def test_a_paper_larger_than_the_target_still_runs(reocr):
    """A 832-page plate volume against a 6-page target must not deadlock — it
    goes in on its own and the queue simply runs long for a while."""
    queue = reocr.PageQueue(6)
    done = threading.Event()

    thread = threading.Thread(target=lambda: (queue.acquire(832), done.set()))
    thread.start()
    thread.join(timeout=2)

    assert done.is_set()


@pytest.mark.unit
def test_an_oversized_paper_does_not_let_others_in(reocr):
    queue = reocr.PageQueue(12)
    queue.acquire(832)
    joined = threading.Event()

    thread = threading.Thread(target=lambda: (queue.acquire(1), joined.set()))
    thread.daemon = True
    thread.start()
    thread.join(timeout=0.3)

    assert not joined.is_set()
    queue.release(832)
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
def test_the_target_can_change_mid_run(reocr):
    """The share moves as clients come and go, and this run lasts days."""
    queue = reocr.PageQueue(6)
    queue.acquire(6)
    queue.acquire(4)                    # the buffer — outstanding is now 10
    let_in = threading.Event()

    waiter = threading.Thread(target=lambda: (queue.acquire(4), let_in.set()))
    waiter.daemon = True
    waiter.start()
    waiter.join(timeout=0.2)
    assert not let_in.is_set()          # 10 outstanding is past a share of 6

    queue.set_limit(12)                 # the other machine finished
    waiter.join(timeout=2)
    assert let_in.is_set()              # ...and the waiter is let straight in


@pytest.mark.unit
def test_the_watcher_follows_the_server(reocr, monkeypatch):
    from papermeister import ocr

    monkeypatch.setattr(reocr, '_SHARE_REFRESH', 0.01)
    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', lambda: 6)

    queue = reocr.PageQueue(12)
    stop = threading.Event()
    watcher = threading.Thread(target=reocr.follow_the_share, args=(queue, stop))
    watcher.daemon = True
    watcher.start()
    deadline = time.time() + 2
    while time.time() < deadline and queue.limit != 6:
        time.sleep(0.01)
    stop.set()

    assert queue.limit == 6


@pytest.mark.unit
def test_a_failed_check_leaves_the_budget_alone(reocr, monkeypatch):
    from papermeister import ocr

    monkeypatch.setattr(reocr, '_SHARE_REFRESH', 0.01)

    def explode():
        raise OSError('stats unreachable')

    monkeypatch.setattr(ocr, 'wrapper_client_concurrency', explode)

    queue = reocr.PageQueue(6)
    stop = threading.Event()
    watcher = threading.Thread(target=reocr.follow_the_share, args=(queue, stop))
    watcher.daemon = True
    watcher.start()
    time.sleep(0.1)
    stop.set()

    assert queue.limit == 6
