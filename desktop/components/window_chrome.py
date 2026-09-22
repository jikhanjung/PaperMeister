"""The window's own chrome, for a frameless main window.

The OS title bar duplicated what the top bar already says (the app's name)
and cost a strip of the screen, so the main window is frameless and the top
bar is the title bar: it drags the window (`startSystemMove`), a double
click maximizes, and it carries the minimize / maximize / close buttons. A
frameless window also loses the OS resize borders; `EdgeResizer` gives them
back — a few transparent pixels around the content where the cursor turns
into a resize arrow and a press starts `startSystemResize`.

Both go through the platform's own move/resize, so snapping and the taskbar
keep working. `native_title_bar` in preferences turns all of this off and
gives the OS frame back.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

#: How wide the invisible resize border around the content is.
EDGE = 6


class WindowButtons(QWidget):
    """Minimize · maximize/restore · close, drawn as flat glyph buttons."""

    def __init__(self, window: QWidget, parent=None):
        super().__init__(parent)
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.minimize = self._button('–', 'Minimize', window.showMinimized)
        self.maximize = self._button('☐', 'Maximize', self.toggle_maximize)
        self.close = self._button('✕', 'Close', window.close)
        self.close.setObjectName('WindowClose')
        for b in (self.minimize, self.maximize, self.close):
            layout.addWidget(b)

    def _button(self, glyph: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setObjectName('WindowButton')
        b.setText(glyph)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setFixedSize(44, 32)
        b.setCursor(Qt.CursorShape.ArrowCursor)
        b.clicked.connect(slot)
        return b

    def toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.refresh()

    def refresh(self):
        maximized = self._window.isMaximized()
        self.maximize.setText('❐' if maximized else '☐')
        self.maximize.setToolTip('Restore' if maximized else 'Maximize')


class TitleBar(QWidget):
    """The top bar as a title bar: drag to move, double-click to maximize.

    The bar's own children (the search box, the buttons) take their clicks
    first; only a press on the bar itself, or on a plain label in it, moves
    the window.
    """

    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('TopBar')
        # A QWidget subclass paints its stylesheet background (and the
        # bottom border) only with this attribute; a plain QWidget did it
        # by itself, which is why the bar went flat when it became a class.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and not self.window().isMaximized():
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class VersionLabel(QLabel):
    def __init__(self, version: str, parent=None):
        super().__init__(f'v{version}', parent)
        self.setObjectName('AppVersion')
        self.setToolTip(f'PaperMeister {version}')


class EdgeResizer:
    """Mixin for a frameless top-level widget: resize by its edges.

    The host keeps `EDGE` pixels of empty margin around its content (so a
    press there reaches the host, not a child), enables mouse tracking, and
    forwards `mouseMoveEvent` / `mousePressEvent` / `leaveEvent` here.
    """

    def edges_at(self, pos: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if self.isMaximized():
            return edges
        w, h = self.width(), self.height()
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= w - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= h - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            tl = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
            return Qt.CursorShape.SizeFDiagCursor if tl else Qt.CursorShape.SizeBDiagCursor
        if horizontal:
            return Qt.CursorShape.SizeHorCursor
        if vertical:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def edge_move(self, event) -> None:
        self.setCursor(self.cursor_for(self.edges_at(event.position().toPoint())))

    def edge_press(self, event) -> bool:
        """Start a system resize when the press is on an edge. True if it did."""
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        edges = self.edges_at(event.position().toPoint())
        handle = self.windowHandle()
        if edges and handle is not None:
            handle.startSystemResize(edges)
            return True
        return False

    def edge_leave(self) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)


def chrome_margins(frameless: bool) -> tuple[int, int, int, int]:
    """The host's content margins: the resize border when frameless, none otherwise."""
    return (EDGE, EDGE, EDGE, EDGE) if frameless else (0, 0, 0, 0)


__all__ = ['EDGE', 'EdgeResizer', 'TitleBar', 'VersionLabel', 'WindowButtons', 'chrome_margins']
