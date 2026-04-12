"""Leftmost rail with icon toggle buttons.

Two button groups:
- Top (modes):   Library, Search — exclusive checkable buttons. Emit
  `section_changed(key)` when the active mode changes.
- Bottom (actions): Sync, Process, Settings — one-shot action buttons that fire
  `action_triggered(key)` without altering the persistent mode.
"""
from PyQt6.QtCore import QPropertyAnimation, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QGraphicsOpacityEffect, QMenu, QToolButton, QVBoxLayout, QWidget

from desktop.theme.icons import rail_icon


class Rail(QWidget):
    section_changed = pyqtSignal(str)      # library | search
    action_triggered = pyqtSignal(str)     # process | settings | sync
    full_sync_triggered = pyqtSignal()     # right-click → "Full Sync"

    MODES = [
        ('library', 'library', 'Library'),
        ('search',  'search',  'Search'),
    ]
    ACTIONS = [
        ('sync',     'sync',     'Sync Zotero'),
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
        self._action_buttons: dict[str, QToolButton] = {}

        for key, icon_name, tooltip in self.MODES:
            btn = self._make_button(icon_name, tooltip, checkable=True)
            btn.clicked.connect(lambda _=False, k=key: self.section_changed.emit(k))
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        for key, icon_name, tooltip in self.ACTIONS:
            btn = self._make_button(icon_name, tooltip, checkable=False)
            btn.clicked.connect(lambda _=False, k=key: self.action_triggered.emit(k))
            self._action_buttons[key] = btn
            layout.addWidget(btn)

        # Default mode selection
        first = self._group.buttons()[0]
        first.setChecked(True)

        # Sync button: right-click context menu for "Full Sync".
        sync_btn = self._action_buttons.get('sync')
        if sync_btn:
            sync_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sync_btn.customContextMenuRequested.connect(self._show_sync_menu)

        # Sync pulse animation (opacity effect on the sync button).
        self._sync_anim: QPropertyAnimation | None = None

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

    def _show_sync_menu(self, pos):
        btn = self._action_buttons.get('sync')
        if btn is None:
            return
        menu = QMenu(self)
        menu.addAction('Full Sync (re-fetch all items)', self.full_sync_triggered.emit)
        menu.exec(btn.mapToGlobal(pos))

    # ── Sync animation ──────────────────────────────────────

    def set_sync_running(self, running: bool):
        """Pulse the sync button opacity while sync is in progress."""
        btn = self._action_buttons.get('sync')
        if btn is None:
            return

        if running:
            effect = QGraphicsOpacityEffect(btn)
            btn.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b'opacity')
            anim.setDuration(900)
            anim.setStartValue(1.0)
            anim.setEndValue(0.3)
            anim.setLoopCount(-1)  # infinite
            from PyQt6.QtCore import QEasingCurve
            anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._sync_anim = anim
            anim.start()
        else:
            if self._sync_anim is not None:
                self._sync_anim.stop()
                self._sync_anim = None
            btn.setGraphicsEffect(None)
