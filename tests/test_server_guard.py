"""ServerGuard state machine (server-down pause/resume for batch queues)."""
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
