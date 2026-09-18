"""The "Process Figures" action (P16 Phase 4b): where it shows, when it is
disabled, and what its window says while a paper runs — including the
server worker being paused, which has to read as waiting, not as a hang."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QTreeWidgetItem


def _menu_actions(monkeypatch, module):
    """Capture the context menu instead of popping it up."""
    captured = {}

    def fake_exec(self, *_a, **_k):
        captured['actions'] = [(a.text(), a.isEnabled(), a.toolTip()) for a in self.actions() if not a.isSeparator()]

    monkeypatch.setattr(module.QMenu, 'exec', fake_exec)
    return captured


@pytest.fixture
def paper_list(qapp, monkeypatch):
    from desktop.views import paper_list as mod
    monkeypatch.setattr('papermeister.preferences.get_pref', lambda k, d=None: d)
    widget = mod.PaperListView()
    item = QTreeWidgetItem(['processed', 'A paper', '2004'])
    item.setData(0, Qt.ItemDataRole.UserRole, 7)
    item.setData(0, Qt.ItemDataRole.UserRole + 2, 70)
    widget.addTopLevelItem(item)
    return widget, item, mod


def _event_at(widget, item):
    rect = widget.visualItemRect(item)
    return SimpleNamespace(pos=lambda: rect.center(), globalPos=lambda: QPoint(0, 0))


@pytest.mark.ui
def test_process_figures_is_offered_for_a_processed_paper(paper_list, monkeypatch):
    widget, item, mod = paper_list
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: '')
    captured = _menu_actions(monkeypatch, mod)
    widget.contextMenuEvent(_event_at(widget, item))
    figs = [a for a in captured['actions'] if a[0] == 'Process Figures']
    assert figs and figs[0][1] is True


@pytest.mark.ui
def test_process_figures_is_disabled_with_the_reason_when_there_is_no_server(paper_list, monkeypatch):
    widget, item, mod = paper_list
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: 'needs the wrapper server')
    captured = _menu_actions(monkeypatch, mod)
    widget.contextMenuEvent(_event_at(widget, item))
    figs = [a for a in captured['actions'] if a[0] == 'Process Figures']
    assert figs and figs[0][1] is False and 'wrapper' in figs[0][2]


@pytest.mark.ui
def test_pending_paper_has_no_figures_action(paper_list, monkeypatch):
    widget, item, mod = paper_list
    item.setText(0, 'pending')
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: '')
    captured = _menu_actions(monkeypatch, mod)
    widget.contextMenuEvent(_event_at(widget, item))
    assert all(a[0] != 'Process Figures' for a in captured['actions'])


@pytest.mark.ui
def test_the_figures_window_reads_a_paused_worker_as_waiting(qapp):
    from desktop.windows.figures_window import FiguresWindow
    w = FiguresWindow()
    w.begin(2)
    w.set_current('Lee 2004')
    w.note('info', 'link…')
    w.note('wait', 'server worker paused: login — waiting')
    assert w.current_label.text().startswith('Waiting')
    assert 'paused' in w.log.toPlainText()
    w.note('info', 'link: 1/3 done, worker running')
    assert w.current_label.text().startswith('Processing')
    w.record('Lee 2004', True, 'link 3/3, panels 2/2')
    w.record('Kim 1999', False, 'server: boom')
    assert w.progress_bar.value() == 2 and '1 done, 1 failed' in w.summary_label.text()
    w.finish()
    assert w.current_label.text() == 'Done' and not w.cancel_btn.isEnabled()


@pytest.mark.ui
def test_cancel_drops_the_queue_and_says_so(qapp):
    from desktop.windows.figures_window import FiguresWindow
    w = FiguresWindow()
    fired = []
    w.cancel_requested.connect(lambda: fired.append(True))
    w.begin(5)
    w.cancel_btn.click()
    assert fired
    w.mark_cancelling(4)
    w.finish()
    assert '4 paper(s) dropped' in w.log.toPlainText() and w.current_label.text() == 'Cancelled'
