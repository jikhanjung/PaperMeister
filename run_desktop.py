"""Frozen / direct entry point for the PaperMeister desktop app.

Equivalent to `python -m desktop`, but as a top-level script so PyInstaller's
Analysis has an unambiguous entry with the repo root on sys.path (the
`from desktop.app import main` line then resolves cleanly).

`desktop.app` installs its SSL/requests patch at import time, so importing it
here is enough — no extra setup needed.
"""
import sys

from desktop.app import main

if __name__ == '__main__':
    sys.exit(main())
