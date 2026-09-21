"""The Text tab's reader: OCR text with its structure, and its figures.

`papermeister.ocr_layout` turns a page's OCR labels into display HTML and says
where each figure sits on the page; this is the half that needs Qt. Two things
happen here that the pure side cannot do.

**Figures are cropped from the PDF on a worker thread.** Rendering a page costs
about a tenth of a second, and a paper can easily have a dozen figure-bearing
pages — done inline that is a visibly frozen tab, and on a 477-page plate
volume it is a hang. So the document goes up immediately with space reserved
for each figure, and the crops drop into place as they arrive.

**Space is reserved from the page's own proportions**, which is why the width
and height are written into the img tag. Without them the text would reflow
under the reader as each figure landed.
"""

import logging
import queue

from PyQt6.QtCore import QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QTextBrowser

from desktop.theme.tokens import COLORS_DARK, FONT
from papermeister import ocr_layout

logger = logging.getLogger('papermeister')

#: Crops are rendered a little larger than they are shown, so a figure still
#: looks sharp on a hidpi screen. Beyond this the render cost stops buying
#: anything a reader can see.
_OVERSAMPLE = 1.5
_MIN_DPI, _MAX_DPI = 72, 220

#: Pages held as rendered bitmaps in the worker. Figures from one page arrive
#: together, so a small window is enough; a whole plate volume is not.
_PAGE_CACHE = 3


class _FigureWorker(QThread):
    """Renders page crops off the UI thread, one at a time, in request order."""

    ready = pyqtSignal(str, QImage)

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._queue: queue.Queue = queue.Queue()
        self._pages: dict[int, object] = {}
        self._order: list[int] = []
        self._stopping = False

    def request(self, uri: str, page: int, bbox, width: int, height: int):
        self._queue.put((uri, page, bbox, width, height))

    def stop(self):
        self._stopping = True
        self._queue.put(None)

    def run(self):
        while not self._stopping:
            job = self._queue.get()
            if job is None:
                return
            try:
                uri, image = self._render(*job)
            except Exception:
                # A figure that will not render is not fatal — the slot stays
                # blank and the rest of the document is unaffected.
                logger.debug('figure render failed: %s', job[0], exc_info=True)
                continue
            if image is not None and not self._stopping:
                self.ready.emit(uri, image)

    def _render(self, uri, page, bbox, width, height):
        # Enough dpi that the crop is at least as detailed as its slot on
        # screen; derived from how much of the page width the figure takes.
        frac_w = (bbox[2] - bbox[0]) / ocr_layout.BBOX_SCALE
        target_px = width * _OVERSAMPLE
        page_pt = self._page_width_pt(page)
        dpi = target_px * 72 / max(1.0, page_pt * frac_w)
        dpi = int(min(_MAX_DPI, max(_MIN_DPI, dpi)))

        page_image = self._page_bitmap(page, dpi)
        crop = page_image.crop(ocr_layout.crop_box(bbox, *page_image.size))
        if crop.width < 1 or crop.height < 1:
            return uri, None
        crop = crop.resize((width, height))
        data = crop.tobytes('raw', 'RGB')
        image = QImage(data, crop.width, crop.height, 3 * crop.width,
                       QImage.Format.Format_RGB888)
        return uri, image.copy()        # copy: `data` dies with this frame

    def _page_width_pt(self, page: int) -> float:
        from papermeister import pdfdoc
        try:
            return pdfdoc.page_sizes(self._pdf_path, [page])[0][0]
        except Exception:
            return 595.0                # A4 portrait, the overwhelming default

    def _page_bitmap(self, page: int, dpi: int):
        from papermeister import pdfdoc
        key = (page, dpi)
        cached = self._pages.get(key)
        if cached is not None:
            return cached
        image = pdfdoc.render_page(self._pdf_path, page, dpi=dpi)
        self._pages[key] = image
        self._order.append(key)
        while len(self._order) > _PAGE_CACHE:
            self._pages.pop(self._order.pop(0), None)
        return image


class OcrView(QTextBrowser):
    """Read-only view of one paper's OCR, with figures cropped from the PDF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('OcrBrowser')
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.document().setDefaultStyleSheet(_stylesheet())

        self._pages: list[str] = []
        self._pdf_path: str | None = None
        self._page_sizes: dict[int, tuple[float, float]] = {}
        self._slots: dict[str, tuple[int, int]] = {}     # uri -> reserved size
        self._images: dict[str, QImage] = {}
        self._requested: set[str] = set()
        self._worker: _FigureWorker | None = None

        # Arrivals are batched: a dozen figures landing in a burst should cost
        # one relayout, not a dozen.
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(120)
        self._refresh.timeout.connect(self._redraw_figures)

        # Figure slots are sized against the panel, so a resized panel needs
        # them recomputed — otherwise they stay at the width they were built
        # for and either overflow or leave the column half empty.
        self._built_width = 0
        self._resized = QTimer(self)
        self._resized.setSingleShot(True)
        self._resized.setInterval(250)
        self._resized.timeout.connect(self._rebuild)

    # ── building ────────────────────────────────────────────────

    def set_pages(self, pages: list[str], pdf_path: str | None = None):
        """Show these OCR pages, cropping figures from `pdf_path` if given."""
        self._stop_worker()
        self._pages = pages
        self._pdf_path = pdf_path
        self._slots.clear()
        self._images.clear()
        self._requested.clear()
        self._page_sizes = self._measure_pages(pages, pdf_path)
        # Build first: rendering the HTML is what discovers the figures (the
        # sizer records a slot per figure). The worker has to be running before
        # the document is set, because setting it is what asks for the images —
        # a request that arrives with no worker to take it is simply dropped.
        html = ocr_layout.document_html(pages, sizer=self._slot_size)
        if self._slots and pdf_path:
            self._worker = _FigureWorker(pdf_path, self)
            self._worker.ready.connect(self._figure_ready)
            self._worker.start()
        self._built_width = self._available_width()
        self.setHtml(html)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._slots and abs(self._available_width() - self._built_width) > 40:
            self._resized.start()

    def _rebuild(self):
        """Re-lay the document at the current width, keeping the reader's place.

        Cached crops are dropped rather than rescaled: they were rendered for
        the old slot, and a figure of small print stretched to a wider slot is
        exactly the case where the difference shows.
        """
        if not self._pages:
            return
        scrollbar = self.verticalScrollBar()
        fraction = scrollbar.value() / scrollbar.maximum() if scrollbar.maximum() else 0.0
        self.set_pages(self._pages, self._pdf_path)
        scrollbar.setValue(round(scrollbar.maximum() * fraction))

    def _measure_pages(self, pages, pdf_path) -> dict[int, tuple[float, float]]:
        """Page proportions, for the pages that actually hold figures."""
        if not pdf_path:
            return {}
        wanted = ocr_layout.picture_pages(pages)
        if not wanted:
            return {}
        from papermeister import pdfdoc
        try:
            sizes = pdfdoc.page_sizes(pdf_path, wanted)
        except Exception:
            return {}
        return dict(zip(wanted, sizes, strict=False))

    def _slot_size(self, page: int, bbox):
        """Space to reserve for one figure, or None if it cannot be shown."""
        size = self._page_sizes.get(page)
        if size is None:
            return None
        width, height = ocr_layout.display_size(bbox, size[0], size[1],
                                                self._available_width())
        self._slots[ocr_layout.figure_uri(page, bbox)] = (width, height)
        return width, height

    def _available_width(self) -> int:
        # The viewport is not laid out yet on the first build, so fall back to
        # a readable column rather than to whatever Qt reports before showing.
        width = self.viewport().width()
        return max(320, (width if width > 100 else 720) - 40)

    # ── figures ─────────────────────────────────────────────────

    def loadResource(self, resource_type, url: QUrl):
        uri = url.toString()
        parsed = ocr_layout.parse_figure_uri(uri)
        if parsed is None:
            return super().loadResource(resource_type, url)

        image = self._images.get(uri)
        if image is not None:
            return image

        if uri not in self._requested and self._worker is not None:
            self._requested.add(uri)
            page, bbox = parsed
            width, height = self._slots.get(uri, (320, 240))
            self._worker.request(uri, page, bbox, width, height)
        return self._placeholder(uri)

    def _placeholder(self, uri: str) -> QImage:
        width, height = self._slots.get(uri, (320, 240))
        image = QImage(width, height, QImage.Format.Format_RGB888)
        image.fill(QColor(COLORS_DARK['bg.elevated']))
        return image

    def _figure_ready(self, uri: str, image: QImage):
        self._images[uri] = image
        self._refresh.start()

    def _redraw_figures(self):
        """Swap the arrived crops in without moving the reader.

        The slots were sized up front, so nothing reflows — but the document
        has the placeholders cached as resources, and only re-adding them and
        marking the content dirty gets the real pixels drawn.
        """
        document = self.document()
        for uri, image in self._images.items():
            document.addResource(document.ResourceType.ImageResource,
                                 QUrl(uri), image)
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        document.markContentsDirty(0, document.characterCount())
        scrollbar.setValue(position)

    # ── lifetime ────────────────────────────────────────────────

    def _stop_worker(self):
        if self._worker is None:
            return
        self._worker.ready.disconnect()
        self._worker.stop()
        self._worker.wait(2000)
        self._worker = None

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)

    def __del__(self):
        try:
            self._stop_worker()
        except Exception:
            pass


def _stylesheet() -> str:
    """Qt rich text supports a small slice of CSS; this stays inside it."""
    return f"""
    h2.pm-section {{
        color: {COLORS_DARK['text.primary']};
        font-size: {FONT['size.lg']}px;
        font-weight: {FONT['weight.bold']};
        margin-top: 18px;
        margin-bottom: 6px;
    }}
    div.pm-caption {{
        color: {COLORS_DARK['text.secondary']};
        font-size: {FONT['size.sm']}px;
        margin-top: 4px;
        margin-bottom: 14px;
    }}
    div.pm-equation {{
        color: {COLORS_DARK['text.primary']};
        font-family: {FONT['family.mono']};
        margin: 8px 0px 8px 0px;
    }}
    div.pm-figure {{
        margin-top: 12px;
        margin-bottom: 4px;
    }}
    div.pm-missing-figure {{
        color: {COLORS_DARK['text.muted']};
        font-size: {FONT['size.sm']}px;
        margin: 10px 0px 10px 0px;
    }}
    div.pm-page-mark {{
        color: {COLORS_DARK['text.muted']};
        font-size: {FONT['size.xs']}px;
        margin-top: 24px;
        margin-bottom: 8px;
    }}
    """
