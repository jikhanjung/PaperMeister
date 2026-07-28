"""ServerGuard state machine (server-down pause/resume for batch queues)."""
import logging

import pytest


def _make_guard(qapp, health, remaining, events):
    from desktop.workers.server_guard import ServerGuard
    return ServerGuard(
        health_check=health,
        on_pause=lambda r: events.append(("pause", r)),
        on_resume=lambda r: events.append(("resume", r)),
        on_drain=lambda: events.append(("drain",)),
        remaining=remaining,
        fail_stop=3,
    )


@pytest.mark.ui
def test_pauses_after_threshold_when_server_down(qapp):
    events = []
    guard = _make_guard(qapp, lambda: False, lambda: 5, events)
    assert guard.record_fail() is False and not guard.paused()   # streak 1
    assert guard.record_fail() is False and not guard.paused()   # streak 2
    assert guard.record_fail() is True and guard.paused()        # streak 3 → pause
    assert events[-1] == ("pause", 5)
    assert guard.record_fail() is False                          # already paused → no-op


@pytest.mark.ui
def test_transient_blip_does_not_pause(qapp):
    events = []
    guard = _make_guard(qapp, lambda: True, lambda: 3, events)   # server answers
    guard.record_fail()
    guard.record_fail()
    guard.record_fail()
    assert not guard.paused()
    assert ("pause", 3) not in events


@pytest.mark.ui
def test_resume_drains_when_server_back(qapp):
    events = []
    guard = _make_guard(qapp, lambda: False, lambda: 5, events)
    guard.record_fail()
    guard.record_fail()
    guard.record_fail()
    assert guard.paused()
    guard._on_poll_result(True)   # simulate the recovery ping answering
    assert not guard.paused()
    assert ("resume", 5) in events
    assert ("drain",) in events


@pytest.mark.ui
def test_record_ok_resets_streak(qapp):
    events = []
    guard = _make_guard(qapp, lambda: False, lambda: 5, events)
    guard.record_fail()
    guard.record_fail()
    guard.record_ok()
    assert guard.record_fail() is False and not guard.paused()   # streak restarted


@pytest.mark.ui
def test_cancel_clears_paused(qapp):
    events = []
    guard = _make_guard(qapp, lambda: False, lambda: 5, events)
    guard.record_fail()
    guard.record_fail()
    guard.record_fail()
    assert guard.paused()
    guard.cancel()
    assert not guard.paused()


@pytest.mark.ui
def test_pause_and_resume_are_logged(qapp, caplog):
    """An unattended overnight batch has to leave a record of why it stopped.
    The guard only spoke to the UI before, so a morning log showed failures
    ending and restarting with nothing explaining the gap.
    """
    from desktop.workers.server_guard import ServerGuard

    alive = [False]
    guard = ServerGuard(
        health_check=lambda: alive[0],
        on_pause=lambda n: None,
        on_resume=lambda n: None,
        on_drain=lambda: None,
        remaining=lambda: 7,
        fail_stop=2,
    )
    with caplog.at_level(logging.WARNING, logger='biblio'):
        guard.record_fail()
        assert guard.record_fail() is True          # crosses the threshold
        assert guard.paused()
        alive[0] = True
        guard._on_poll_result(True)                 # the recovery ping lands

    text = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'PAUSING' in text and '7 item(s)' in text
    assert 'RESUMING' in text


@pytest.mark.unit
def test_duration_is_readable():
    from desktop.workers.server_guard import _duration
    assert _duration(45) == '45s'
    assert _duration(125) == '2m 5s'
    assert _duration(7325) == '2h 2m'
