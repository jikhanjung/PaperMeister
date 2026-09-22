"""The search bar's shortcut is the platform's Find key, and says so."""
import sys

import pytest


@pytest.mark.ui
def test_the_placeholder_names_the_platform_find_key_and_the_key_focuses_the_bar(qapp):
    from PyQt6.QtGui import QKeySequence

    from desktop.components.search_bar import SearchBar, find_shortcut_label
    label = find_shortcut_label()
    assert label == ('⌘F' if sys.platform == 'darwin' else 'Ctrl+F')
    bar = SearchBar()
    assert label in bar.placeholderText() and '⌘' not in bar.placeholderText() or sys.platform == 'darwin'
    assert bar._shortcut.key() == QKeySequence(QKeySequence.StandardKey.Find)
    bar.setText('trilobite')
    bar.show()
    bar.focus_for_typing()
    assert bar.selectedText() == 'trilobite'
