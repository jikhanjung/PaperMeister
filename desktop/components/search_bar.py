"""Top search input. Phase 5 wires this to FTS5; for now it is a placeholder."""
from PyQt6.QtWidgets import QLineEdit


class SearchBar(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SearchBar')
        self.setPlaceholderText('Search papers, authors, full text…  (⌘F)')
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(32)
