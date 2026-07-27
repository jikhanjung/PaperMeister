"""Sphinx configuration for the PaperMeister manual.

Built by .github/workflows/docs.yml into English and Korean and published to
GitHub Pages. `make html` here for a local preview.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

# -- Project information -----------------------------------------------------

project = "PaperMeister"
# `copyright` is the name Sphinx requires for this setting, so the shadowing
# is not ours to rename.
copyright = "2026, Jikhan Jung"  # noqa: A001
author = "Jikhan Jung"

# Single-sourced from version.py, the same file tests/test_version_consistency.py
# pins — so the rendered docs can never disagree with the shipped version.
from version import __version__  # noqa: E402

release = __version__
version = ".".join(__version__.split(".")[:2])

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    # Used only by changelog.rst, to include the repository-root CHANGELOG.md
    # instead of maintaining a second copy of the release notes here.
    "myst_parser",
]

templates_path = ["_templates"]
# myst_parser makes Sphinx treat .md here as documents too, so this directory's
# own README has to be excluded explicitly.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "README.md"]

# Internationalization
locale_dirs = ["locale/"]
gettext_compact = False
language = "en"

napoleon_google_docstring = True
napoleon_numpy_docstring = True

# -- HTML output -------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

html_context = {
    "display_github": True,
    "github_user": "jikhanjung",
    "github_repo": "PaperMeister",
    "github_version": "main",
    "conf_py_path": "/docs/manual/",
}

html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

todo_include_todos = True
