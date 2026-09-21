"""The Figures tab: a paper by its figures, boxes tied to entries by the
cursor, crops rendered only near the viewport and let go far from it."""
import json
import os
import tempfile
import time

import pytest
from PIL import Image


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-figtab-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def paper(db):
    """Twelve figures: the first split into two panels with entries, the
    second with entries only, the rest bare — enough to scroll."""
    from papermeister.models import Figure, FigureEntry, FigurePanel, Paper, PaperFile
    p = Paper.create(title='Plates')
    pf = PaperFile.create(paper=p, path='x.pdf', hash='ab' * 32, status='processed')
    ids = []
    for i in range(12):
        f = Figure.create(paper=p, paper_file=pf, file_hash=pf.hash, page=i, name=f'Plate {i + 1}',
                          bbox_page_1000=json.dumps([100, 100, 900, 900]), blocks_json='[]',
                          caption=f'PLATE {i + 1}.' if i < 3 else '')
        ids.append(f.id)
    FigureEntry.create(figure=ids[0], order=0, label='1', description='Cranidium', specimen_number='S1')
    FigureEntry.create(figure=ids[0], order=1, label='2', description='Pygidium')
    FigureEntry.create(figure=ids[0], order=2, label='3', description='Hypostome')
    FigurePanel.create(figure=ids[0], order=0, label='1', bbox_figure_1000=json.dumps([0, 0, 500, 500]),
                       entry_orders_json='[0]')
    FigurePanel.create(figure=ids[0], order=1, label='2', bbox_figure_1000=json.dumps([500, 0, 1000, 500]),
                       entry_orders_json='[1]')
    FigureEntry.create(figure=ids[1], order=0, label='a', description='Dorsal view')
    return p.id, ids


@pytest.fixture
def white_pdf(monkeypatch):
    from papermeister import pdfdoc
    rendered = []

    def render_page(path, page_idx, dpi=150):
        rendered.append(page_idx)
        return Image.new('RGB', (round(595 * dpi / 72), round(842 * dpi / 72)), 'white')

    monkeypatch.setattr(pdfdoc, 'page_sizes', lambda path, indices=None: [(595.0, 842.0) for _ in (indices or [0])])
    monkeypatch.setattr(pdfdoc, 'render_page', render_page)
    return rendered


def _settle(qapp, done, seconds=8):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        if done():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.ui
def test_blocks_carry_boxes_entries_or_caption_and_the_cursor_ties_them(qapp, paper, white_pdf):
    from desktop.views.figures_tab import FiguresTab
    paper_id, ids = paper
    tab = FiguresTab()
    tab.resize(900, 700)
    tab.show()
    assert tab.set_paper(paper_id, 'x.pdf') == 12
    split, plain, bare = tab._blocks[ids[0]], tab._blocks[ids[1]], tab._blocks[ids[5]]
    assert split.entries.count() == 3 and 'no panel for 3' in split._title()
    assert [split.entries.item(i).text().split('  ')[0] for i in range(3)] == ['1', '2', '3']
    assert plain.entries.count() == 1 and plain.panel_set is None
    assert bare.entries.count() == 0
    # the caption two ways where there are entries and a caption; one way otherwise
    assert [split.caption_tabs.tabText(i) for i in range(2)] == ['Entries (3)', 'Caption']
    assert split.caption_tabs.widget(1).text() == 'PLATE 1.'
    assert plain.caption_tabs is not None and bare.caption_tabs is None
    # the first block's crop arrives with its two boxes
    assert _settle(qapp, lambda: split.canvas._image is not None)
    assert len(split.canvas._boxes) == 2 and split.canvas._boxes[1][1] == '2'
    # hover a box → its entry fills; hover an entry → its box lights
    split.canvas.panel_hovered.emit(1)
    assert split.entries._hovered == 1
    split.entries.row_hovered.emit(0)
    assert split.canvas._hover == 0
    split.entries.row_hovered.emit(-1)
    assert split.canvas._hover is None
    # the unmatched entry (row 2) lights nothing; a click keeps the pairing
    split.entries.setCurrentRow(2)
    assert split.canvas.lit() is None
    split.canvas.panel_clicked.emit(1)
    assert split.entries.currentRow() == 1 and split.canvas.lit() == 1
    tab._stop_worker()


@pytest.mark.ui
def test_only_blocks_near_the_viewport_are_rendered_and_far_ones_are_let_go(qapp, paper, white_pdf):
    from desktop.views import figures_tab as mod
    paper_id, ids = paper
    tab = mod.FiguresTab()
    tab.resize(900, 600)
    tab.show()
    tab.set_paper(paper_id, 'x.pdf')
    qapp.processEvents()
    tab._render_visible()
    requested = [f for f in ids if tab._blocks[f].requested]
    assert 0 < len(requested) < 12, requested          # the top of the paper, not all of it
    assert _settle(qapp, lambda: all(tab._blocks[f].canvas._image is not None for f in requested))
    assert sorted(white_pdf) == sorted(ids.index(f) for f in requested)
    # scroll to the bottom: the top crops are released, the bottom ones rendered
    tab.verticalScrollBar().setValue(tab.verticalScrollBar().maximum())
    tab._render_visible()
    assert tab._blocks[ids[-1]].requested
    assert _settle(qapp, lambda: tab._blocks[ids[-1]].canvas._image is not None)
    tab._render_visible()
    assert tab._blocks[ids[0]].canvas._image is None and not tab._blocks[ids[0]].requested
    assert len(tab._live) <= mod.MAX_LIVE
    tab._stop_worker()


@pytest.mark.ui
def test_a_paper_without_figures_says_so(qapp, db):
    from desktop.views.figures_tab import FiguresTab
    from papermeister.models import Paper
    p = Paper.create(title='t')
    tab = FiguresTab()
    assert tab.set_paper(p.id, None) == 0
    assert tab._worker is None


@pytest.mark.ui
def test_the_detail_panel_has_a_figures_tab_before_references(qapp, monkeypatch, paper):
    from desktop.views.detail_panel import DetailPanel
    paper_id, _ = paper
    panel = DetailPanel()
    panel.show_paper(paper_id)
    names = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
    assert names == ['Metadata', 'PDF', 'Text', 'Figures', 'References']
    built = []
    monkeypatch.setattr(panel, '_build_figures_tab', lambda d: built.append(d.paper_id) or __import__('PyQt6.QtWidgets').QtWidgets.QWidget())
    panel._tabs.setCurrentIndex(3)
    assert built == [paper_id] and panel._figures_built
