"""Leftmost rail with icon toggle buttons.

Two button groups:
- Top (modes):   Library, Search — exclusive checkable buttons. Emit
  `section_changed(key)` when the active mode changes.
- Bottom (actions): Process, Settings — one-shot action buttons that fire
  `action_triggered(key)` without altering the persistent mode.
"""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from desktop.theme.icons import rail_icon


class Rail(QWidget):
    section_changed = pyqtSignal(str)   # library | search
    action_triggered = pyqtSignal(str)  # process | settings

    MODES = [
        ('library', 'library', 'Library'),
        ('search',  'search',  'Search'),
    ]
    ACTIONS = [
        ('process',  'process',  'Process'),
        ('settings', 'settings', 'Settings'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Rail')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for key, icon_name, tooltip in self.MODES:
            btn = self._make_button(icon_name, tooltip, checkable=True)
            btn.clicked.connect(lambda _=False, k=key: self.section_changed.emit(k))
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        for key, icon_name, tooltip in self.ACTIONS:
            btn = self._make_button(icon_name, tooltip, checkable=False)
            btn.clicked.connect(lambda _=False, k=key: self.action_triggered.emit(k))
            layout.addWidget(btn)

        # Default mode selection
        first = self._group.buttons()[0]
        first.setChecked(True)

    def _make_button(self, icon_name: str, tooltip: str, *, checkable: bool) -> QToolButton:
        btn = QToolButton(self)
        btn.setIcon(rail_icon(icon_name, size=26))
        btn.setIconSize(QSize(26, 26))
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        if checkable:
            btn.setAutoExclusive(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(44, 44)
        return btn
