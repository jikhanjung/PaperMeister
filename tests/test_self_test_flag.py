"""The --self-test flag is what CI uses to prove a frozen build actually runs.

If it silently stopped working, the smoke step in reusable_build.yml would keep
passing while testing nothing — the same failure mode as a gate that installs no
dependencies. So pin the two halves: the flag is recognised only when asked for,
and arming it schedules an exit rather than leaving the app running forever.
"""
import sys

import pytest

from desktop import app as desktop_app


@pytest.mark.unit
def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['PaperMeister'])
    assert desktop_app._self_test_requested() is False


@pytest.mark.unit
def test_flag_is_recognised(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['PaperMeister', '--self-test'])
    assert desktop_app._self_test_requested() is True


@pytest.mark.unit
def test_qt_arguments_do_not_trigger_it(monkeypatch):
    """Qt consumes its own switches from argv; none of them mean self-test.
    Hand-parsing (rather than argparse) is what keeps these from erroring out."""
    monkeypatch.setattr(sys, 'argv',
                        ['PaperMeister', '-platform', 'offscreen', '-style', 'Fusion'])
    assert desktop_app._self_test_requested() is False


@pytest.mark.ui
def test_arming_schedules_an_exit(qapp, monkeypatch):
    """The timer is the whole mechanism — without it the CI step would hang
    until the job timeout instead of reporting a result."""
    scheduled = {}

    class FakeTimer:
        @staticmethod
        def singleShot(ms, fn):
            scheduled['ms'] = ms
            scheduled['fn'] = fn

    import PyQt6.QtCore
    monkeypatch.setattr(PyQt6.QtCore, 'QTimer', FakeTimer)

    quit_called = []
    monkeypatch.setattr(qapp, 'quit', lambda: quit_called.append(True))

    desktop_app._arm_self_test(qapp)

    assert scheduled['ms'] > 0, 'must let the event loop spin before quitting'
    scheduled['fn']()                      # fire the timer
    assert quit_called == [True]
