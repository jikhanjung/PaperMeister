"""Import smoke: every module in the app must import cleanly.

Catches import-time breakage (version-only stdlib symbols, missing deps, syntax,
over-eager unused-import removal) as a single red test — the cheapest guard
against "works on my machine, crashes on the user's". Runs Qt headless
(offscreen set in conftest).
"""
import importlib
import pkgutil

import pytest


def _all_modules():
    names = []
    for pkg_name in ("papermeister", "desktop"):
        pkg = importlib.import_module(pkg_name)
        names.append(pkg_name)
        for info in pkgutil.walk_packages(pkg.__path__, pkg_name + "."):
            names.append(info.name)
    return names


@pytest.mark.parametrize("module", _all_modules())
def test_module_imports(module):
    importlib.import_module(module)
