"""Shared pytest fixtures.

Runs Qt headless so UI-touching tests work in CI / over SSH.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for tests that construct QObjects/QTimers."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
