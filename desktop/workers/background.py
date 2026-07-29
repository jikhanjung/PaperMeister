"""Thin QThread wrapper for off-main-thread service calls.

All DB writes go through here so the UI thread never blocks.
"""
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal


class BackgroundTask(QThread):
    """Run a callable on a worker thread, emit result/error on finish."""

    done = pyqtSignal(object)      # payload
    failed = pyqtSignal(str)       # error message
    #: Optional (done, total) for work that reports sub-steps. The callable has
    #: to emit it itself — nothing here calls it — which keeps the cross-thread
    #: hop a queued signal rather than a direct call into a widget.
    progress = pyqtSignal(int, int)
    #: Optional (kind, message) for something worth showing mid-task that is
    #: neither progress nor the outcome — e.g. the LLM server went away and the
    #: task is waiting it out. Emitted by the callable, same as `progress`.
    notice = pyqtSignal(str, str)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f'{type(exc).__name__}: {exc}')
            return
        self.done.emit(result)
