"""Leftmost rail with icon toggle buttons."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget


class Rail(QWidget):
    """Vertical icon rail. Emits `section_changed(str)` on selection."""

    section_changed = pyqtSignal(str)

    SECTIONS = [
        ('library', '📚', 'Library'),
        ('search',  '🔍', 'Search'),
        ('process', '⚙', 'Process'),
        ('settings','⋯',  'Settings'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Rail')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for key, icon, tooltip in self.SECTIONS:
            btn = QToolButton(self)
            btn.setText(icon)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(36, 36)
            btn.clicked.connect(lambda _=False, k=key: self.section_changed.emit(k))
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Default selection
        first = self._group.buttons()[0]
        first.setChecked(True)
