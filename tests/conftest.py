"""Shared pytest fixtures.

Runs Qt headless so UI-touching tests work in CI / over SSH.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for tests that construct QObjects/QTimers."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _keep_papermeister_modules():
    """Some tests re-import `papermeister.*` to re-resolve paths (config
    location, data dir). Left in place, the fresh modules carry a fresh
    peewee proxy, and everything imported earlier — the desktop services —
    still holds the old model classes bound to the old, now uninitialized
    proxy: "Cannot use uninitialized Proxy" in whichever DB-touching UI test
    runs later. Put the original modules back after each test."""
    saved = {k: v for k, v in sys.modules.items() if k.startswith('papermeister')}
    yield
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module
    # `from papermeister import x` reads the package attribute. The re-import
    # pointed it at the fresh module — or, when the package itself was
    # re-imported, set it only on the fresh package. Make every submodule
    # in sys.modules reachable as an attribute of its (restored) parent.
    for name in [m for m in sys.modules if m.startswith('papermeister.')]:
        parent, _, child = name.rpartition('.')
        if parent in sys.modules:
            setattr(sys.modules[parent], child, sys.modules[name])
