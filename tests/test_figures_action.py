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
    figs = [a for a in captured['actions'] if a[0].startswith('Process Figures')]
    assert figs and figs[0][1] is True


@pytest.mark.ui
def test_process_figures_is_disabled_with_the_reason_when_there_is_no_server(paper_list, monkeypatch):
    widget, item, mod = paper_list
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: 'needs the wrapper server')
    captured = _menu_actions(monkeypatch, mod)
    widget.contextMenuEvent(_event_at(widget, item))
    figs = [a for a in captured['actions'] if a[0].startswith('Process Figures')]
    assert figs and figs[0][1] is False and 'wrapper' in figs[0][2]


@pytest.mark.ui
def test_pending_paper_has_no_figures_action(paper_list, monkeypatch):
    widget, item, mod = paper_list
    item.setText(0, 'pending')
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: '')
    captured = _menu_actions(monkeypatch, mod)
    widget.contextMenuEvent(_event_at(widget, item))
    assert all(not a[0].startswith('Process Figures') for a in captured['actions'])


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


@pytest.mark.ui
def test_the_menu_follows_the_stages(paper_list, monkeypatch):
    """Each stage offers what moves it on; the Figures label names what is next."""
    from desktop.services.paper_service import Stages
    from desktop.views.paper_list import ROLE_STAGES
    widget, item, mod = paper_list
    monkeypatch.setattr('papermeister.figure_pipeline.server_hint', lambda: '')

    def labels(stages):
        item.setData(0, ROLE_STAGES, stages)
        captured = _menu_actions(monkeypatch, mod)
        widget.contextMenuEvent(_event_at(widget, item))
        return [a[0] for a in captured['actions']]

    fresh = labels(Stages(ocr='done'))
    assert fresh[:3] == ['Extract Info', 'Extract References', 'Process Figures (assemble → captions → panels)']
    assert 'Open PDF' in fresh and 'Show in citation network' in fresh
    mid = labels(Stages(ocr='done', biblio='review', refs='partial', figs='linked'))
    assert mid[:3] == ['Review Info (Metadata tab)', 'Retry References', 'Process Figures (panels)']
    finished = labels(Stages(ocr='done', biblio='done', refs='done', figs='split'))
    assert finished[:3] == ['Re-extract Info', 'Re-extract References', 'Process Figures (re-check)']
    # before OCR, only OCR
    item.setText(0, 'failed')
    assert labels(Stages(ocr='failed')) == ['Retry OCR', 'Show in citation network']


@pytest.mark.ui
def test_the_status_cell_names_the_stage_to_run_next_and_lists_all_on_hover(qapp):
    from desktop.services.paper_service import Stages
    from desktop.views import paper_list as mod
    assert mod.badge_text(Stages(ocr='pending')) == 'OCR wait'
    assert mod.badge_text(Stages(ocr='failed')) == 'OCR err'
    assert mod.badge_text(Stages(ocr='done')) == 'INFO'                       # next to run
    assert mod.badge_text(Stages(ocr='done', biblio='review')) == 'INFO rev'
    assert mod.badge_text(Stages(ocr='done', biblio='done', refs='partial')) == 'REF part'
    assert mod.badge_text(Stages(ocr='done', biblio='done', refs='done', figs='linked')) == 'FIG cap'
    assert mod.badge_text(Stages(ocr='done', biblio='done', refs='done', figs='split')) == 'done'
    tip = mod.stages_tooltip_html(Stages(ocr='done', biblio='review', refs='none', figs='none',
                                         detail={'biblio': 'extracted, needs review'}))
    assert '✓ OCR' in tip and '· INFO' in tip and 'needs review' in tip and '· FIG' in tip
