"""The Text tab's reader, on the Qt side.

What matters here is not how it looks but what it does with the reader's time:
a figure costs a PDF page render, and a paper — never mind a 477-page plate
volume — has many. So the document must go up without waiting for any of them,
the space must already be the right shape when they land, and a page must be
rendered only when a figure on it is actually on screen.
"""
import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage, QTextDocument

from papermeister import ocr_layout

PAGE_WITH_FIGURE = (
    '<div data-bbox="85 47 158 61" data-label="Page-Header"><p>Fossils 86</p></div>'
    '<div data-bbox="85 466 210 479" data-label="Section-Header"><h4>Etymology</h4></div>'
    '<div data-bbox="240 89 760 293" data-label="Figure">'
    '<img alt="Map of the equatorial Pacific."/></div>'
)
PLAIN_PAGE = '<div data-bbox="85 481 479 629" data-label="Text"><p>no pictures</p></div>'

#: What Qt passes when it needs an image for an <img> tag.
_IMAGE = int(QTextDocument.ResourceType.ImageResource.value)

#: Never opened — every test that uses it stubs out the PDF layer.
FAKE_PDF = 'paper.pdf'


@pytest.fixture
def fake_pdf(monkeypatch):
    """A PDF that measures instantly and renders a recognisable page."""
    from papermeister import pdfdoc

    rendered = []

    def page_sizes(path, indices=None):
        return [(595.0, 842.0) for _ in (indices if indices is not None else [0])]

    def render_page(path, page_idx, dpi=150):
        from PIL import Image
        rendered.append((page_idx, dpi))
        return Image.new('RGB', (round(595 * dpi / 72), round(842 * dpi / 72)), 'white')

    monkeypatch.setattr(pdfdoc, 'page_sizes', page_sizes)
    monkeypatch.setattr(pdfdoc, 'render_page', render_page)
    return rendered


@pytest.fixture
def view(qapp):
    from desktop.components.ocr_view import OcrView

    widget = OcrView()
    widget.resize(760, 900)
    widget.show()          # the viewport only takes its size once laid out
    qapp.processEvents()
    yield widget
    widget._stop_worker()


def _wait_for_figures(qapp, view, seconds=10):
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        if view._requested and len(view._images) >= len(view._requested):
            return True
        time.sleep(0.02)
    return False


@pytest.mark.ui
def test_the_document_is_up_before_any_figure_is_rendered(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)

    assert 'Etymology' in view.toPlainText()
    assert fake_pdf == []          # nothing rendered yet — the reader is not waiting
    assert len(view._slots) == 1   # but the space is already reserved


@pytest.mark.ui
def test_a_figure_is_rendered_only_when_it_is_asked_for(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)
    uri = ocr_layout.figure_uri(0, (240, 89, 760, 293))

    view.loadResource(_IMAGE, QUrl(uri))       # what painting the figure does
    assert _wait_for_figures(qapp, view), 'figure never arrived'

    assert [page for page, _ in fake_pdf] == [0]
    assert isinstance(view._images[uri], QImage)


@pytest.mark.ui
def test_the_reserved_slot_and_the_delivered_crop_are_the_same_size(qapp, view, fake_pdf):
    """The size is committed to before the pixels exist; if the crop came back
    a different shape the text would jump as each figure landed."""
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)
    uri = ocr_layout.figure_uri(0, (240, 89, 760, 293))
    reserved = view._slots[uri]

    view.loadResource(_IMAGE, QUrl(uri))
    assert _wait_for_figures(qapp, view)

    image = view._images[uri]
    assert (image.width(), image.height()) == reserved


@pytest.mark.ui
def test_the_placeholder_holds_the_slot_until_the_crop_arrives(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)
    uri = ocr_layout.figure_uri(0, (240, 89, 760, 293))

    first = view.loadResource(_IMAGE, QUrl(uri))
    assert (first.width(), first.height()) == view._slots[uri]


@pytest.mark.ui
def test_pages_without_figures_start_no_worker(qapp, view, fake_pdf):
    view.set_pages([PLAIN_PAGE], FAKE_PDF)
    assert view._worker is None
    assert view._slots == {}


@pytest.mark.ui
def test_without_a_pdf_the_figure_becomes_its_description(qapp, view):
    view.set_pages([PAGE_WITH_FIGURE], None)

    assert view._worker is None
    assert 'Map of the equatorial Pacific.' in view.toPlainText()


@pytest.mark.ui
def test_a_pdf_that_cannot_be_measured_does_not_take_the_tab_down(qapp, view, monkeypatch):
    from papermeister import pdfdoc

    def explode(path, indices=None):
        raise OSError('file went away mid-read')

    monkeypatch.setattr(pdfdoc, 'page_sizes', explode)
    view.set_pages([PAGE_WITH_FIGURE], 'gone.pdf')

    assert 'Etymology' in view.toPlainText()     # the text still reads
    assert view._slots == {}


@pytest.mark.ui
def test_non_figure_resources_are_left_to_qt(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)
    # Not ours, so it must not be answered with a placeholder.
    assert view.loadResource(_IMAGE, QUrl('https://example.org/logo.png')) in (None, )


@pytest.mark.ui
def test_a_resized_panel_resizes_the_figures(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], FAKE_PDF)
    before = next(iter(view._slots.values()))

    view.resize(400, 900)
    qapp.processEvents()
    view._rebuild()          # what the debounce timer would fire

    after = next(iter(view._slots.values()))
    assert after[0] < before[0]


@pytest.mark.ui
def test_switching_papers_stops_the_previous_worker(qapp, view, fake_pdf):
    view.set_pages([PAGE_WITH_FIGURE], 'first.pdf')
    first = view._worker
    assert first is not None

    view.set_pages([PAGE_WITH_FIGURE], 'second.pdf')
    assert first.isFinished() or not first.isRunning()
    assert view._worker is not first
