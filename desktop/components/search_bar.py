"""Top search input, wired to FTS5 by the main window.

The placeholder names the shortcut that focuses it — the platform's own
Find key (Ctrl+F on Windows and Linux, ⌘F on macOS), which the bar binds
itself, application-wide.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QLineEdit


def find_shortcut_label() -> str:
    """The Find key as the platform writes it: 'Ctrl+F', or '⌘F' on macOS."""
    text = QKeySequence(QKeySequence.StandardKey.Find).toString(QKeySequence.SequenceFormat.NativeText)
    return text or 'Ctrl+F'


class SearchBar(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SearchBar')
        self.setPlaceholderText(f'Search papers, authors, full text…  ({find_shortcut_label()})')
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(32)
        # Application-wide, so it works from any panel; the bar takes focus
        # with its text selected, ready to be replaced.
        self._shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        self._shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut.activated.connect(self.focus_for_typing)

    def focus_for_typing(self):
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.selectAll()
