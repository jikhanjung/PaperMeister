"""Thin QThread wrapper for off-main-thread service calls.

All DB writes go through here so the UI thread never blocks.
"""
from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class BackgroundTask(QThread):
    """Run a callable on a worker thread, emit result/error on finish."""

    done = pyqtSignal(object)   # payload
    failed = pyqtSignal(str)    # error message

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
