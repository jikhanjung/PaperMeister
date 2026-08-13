"""Identity and licensing facts, in one place and free of Qt.

Kept out of the dialog that displays it so the CLI and the tests can read the
same values, and so the third-party table can be checked against what is
actually installed (`tests/test_about.py`) rather than drifting quietly.

On the licence: PaperMeister links PyQt6 (GPL-3.0) and PyMuPDF (AGPL-3.0), and
the released installers bundle both. The strongest of those terms governs the
combined work we distribute, so the application is distributed under the
AGPL-3.0. See devlog/20260813_R03_License_Audit.md for how that was arrived at
and what it would take to move off it.
"""
from version import __version__

APP_NAME = 'PaperMeister'
APP_DESCRIPTION = 'Turns a PDF library into a searchable knowledge base.'
APP_URL = 'https://github.com/jikhanjung/PaperMeister'
APP_LICENSE = 'AGPL-3.0-or-later'
APP_COPYRIGHT = '© 2026 Jikhan Jung'
APP_VERSION = __version__

#: Runtime dependencies: (distribution, licence to display, pattern that must
#: still appear in what that distribution declares about itself).
#:
#: The pattern is here rather than in the test because it is part of the claim:
#: it records *what evidence* the displayed licence rests on. Upstreams reword
#: these constantly — "MIT" vs "MIT License" vs an SPDX expression, and PyMuPDF
#: writes "GNU AFFERO GPL 3.0" rather than "AGPL" — so matching the whole string
#: would fail for reasons that have nothing to do with licensing. Some packages
#: (peewee) declare nothing in metadata at all, and the evidence is the bundled
#: licence file instead; `tests/test_about.py` looks in both.
THIRD_PARTY = [
    ('PyQt6',        'GPL-3.0-only',                   r'gpl-3\.0|general public license'),
    ('PyMuPDF',      'AGPL-3.0 or Artifex commercial', r'affero|agpl'),
    ('Pillow',       'MIT-CMU',                        r'mit'),
    ('requests',     'Apache-2.0',                     r'apache'),
    ('peewee',       'MIT',                            r'mit|permission is hereby granted'),
    ('pyzotero',     'Blue Oak Model License 1.0.0',   r'blueoak|blue oak'),
    ('platformdirs', 'MIT',                            r'mit'),
]

#: Named so the About tab can explain why the app is AGPL rather than just
#: assert it — the two entries here are the reason.
COPYLEFT_COMPONENTS = ('PyQt6', 'PyMuPDF')


def license_summary() -> str:
    """One paragraph a user can act on, not just a licence name."""
    return (
        f'{APP_NAME} is distributed under the {APP_LICENSE}. The released '
        f'builds bundle PyQt6 (GPL-3.0) and PyMuPDF (AGPL-3.0), whose terms '
        f'cover the application as a whole. You may use, study, modify and '
        f'redistribute it under those terms; the complete source is at '
        f'{APP_URL}.'
    )
