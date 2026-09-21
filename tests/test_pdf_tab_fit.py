"""The PDF tab fits pages to the viewport width and re-fits on resize."""
import pytest


class _Page:
    def __init__(self, w, h):
        self._size = (w, h)
        self.rendered = []

    def get_size(self):
        return self._size

    def render(self, scale, rev_byteorder=True, prefer_bgrx=False):
        self.rendered.append(scale)
        w, h = int(self._size[0] * scale), int(self._size[1] * scale)

        class Bitmap:
            width, height, stride = w, h, w * 3
            buffer = bytes(w * h * 3)
        return Bitmap()


@pytest.mark.ui
def test_pages_fit_the_width_and_are_rerendered_after_a_resize(qapp):
    from desktop.views.detail_panel import _LazyPdfView
    doc = [_Page(595, 842), _Page(595, 842)]
    view = _LazyPdfView(doc)
    view.resize(500, 600)
    view.show()
    qapp.processEvents()
    view._refit_now()
    label = view._page_labels[0]
    assert abs(label.width() - (view.viewport().width() - view._GUTTER)) <= 1
    assert doc[0].rendered and view._rendered[0]
    zoom_before = view._zoom
    view.resize(900, 600)
    qapp.processEvents()
    view._refit_now()
    assert view._zoom > zoom_before and label.width() > 800
    assert len(doc[0].rendered) == 2          # decoded again for the new width
