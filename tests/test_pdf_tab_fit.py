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


@pytest.mark.ui
def test_the_toolbar_moves_between_pages_and_zooms(qapp):
    from desktop.views.detail_panel import PdfTab
    doc = [_Page(595, 842) for _ in range(5)]
    tab = PdfTab(doc)
    tab.resize(500, 600)
    tab.show()
    qapp.processEvents()
    tab.view._refit_now()
    assert tab.page_total.text() == '/ 5' and tab.page_box.value() == 1 and tab.fit_btn.isChecked()
    fitted = tab.view.zoom()
    # next / previous / typed page
    tab.next_btn.click()
    qapp.processEvents()
    assert tab.view.current_page() == 1 and tab.page_box.value() == 2
    tab.page_box.setValue(4)
    tab.page_box.editingFinished.emit()
    qapp.processEvents()
    assert tab.view.current_page() == 3 and tab.page_box.value() == 4
    tab.prev_btn.click()
    qapp.processEvents()
    assert tab.view.current_page() == 2
    # zoom leaves fit-width mode; the label follows; a resize no longer refits
    tab.zoom_in_btn.click()
    assert not tab.fit_btn.isChecked() and abs(tab.view.zoom() - fitted * 1.25) < 1e-6
    assert tab.zoom_label.text() == f'{round(fitted * 1.25 * 100)}%'
    tab.resize(900, 600)
    qapp.processEvents()
    tab.view._refit_now()
    assert abs(tab.view.zoom() - fitted * 1.25) < 1e-6
    # fit width again follows the (now wider) viewport
    tab.fit_btn.click()
    assert tab.fit_btn.isChecked() and tab.view.zoom() > fitted


@pytest.mark.ui
def test_a_landscape_page_does_not_narrow_the_others(qapp):
    """Bruton 2004 has one 766 pt landscape page among 557 pt portrait ones;
    fitting to the widest left every portrait page at two thirds of the panel."""
    from desktop.views.detail_panel import _LazyPdfView
    doc = [_Page(557, 763), _Page(766, 560), _Page(557, 763)]
    view = _LazyPdfView(doc)
    view.resize(600, 700)
    view.show()
    qapp.processEvents()
    view._refit_now()
    want = view.viewport().width() - view._GUTTER
    assert all(abs(lbl.width() - want) <= 1 for lbl in view._page_labels)
    assert view._zooms[1] < view._zooms[0]
    # a chosen zoom is one zoom for every page
    view.set_zoom(1.0)
    assert view._page_labels[1].width() == 766 and view._page_labels[0].width() == 557
