"""Desktop app bootstrap — global exception hook."""
import sys

import pytest


@pytest.mark.ui
def test_excepthook_installed_and_safe(monkeypatch):
    from desktop.app import _install_excepthook

    orig = sys.excepthook
    try:
        _install_excepthook()
        assert sys.excepthook is not orig

        # Stub the dialog so the modal doesn't block the test run.
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

        # A real exception must be handled (logged) without re-raising.
        sys.excepthook(ValueError, ValueError("boom"), None)

        # KeyboardInterrupt delegates to the default hook (no dialog).
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        sys.excepthook = orig
