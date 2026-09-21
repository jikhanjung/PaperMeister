"""The figure canvas: boxes tied to entries by click and hover, a tooltip on
a box, and the panel data the Figures tab reads."""
import os
import tempfile

import pytest
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QImage


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-canvas-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


class Ev:
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def position(self):
        return self._p

    def globalPosition(self):
        return self._p


def _canvas_with_two_boxes(tips=None):
    from desktop.components.figure_canvas import FigureCanvas
    canvas = FigureCanvas()
    image = QImage(400, 400, QImage.Format.Format_RGB888)
    image.fill(0xffffff)
    canvas.set_figure(image, [(QRectF(0, 0, 400, 400), 'all', '#7b93ad'),
                              (QRectF(100, 100, 50, 50), '2', '#7b93ad')], 1.0, tips=tips)
    target = canvas._drawn_rect()
    return canvas, target, target.width() / 400


@pytest.mark.ui
def test_a_click_finds_the_smallest_box_under_it(qapp):
    canvas, target, sx = _canvas_with_two_boxes()
    hits = []
    canvas.panel_clicked.connect(hits.append)
    canvas.mousePressEvent(Ev(target.x() + 120 * sx, target.y() + 120 * sx))
    canvas.mousePressEvent(Ev(target.x() + 300 * sx, target.y() + 300 * sx))
    assert hits == [1, 0]


@pytest.mark.ui
def test_hover_lights_a_box_reports_it_and_shows_its_entry_as_a_tooltip(qapp, monkeypatch):
    from desktop.components import figure_canvas as mod
    shown = []
    monkeypatch.setattr(mod.QToolTip, 'showText', lambda pos, text, w=None: shown.append(text))
    monkeypatch.setattr(mod.QToolTip, 'hideText', lambda: shown.append(None))
    canvas, target, sx = _canvas_with_two_boxes(tips=['', '2 — Pygidium (S2)'])
    hovered = []
    canvas.panel_hovered.connect(hovered.append)
    canvas.mouseMoveEvent(Ev(target.x() + 120 * sx, target.y() + 120 * sx))    # the small box
    assert canvas._hover == 1 and hovered == [1] and shown == ['2 — Pygidium (S2)']
    canvas.mouseMoveEvent(Ev(target.x() + 300 * sx, target.y() + 300 * sx))    # the big one, no tip text
    assert canvas._hover == 0 and hovered == [1, 0] and shown[-1] is None
    canvas.leaveEvent(None)
    assert canvas._hover is None and hovered[-1] == -1
    # a click is kept; hover overrides it only while the cursor is there
    canvas.light(1)
    canvas.hover(0)
    assert canvas.lit() == 1 and canvas._hover == 0


@pytest.mark.unit
def test_entry_text_names_specimen_confidence_and_annotation():
    from desktop.components.figure_canvas import entry_text
    from desktop.services.paper_service import PanelInfo
    p = PanelInfo(label='1', bbox_page_1000=[0, 0, 1, 1], entries=[('1', 'Cranidium, dorsal view', 'S1')])
    assert entry_text(p) == '1 — Cranidium, dorsal view (S1)'
    p.confidence = 'medium'
    assert entry_text(p).startswith('Confidence: medium.\n1 — ')
    assert entry_text(PanelInfo(label='sb', bbox_page_1000=[0, 0, 1, 1], entries=[], annotation=True)).startswith('Annotation')
    assert entry_text(PanelInfo(label='9', bbox_page_1000=[0, 0, 1, 1], entries=[])) == 'No caption entry matched.'


@pytest.mark.unit
def test_load_panels_maps_boxes_to_the_page_and_names_unmatched_entries(db):
    import json

    from desktop.services.paper_service import load_entries, load_panels
    from papermeister.models import Figure, FigureEntry, FigurePanel, Paper, PaperFile
    paper = Paper.create(title='t')
    pf = PaperFile.create(paper=paper, path='x.pdf', hash='ab' * 32, status='processed')
    fig = Figure.create(paper=paper, paper_file=pf, file_hash=pf.hash, page=3, name='Plate I',
                        bbox_page_1000=json.dumps([100, 200, 900, 800]), blocks_json='[]')
    FigureEntry.create(figure=fig, order=0, label='1', description='Cranidium', specimen_number='S1')
    FigureEntry.create(figure=fig, order=1, label='2', description='Pygidium')
    FigurePanel.create(figure=fig, order=0, label='1', bbox_figure_1000=json.dumps([0, 0, 500, 500]),
                       entry_orders_json='[0]')
    ps = load_panels(fig.id)
    assert ps.panels[0].bbox_page_1000 == [100, 200, 500, 500]          # figure frame → page frame
    assert ps.panels[0].entries == [('1', 'Cranidium', 'S1')] and ps.unmatched == ['2']
    assert load_panels(999) is None
    assert load_entries(fig.id) == ('Plate I', [('1', 'Cranidium', 'S1'), ('2', 'Pygidium', '')])
