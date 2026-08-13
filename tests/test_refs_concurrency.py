"""The desktop references batch parses several papers at once.

A single LLM request decodes its tokens serially, so packing more references
into one call buys almost nothing (measured on the live server: 12 references
in one call vs twelve calls is 1.2x, and the decode rate is ~21 tok/s either
way). Concurrent requests are the axis that pays, because vLLM batches them
into one forward pass over the weights — four papers in flight finished the
same work 4.0x faster with per-request latency unchanged.

scripts/extract_references.py has had `--workers` since 05c79d6; the desktop
stayed serial. These cover the scheduling half of catching it up: the slots
fill, they refill as papers finish, and the things that were only safe because
refs ran one at a time stay safe.
"""
import types

import pytest

from desktop.windows.main_window import MainWindow


class _FakeTask:
    """Stands in for a BackgroundTask that is still running."""

    def __init__(self):
        self._running = True

    def isRunning(self):
        return self._running

    def finish(self):
        self._running = False


class _FakeGuard:
    def __init__(self, paused=False):
        self._paused = paused

    def paused(self):
        return self._paused


def _window(workers=4, queue=(), paused=False):
    """A stand-in carrying only what the drain path touches.

    The scheduling methods are taken unbound off MainWindow, so the code under
    test is the real one; constructing a MainWindow would need the whole app
    and a database behind it.
    """
    win = types.SimpleNamespace(
        _refs_tasks={},
        _refs_queue=list(queue),
        _refs_guard=_FakeGuard(paused),
        _refs_window=None,
        started=[],
    )

    def _start(paper_id, file_id):
        win.started.append(paper_id)
        win._refs_tasks[paper_id] = _FakeTask()

    win._refs_running = types.MethodType(MainWindow._refs_running, win)
    win._drain_refs_queue = types.MethodType(MainWindow._drain_refs_queue, win)
    win._refs_workers = lambda: workers
    win._run_references_extraction_silent = _start
    return win


@pytest.mark.unit
def test_drain_fills_every_slot_not_just_one():
    win = _window(workers=4, queue=[(i, i) for i in range(10)])

    win._drain_refs_queue()

    assert win.started == [0, 1, 2, 3]
    assert len(win._refs_queue) == 6


@pytest.mark.unit
def test_drain_refills_as_papers_finish():
    win = _window(workers=3, queue=[(i, i) for i in range(6)])
    win._drain_refs_queue()
    assert win.started == [0, 1, 2]

    win._refs_tasks[1].finish()      # one paper done
    win._drain_refs_queue()

    # Exactly one slot opened, so exactly one more paper starts.
    assert win.started == [0, 1, 2, 3]
    assert win._refs_running() == 3


@pytest.mark.unit
def test_a_paused_server_starts_nothing():
    """ServerGuard pauses the batch while the LLM server is down; the queue is
    kept so it can resume. Starting work anyway would spend the outage failing
    papers and marking them for retry."""
    win = _window(workers=4, queue=[(i, i) for i in range(5)], paused=True)

    win._drain_refs_queue()

    assert win.started == []
    assert len(win._refs_queue) == 5


@pytest.mark.unit
def test_workers_never_exceeds_the_queue():
    win = _window(workers=4, queue=[(1, 1)])

    win._drain_refs_queue()

    assert win.started == [1]
    assert win._refs_queue == []


@pytest.mark.unit
def test_unusable_entries_do_not_recurse_or_stall():
    """A queued paper whose file went missing is skipped without re-entering
    the drain — a long run of them would otherwise nest one level each."""
    win = _window(workers=2, queue=[(i, i) for i in range(5)])

    def _start(paper_id, file_id):
        if paper_id < 3:
            return                   # no hash → skipped, no slot taken
        win.started.append(paper_id)
        win._refs_tasks[paper_id] = _FakeTask()

    win._run_references_extraction_silent = _start
    win._drain_refs_queue()

    assert win.started == [3, 4]     # walked past the three unusable ones
    assert win._refs_queue == []


@pytest.mark.unit
def test_claude_backend_stays_serial(monkeypatch):
    """Only the local qwen server batches concurrent requests. Firing parallel
    claude calls would just spend the Max plan quota faster."""
    win = types.SimpleNamespace()
    win._refs_backend = lambda: 'claude'
    workers = types.MethodType(MainWindow._refs_workers, win)

    assert workers() == 1


@pytest.mark.unit
@pytest.mark.parametrize('pref,expected', [
    (4, 4), (1, 1), ('3', 3),
    (0, 1), (-2, 1),        # clamped up
    (99, 8),                # clamped down
    ('nonsense', 4),        # unparseable falls back to the default
])
def test_worker_count_is_read_from_prefs_and_clamped(monkeypatch, pref, expected):
    import papermeister.preferences as prefs

    monkeypatch.setattr(prefs, 'get_pref',
                        lambda key, default=None: pref if key == 'refs_workers' else 'http://x')
    win = types.SimpleNamespace()
    win._refs_backend = lambda: 'qwen'
    workers = types.MethodType(MainWindow._refs_workers, win)

    assert workers() == expected
