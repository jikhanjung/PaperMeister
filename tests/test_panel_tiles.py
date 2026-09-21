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
def test_the_figure_goes_up_with_its_entries_and_the_crop_lands(qapp, white_pdf):
    from PyQt6.QtCore import Qt

    from desktop.components.panel_tiles import PanelTiles

    tiles = PanelTiles('paper.pdf')
    tiles.show_panels(_panel_set(3, unmatched=['4']))
    assert tiles.header.text() == 'Plate I — 3 panels  ·  no panel for 4'
    # entries in caption order, the unmatched one last and greyed
    assert [tiles.entries.item(i).text().split('  ')[0] for i in range(tiles.entries.count())] == ['1', '2', '3', '4']
    assert 'no panel' in tiles.entries.item(3).text()
    assert tiles.entries.item(0).foreground().color().name() == '#e11d48'
    # one page render for the figure
    assert _settle(qapp, lambda: len(white_pdf) >= 1)
    tiles._worker.wait(3000)
    qapp.processEvents()
    assert [page for page, _ in white_pdf] == [4]
    assert tiles.canvas._image is not None and len(tiles.canvas._boxes) == 3
    assert tiles.canvas._boxes[0][1] == '1' and tiles.canvas._boxes[0][2] == '#e11d48'
    assert tiles.entries.item(0).data(Qt.ItemDataRole.ToolTipRole).startswith('1  Specimen 1')
    tiles._stop_worker()


@pytest.mark.ui
def test_an_entry_lights_its_panel_and_a_panel_selects_its_entry(qapp, white_pdf):
    from desktop.components.panel_tiles import PanelTiles

    tiles = PanelTiles('paper.pdf')
    tiles.show_panels(_panel_set(3, unmatched=['4']))
    tiles.entries.setCurrentRow(1)
    assert tiles.canvas.lit() == 1
    tiles.entries.setCurrentRow(3)            # the unmatched entry lights nothing
    assert tiles.canvas.lit() is None
    tiles.canvas.panel_clicked.emit(2)
    assert tiles.entries.currentRow() == 2 and tiles.canvas.lit() == 2
    # the highlight survives the crop arriving late
    assert _settle(qapp, lambda: tiles.canvas._image is not None)
    assert tiles.canvas.lit() == 2
    tiles._stop_worker()


@pytest.mark.ui
def test_a_click_on_the_figure_finds_the_smallest_box_under_it(qapp):
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage

    from desktop.components.panel_tiles import FigureCanvas
    canvas = FigureCanvas()
    image = QImage(400, 400, QImage.Format.Format_RGB888)
    image.fill(0xffffff)
    canvas.set_figure(image, [(QRectF(0, 0, 400, 400), 'all', '#e11d48'),
                              (QRectF(100, 100, 50, 50), '2', '#2563eb')], 1.0)
    hits = []
    canvas.panel_clicked.connect(hits.append)
    target = canvas._drawn_rect()
    sx = target.width() / 400

    class Ev:
        def __init__(self, x, y):
            self._p = (x, y)

        def position(self):
            from PyQt6.QtCore import QPointF
            return QPointF(*self._p)

    canvas.mousePressEvent(Ev(target.x() + 120 * sx, target.y() + 120 * sx))
    canvas.mousePressEvent(Ev(target.x() + 300 * sx, target.y() + 300 * sx))
    assert hits == [1, 0]


@pytest.mark.ui
def test_clearing_between_figures_drops_a_late_crop(qapp, white_pdf):
    from PyQt6.QtGui import QImage

    from desktop.components.panel_tiles import PanelTiles

    tiles = PanelTiles('paper.pdf')
    tiles.show_panels(_panel_set(2))
    tiles.clear()
    assert tiles.entries.count() == 0 and tiles.header.text() == ''
    tiles._crop_ready(7, QImage(4, 4, QImage.Format.Format_RGB888), (0, 0, 4, 4), (100, 100))
    assert tiles.canvas._image is None
    tiles.show_panels(None)
    assert tiles.entries.count() == 0
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


@pytest.mark.ui
def test_a_figure_with_entries_but_no_panels_lists_the_entries(qapp):
    from desktop.components.panel_tiles import PanelTiles
    tiles = PanelTiles(None)
    tiles.show_entries('Plate 1', [('1', 'Shumardia cf. pentagonalis. PMO 140.788. Cranidium, dorsal view, ×20.', 'PMO 140.788'),
                                   ('4', 'Pseudocalymene superba. Hypostoma.', 'PMO 140.763')])
    assert tiles.header.text() == 'Plate 1 — 2 caption entries'
    assert tiles.entries.count() == 2 and tiles.canvas.isHidden()
    assert tiles.entries.item(1).text() == '4  Pseudocalymene superba. Hypostoma.  (PMO 140.763)'
    assert '(PMO 140.788)' not in tiles.entries.item(0).text()      # already in the description
    tiles.show_panels(_panel_set(1))          # a split figure: the figure comes back
    assert tiles.entries.count() == 1 and not tiles.canvas.isHidden()
    tiles.show_entries('Fig. 1', [])
    assert tiles.isHidden()
    tiles._stop_worker()


@pytest.mark.unit
def test_load_entries_reads_the_figures_entries_in_order(db):
    import json

    from desktop.services.paper_service import load_entries
    from papermeister.models import Figure, FigureEntry, Paper, PaperFile
    paper = Paper.create(title='t')
    pf = PaperFile.create(paper=paper, path='x.pdf', hash='cd' * 32, status='processed')
    fig = Figure.create(paper=paper, paper_file=pf, file_hash=pf.hash, page=3, name='Plate 1',
                        bbox_page_1000=json.dumps([100, 200, 900, 800]), blocks_json='[]')
    FigureEntry.create(figure=fig, order=1, label='2', description='Pygidium')
    FigureEntry.create(figure=fig, order=0, label='1', description='Cranidium', specimen_number='S1')
    assert load_entries(fig.id) == ('Plate 1', [('1', 'Cranidium', 'S1'), ('2', 'Pygidium', '')])
    assert load_entries(999) == ('', [])
