"""P16 Phase 5, steps 2 and 3: a split figure's panels as tiles under the
figure list, and as boxes over the reader's figure images."""
import os
import tempfile
import time

import pytest
from PIL import Image
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QTextDocument

from desktop.services.paper_service import PanelInfo, PanelSet

_IMAGE = int(QTextDocument.ResourceType.ImageResource.value)


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-tiles-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def white_pdf(monkeypatch):
    """Renders a white page instantly; records what was asked."""
    from papermeister import pdfdoc
    rendered = []

    def render_page(path, page_idx, dpi=150):
        rendered.append((page_idx, dpi))
        return Image.new('RGB', (round(595 * dpi / 72), round(842 * dpi / 72)), 'white')

    monkeypatch.setattr(pdfdoc, 'page_sizes', lambda path, indices=None: [(595.0, 842.0) for _ in (indices or [0])])
    monkeypatch.setattr(pdfdoc, 'render_page', render_page)
    return rendered


def _panel_set(n=3, unmatched=()):
    return PanelSet(figure_id=7, name='Plate I', page=4, bbox_page_1000=[100, 100, 900, 900],
                    panels=[PanelInfo(label=str(i + 1), bbox_page_1000=[100 + i * 250, 100, 300 + i * 250, 400],
                                      entries=[(str(i + 1), f'Specimen {i + 1}, dorsal view', f'YSUG {i}')],
                                      colour='#e11d48' if i % 2 == 0 else '#2563eb')
                            for i in range(n)],
                    unmatched=list(unmatched))


def _settle(qapp, done, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        if done():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.ui
def test_tiles_go_up_at_once_and_the_crops_land_on_them(qapp, white_pdf):
    from PyQt6.QtCore import Qt

    from desktop.components.panel_tiles import PanelTiles

    tiles = PanelTiles('paper.pdf')
    tiles.show_panels(_panel_set(3, unmatched=['4']))
    assert tiles.grid.count() == 3
    assert tiles.header.text() == 'Plate I — 3 panels  ·  no panel for 4'
    assert [tiles.grid.item(i).text() for i in range(3)] == ['1', '2', '3']
    assert 'dorsal view' in tiles.grid.item(0).toolTip() and 'YSUG 0' in tiles.grid.item(0).toolTip()
    tiles.grid.setCurrentRow(1)
    assert tiles.detail.text().startswith('2 — Specimen 2')
    # one page render for the figure, not one per panel
    assert _settle(qapp, lambda: len(white_pdf) >= 1)
    tiles._worker.wait(3000)
    qapp.processEvents()
    assert white_pdf == [(4, 150)]
    assert tiles.grid.item(2).icon().availableSizes()      # a real crop replaced the blank
    assert tiles.grid.item(0).data(Qt.ItemDataRole.UserRole).startswith('1 — ')
    tiles._stop_worker()


@pytest.mark.ui
def test_clearing_between_figures_drops_late_crops(qapp, white_pdf):
    from PyQt6.QtGui import QImage

    from desktop.components.panel_tiles import PanelTiles

    tiles = PanelTiles('paper.pdf')
    tiles.show_panels(_panel_set(2))
    tiles.clear()
    assert tiles.grid.count() == 0 and tiles.header.text() == ''
    tiles._tile_ready(7, 0, QImage(4, 4, QImage.Format.Format_RGB888))   # the old figure's crop, too late
    assert tiles.grid.count() == 0
    tiles.show_panels(None)
    assert tiles.grid.count() == 0
    tiles._stop_worker()


@pytest.mark.unit
def test_panel_boxes_are_drawn_where_the_crop_put_the_page():
    """The box must land on the specimen: same crop box and page size as the
    figure crop, and a panel outside this crop is not drawn on it."""
    from desktop.components.ocr_view import draw_panel_boxes
    page_w, page_h = 1000, 1400
    crop_box = (100, 140, 900, 1260)                # pixels on the page, as crop_box gave them
    crop = Image.new('RGB', (400, 560), 'white')    # the slot: half scale
    panels = [('1', [100, 100, 500, 500], '#e11d48'),   # top-left quarter of the crop
              ('9', [950, 100, 1000, 200], '#2563eb')]  # right of the crop: skipped
    draw_panel_boxes(crop, panels, crop_box, (page_w, page_h))
    # the first panel's page box (100..500 of 1000) is pixels 100..500 × 140..700 → crop (0..200, 0..280)
    assert crop.getpixel((199, 140)) != (255, 255, 255)     # right edge of the box
    assert crop.getpixel((100, 279)) != (255, 255, 255)     # bottom edge
    assert crop.getpixel((300, 400)) == (255, 255, 255)     # nothing else drawn
    assert crop.getpixel((399, 10)) == (255, 255, 255)      # the off-crop panel left no mark


@pytest.mark.ui
def test_the_reader_draws_boxes_only_when_it_was_given_them(qapp, white_pdf):
    from desktop.components.ocr_view import OcrView
    page = ('<div data-bbox="240 89 760 293" data-label="Figure"><img alt="a"/></div>')
    view = OcrView()
    view.resize(760, 900)
    view.show()
    qapp.processEvents()
    view.set_panels({0: [('1', [240, 89, 500, 293], '#e11d48')]})
    view.set_pages([page], 'paper.pdf')
    from papermeister import ocr_layout
    uri = ocr_layout.figure_uri(0, (240, 89, 760, 293))
    view.loadResource(_IMAGE, QUrl(uri))
    assert _settle(qapp, lambda: uri in view._images)
    image = view._images[uri]

    def left_edge_marked(img):
        # the crop is padded a little beyond the bbox, so the box's left edge
        # sits a few pixels in; a white page otherwise
        y = img.height() // 2
        return any(img.pixelColor(x, y).name() != '#ffffff' for x in range(12))

    assert left_edge_marked(image)
    view.set_panels({})
    view.refresh_figures()
    view.loadResource(_IMAGE, QUrl(uri))
    assert _settle(qapp, lambda: uri in view._images)
    assert not left_edge_marked(view._images[uri])
    view._stop_worker()


@pytest.mark.unit
def test_the_box_map_is_by_page_with_colours_cycling_per_figure(db):
    import json

    from desktop.services.paper_service import load_panel_boxes, load_panels, panel_colour
    from papermeister.models import Figure, FigureEntry, FigurePanel, Paper, PaperFile
    paper = Paper.create(title='t')
    pf = PaperFile.create(paper=paper, path='x.pdf', hash='ab' * 32, status='processed')
    fig = Figure.create(paper=paper, paper_file=pf, file_hash=pf.hash, page=3, name='Plate I',
                        bbox_page_1000=json.dumps([100, 200, 900, 800]), blocks_json='[]')
    FigureEntry.create(figure=fig, order=0, label='1', description='Cranidium', specimen_number='S1')
    FigureEntry.create(figure=fig, order=1, label='2', description='Pygidium')
    for i in range(7):
        FigurePanel.create(figure=fig, order=i, label=str(i + 1), bbox_figure_1000=json.dumps([0, 0, 500, 500]),
                           entry_orders_json=json.dumps([0] if i == 0 else []))
    boxes = load_panel_boxes(paper.id)
    assert list(boxes) == [3] and len(boxes[3]) == 7
    assert boxes[3][0][1] == [100, 200, 500, 500]          # figure frame → page frame
    assert boxes[3][6][2] == boxes[3][0][2] == panel_colour(0)   # the seventh wraps to the first colour
    ps = load_panels(fig.id)
    assert ps.unmatched == ['2'] and ps.panels[0].entries == [('1', 'Cranidium', 'S1')]
    assert ps.panels[1].colour == panel_colour(1)
