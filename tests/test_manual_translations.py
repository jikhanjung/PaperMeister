"""Translated manual strings are re-parsed as RST, not as their source markup.

Sphinx substitutes a `msgstr` and hands it to the reStructuredText inline
parser — even for `changelog.rst`, whose text comes from the Markdown
`CHANGELOG.md` via myst_parser. So Markdown habits that are correct in the
`msgid` are silently wrong in the `msgstr`:

* A single-backtick span is a *title reference* (italic `<cite>`), not code.
  Worse, it is not a literal, so backslashes are eaten (`%LOCALAPPDATA%\\PaleoBytes`
  rendered as `%LOCALAPPDATA%PaleoBytes`) and `--execute` became an en dash.
* RST has no nested inline markup, so a code span inside `**bold**` does not
  parse at all and the backticks show up as text.

Both failures render fine in English and only ever break the translation, where
they are least likely to be noticed. This test is the tripwire.

The PO parsing here is deliberately stdlib-only: polib ships with sphinx-intl,
which is a docs dependency, not a test one.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALE_DIR = ROOT / "docs" / "manual" / "locale"

# docutils allows an inline-markup end-string to be followed only by whitespace
# or one of these; anything else leaves the markup unterminated.
CLOSING_OK = set(" \t\n-.,:;!?\\/'\")]}>")

# A single-backtick span. The `_` suffix form is an RST hyperlink reference
# (`text <url>`_), which is legitimate and stays allowed.
SINGLE_SPAN = re.compile(r"(?<!`)`(?!`)([^`\n]+?)(?<!`)`(?!`)(_?)")
LITERAL_SPAN = re.compile(r"``(.+?)``", re.S)

# One pass, so an escaped backslash is never re-read as the start of an escape.
PO_ESCAPE = re.compile(r"\\(.)")
PO_UNESCAPE = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _msgstrs(path: Path):
    """Yield (line number, decoded msgstr) for each live entry in a .po file."""
    entries, lineno, parts, collecting = [], 0, [], False
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if line.startswith("#~"):  # obsolete entry — never rendered
            continue
        if line.startswith("msgstr"):
            collecting, lineno = True, i
            parts = [line[len("msgstr"):].strip()]
        elif collecting and line.startswith('"'):
            parts.append(line)
        elif collecting:
            entries.append((lineno, _decode(parts)))
            collecting = False
    if collecting:
        entries.append((lineno, _decode(parts)))
    return [(ln, s) for ln, s in entries if s]


def _decode(parts):
    body = "".join(p[1:-1] for p in parts if p.startswith('"') and p.endswith('"'))
    return PO_ESCAPE.sub(lambda m: PO_UNESCAPE.get(m.group(1), m.group(1)), body)


def _po_files():
    return sorted(LOCALE_DIR.rglob("*.po"))


@pytest.mark.unit
def test_locale_catalogs_exist():
    assert _po_files(), f"no .po catalogs under {LOCALE_DIR}"


@pytest.mark.unit
@pytest.mark.parametrize("po", _po_files(), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_no_single_backtick_spans_in_translations(po):
    """Single backticks render as italic <cite> and drop backslashes."""
    bad = [
        (ln, m.group(1))
        for ln, msgstr in _msgstrs(po)
        for m in SINGLE_SPAN.finditer(msgstr)
        if not m.group(2)  # `text <url>`_ is a hyperlink, not a title reference
    ]
    assert not bad, (
        f"{po.relative_to(ROOT)}: single-backtick span(s) in a translation — "
        f"use double backticks for code, since msgstr is parsed as RST: {bad}")


@pytest.mark.unit
@pytest.mark.parametrize("po", _po_files(), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_inline_literals_are_terminated(po):
    """``literal``( leaves the markup open and leaks backticks into the page.

    Korean hits this constantly because a postposition or a parenthesis follows
    the closing backticks with no space; the fix is an escaped space (``\\ ``).
    """
    bad = []
    for ln, msgstr in _msgstrs(po):
        for m in LITERAL_SPAN.finditer(msgstr):
            after = msgstr[m.end():m.end() + 1]
            if after and after not in CLOSING_OK:
                bad.append((ln, m.group(1), after))
    assert not bad, (
        f"{po.relative_to(ROOT)}: inline literal followed by {'/'.join(repr(b[2]) for b in bad)} — "
        f"RST needs whitespace or an escaped space (backslash-space) after ``: {bad}")
