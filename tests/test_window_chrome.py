"""The frameless main window's own chrome: edge detection for resizing,
the title bar's double-click, the buttons' state."""
import pytest
from PyQt6.QtCore import QPoint, Qt


@pytest.mark.ui
def test_edges_and_their_cursors(qapp):
    from PyQt6.QtWidgets import QMainWindow

    from desktop.components import window_chrome as wc

    class Host(wc.EdgeResizer, QMainWindow):
        pass

    w = Host()
    w.resize(400, 300)
    E = wc.EDGE
    assert w.edges_at(QPoint(2, 150)) == Qt.Edge.LeftEdge
    assert w.edges_at(QPoint(399, 150)) == Qt.Edge.RightEdge
    assert w.edges_at(QPoint(200, 1)) == Qt.Edge.TopEdge
    assert w.edges_at(QPoint(200, 299)) == Qt.Edge.BottomEdge
    assert w.edges_at(QPoint(1, 1)) == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
    assert w.edges_at(QPoint(399, 299)) == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
    assert w.edges_at(QPoint(E + 1, E + 1)) == Qt.Edge(0)
    assert wc.EdgeResizer.cursor_for(Qt.Edge.LeftEdge) == Qt.CursorShape.SizeHorCursor
    assert wc.EdgeResizer.cursor_for(Qt.Edge.TopEdge) == Qt.CursorShape.SizeVerCursor
    assert wc.EdgeResizer.cursor_for(Qt.Edge.LeftEdge | Qt.Edge.TopEdge) == Qt.CursorShape.SizeFDiagCursor
    assert wc.EdgeResizer.cursor_for(Qt.Edge.RightEdge | Qt.Edge.TopEdge) == Qt.CursorShape.SizeBDiagCursor
    assert wc.EdgeResizer.cursor_for(Qt.Edge(0)) == Qt.CursorShape.ArrowCursor
    w.showMaximized()
    assert w.edges_at(QPoint(1, 1)) == Qt.Edge(0)        # nothing to resize when maximized
    assert wc.chrome_margins(True) == (E, E, E, E) and wc.chrome_margins(False) == (0, 0, 0, 0)


@pytest.mark.ui
def test_the_buttons_follow_the_window_state_and_the_bar_double_clicks(qapp):
    from PyQt6.QtWidgets import QMainWindow

    from desktop.components import window_chrome as wc
    w = QMainWindow()
    buttons = wc.WindowButtons(w)
    assert buttons.maximize.toolTip() == 'Maximize'
    w.showMaximized()
    buttons.refresh()
    assert buttons.maximize.toolTip() == 'Restore'
    buttons.toggle_maximize()
    assert not w.isMaximized() and buttons.maximize.toolTip() == 'Maximize'
    bar = wc.TitleBar()
    fired = []
    bar.double_clicked.connect(lambda: fired.append(True))

    class Ev:
        def button(self):
            return Qt.MouseButton.LeftButton

        def accept(self):
            pass
    bar.mouseDoubleClickEvent(Ev())
    assert fired == [True]


@pytest.mark.ui
def test_the_main_window_is_frameless_unless_the_preference_says_otherwise(qapp, monkeypatch):
    monkeypatch.setattr('papermeister.preferences.get_pref', lambda k, d=None: d)
    from desktop.windows import main_window as mw
    monkeypatch.setattr(mw.MainWindow, '_load_initial', lambda self: None)
    monkeypatch.setattr(mw.MainWindow, '_sync_zotero', lambda self: None)
    w = mw.MainWindow()
    assert w._frameless and bool(w.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert w.findChild(mw.WindowButtons) is not None
    assert w.findChild(mw.VersionLabel).text().startswith('v')
    w.detail_panel.dispose()
    monkeypatch.setattr('papermeister.preferences.get_pref', lambda k, d=None: True if k == 'native_title_bar' else d)
    w2 = mw.MainWindow()
    assert not w2._frameless and not (w2.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert w2.findChild(mw.WindowButtons) is None
    w2.detail_panel.dispose()
