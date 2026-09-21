"""The chosen figure's panels and caption entries, under the Text tab's
figure list — P16 Phase 5.

For a figure the split stage (③) worked on: the **figure itself with a box
on every panel**, and beside it the caption entries. Click an entry and its
panel lights up on the figure; click a panel and its entry is selected. That
is the check a reviewer does — is *this* box the specimen *this* entry
describes — and it needs the whole plate, not a tile: where a box sits among
its neighbours is half the evidence.

For a figure with entries but no panels (most figures): the entries alone.

The figure crop comes off a worker thread like the reader's figures
(`ocr_view`): one page render, one crop, delivered as an image; the boxes are
drawn on paint, so a highlight costs no render.
"""
from __future__ import annotations

import logging
import queue

from PyQt6.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.theme.tokens import COLORS_DARK, FONT, SPACING

logger = logging.getLogger('papermeister')

#: The figure is shown no taller than this; a plate is tall, the list beside
#: it needs the rest of the tab.
MAX_FIGURE_HEIGHT = 380
MIN_FIGURE_WIDTH = 220
MAX_FIGURE_WIDTH = 520
#: The figure's page is rendered so the crop is about this wide, then scaled
#: to fit — sharp enough to tell specimens apart, cheap enough per click.
RENDER_WIDTH = 900
_MAX_LIST_HEIGHT = 380
HIGHLIGHT = '#facc15'


class _CropWorker(QThread):
    """Renders the figure's page once and crops the figure from it."""

    ready = pyqtSignal(int, QImage, tuple, tuple)     # figure id, crop, crop box (px), page size (px)

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._queue: queue.Queue = queue.Queue()
        self._stopping = False

    def request(self, figure_id: int, page: int, bbox_page_1000: list[int]):
        self._queue.put((figure_id, page, bbox_page_1000))

    def stop(self):
        self._stopping = True
        self._queue.put(None)

    def run(self):
        while not self._stopping:
            job = self._queue.get()
            if job is None:
                return
            figure_id, page, bbox = job
            try:
                from papermeister import ocr_layout, pdfdoc
                page_pt = pdfdoc.page_sizes(self._pdf_path, [page])[0][0]
                frac = max(0.05, (bbox[2] - bbox[0]) / 1000)
                dpi = int(max(72, min(220, RENDER_WIDTH * 72 / (page_pt * frac))))
                page_image = pdfdoc.render_page(self._pdf_path, page, dpi=dpi)
                box = ocr_layout.crop_box(tuple(bbox), *page_image.size)
                crop = page_image.crop(box).convert('RGB')
            except Exception:
                # A page that will not render leaves the entries alone; the
                # list above still says what the split found.
                logger.debug('figure crop failed: figure %s page %s', figure_id, page, exc_info=True)
                continue
            if crop.width < 1 or crop.height < 1 or self._stopping:
                continue
            data = crop.tobytes('raw', 'RGB')
            image = QImage(data, crop.width, crop.height, 3 * crop.width, QImage.Format.Format_RGB888)
            self.ready.emit(figure_id, image.copy(), tuple(box), tuple(page_image.size))


class FigureCanvas(QWidget):
    """The figure with its panel boxes; one panel can be lit."""

    panel_clicked = pyqtSignal(int)      # panel index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._boxes: list[tuple[QRectF, str, str]] = []   # in image pixels: rect, label, colour
        self._lit: int | None = None
        self._aspect = 1.0
        self.setMinimumSize(MIN_FIGURE_WIDTH, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_figure(self, image: QImage | None, boxes: list[tuple[QRectF, str, str]], aspect: float) -> None:
        self._image, self._boxes, self._lit = image, boxes, None
        self._aspect = aspect or 1.0
        self._fit()
        self.update()

    def light(self, index: int | None) -> None:
        self._lit = index
        self.update()

    def lit(self) -> int | None:
        return self._lit

    def _fit(self):
        """As tall as allowed, unless that makes it too wide; never narrower than the minimum."""
        height = MAX_FIGURE_HEIGHT
        width = int(height * self._aspect)
        if width > MAX_FIGURE_WIDTH:
            width = MAX_FIGURE_WIDTH
            height = int(width / self._aspect)
        self.setFixedSize(max(MIN_FIGURE_WIDTH, width), max(120, height))

    def _drawn_rect(self) -> QRectF:
        """Where the image sits, scaled to fit and centred."""
        w, h = self.width(), self.height()
        scale = min(w / max(1, self._image.width()), h / max(1, self._image.height())) if self._image else 1.0
        iw = (self._image.width() if self._image else w) * scale
        ih = (self._image.height() if self._image else h) * scale
        return QRectF((w - iw) / 2, (h - ih) / 2, iw, ih)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS_DARK['bg.elevated']))
        if self._image is None:
            painter.end()
            return
        target = self._drawn_rect()
        painter.drawImage(target, self._image)
        sx = target.width() / max(1, self._image.width())
        sy = target.height() / max(1, self._image.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, (rect, label, colour) in enumerate(self._boxes):
            r = QRectF(target.x() + rect.x() * sx, target.y() + rect.y() * sy, rect.width() * sx, rect.height() * sy)
            lit = self._lit == index
            faded = self._lit is not None and not lit
            pen_colour = QColor(HIGHLIGHT if lit else colour)
            if faded:
                pen_colour.setAlpha(90)
            painter.setPen(QPen(pen_colour, 3 if lit else 1.5))
            if lit:
                fill = QColor(HIGHLIGHT)
                fill.setAlpha(50)
                painter.fillRect(r, fill)
            painter.drawRect(r)
            if label and (lit or not faded):
                painter.fillRect(QRectF(r.x(), r.y(), min(r.width(), 6 * len(label) + 8), 13), pen_colour)
                painter.setPen(QColor('#000000' if lit else '#ffffff'))
                painter.drawText(QRectF(r.x() + 3, r.y(), r.width(), 13), Qt.AlignmentFlag.AlignVCenter, label)
        painter.end()

    def mousePressEvent(self, event):
        if self._image is None:
            return
        target = self._drawn_rect()
        sx = target.width() / max(1, self._image.width())
        sy = target.height() / max(1, self._image.height())
        p = event.position()
        hits = []
        for index, (rect, _label, _colour) in enumerate(self._boxes):
            r = QRectF(target.x() + rect.x() * sx, target.y() + rect.y() * sy, rect.width() * sx, rect.height() * sy)
            if r.contains(p):
                hits.append((r.width() * r.height(), index))
        if hits:
            self.panel_clicked.emit(min(hits)[1])     # the smallest box under the cursor


class PanelTiles(QFrame):
    """The chosen figure: panels on the figure and its caption entries.
    `show_panels()` a PanelSet, `show_entries()` for a figure without
    panels, `clear()` between figures."""

    def __init__(self, pdf_path: str | None, parent=None):
        super().__init__(parent)
        self.setObjectName('PanelTiles')
        self._pdf_path = pdf_path
        self._worker: _CropWorker | None = None
        self._figure_id: int | None = None
        self._panel_set = None
        self._panel_of_entry: dict[int, int] = {}     # entry row -> panel index
        self._entry_of_panel: dict[int, int] = {}     # panel index -> first entry row
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], 0, SPACING['lg'], SPACING['sm'])
        layout.setSpacing(SPACING['xs'])
        self.header = QLabel('')
        self.header.setStyleSheet(f"font-weight: {FONT['weight.bold']};")
        layout.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(SPACING['md'])
        self.canvas = FigureCanvas()
        self.canvas.panel_clicked.connect(self._panel_clicked)
        body.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignTop)
        self.entries = QListWidget()
        self.entries.setObjectName('EntryList')
        self.entries.setMaximumHeight(_MAX_LIST_HEIGHT)
        self.entries.setWordWrap(True)
        self.entries.currentRowChanged.connect(self._entry_chosen)
        body.addWidget(self.entries, 1)
        layout.addLayout(body)
        self.hide()

    # ── driven by the figure list ─────────────────────────────

    def show_panels(self, panel_set) -> None:
        self.clear()
        if panel_set is None or not panel_set.panels:
            return
        self._figure_id = panel_set.figure_id
        self._panel_set = panel_set
        title = f'{panel_set.name or "Figure"} — {len(panel_set.panels)} panels'
        if panel_set.unmatched:
            title += f'  ·  no panel for {", ".join(panel_set.unmatched)}'
        self.header.setText(title)
        # Entries in caption order, each remembering its panel; a panel with
        # no entry (an annotation, an unlabelled specimen) is listed after.
        for index, p in enumerate(panel_set.panels):
            for label, description, specimen in p.entries:
                self._add_entry(label, description, specimen, p.colour, index)
        for index, p in enumerate(panel_set.panels):
            if not p.entries:
                what = 'annotation (scale bar, key)' if p.annotation else 'no caption entry'
                self._add_entry(p.label or '?', what, '', p.colour, index)
        for label in panel_set.unmatched:
            self._add_entry(label, 'no panel — check the plate', '', COLORS_DARK['text.secondary'], None)
        x0, y0, x1, y1 = panel_set.bbox_page_1000
        aspect = max(1, x1 - x0) / max(1, y1 - y0)
        self.canvas.set_figure(None, [], aspect)
        self.canvas.show()
        self.show()
        if self._pdf_path:
            self._ensure_worker().request(panel_set.figure_id, panel_set.page, panel_set.bbox_page_1000)

    def show_entries(self, name: str, entries: list[tuple[str, str, str]]) -> None:
        """The caption entries of a figure without panels."""
        self.clear()
        if not entries:
            return
        self.header.setText(f'{name or "Figure"} — {len(entries)} caption entries')
        for label, description, specimen in entries:
            self._add_entry(label, description, specimen, None, None)
        self.canvas.hide()
        self.show()

    def clear(self) -> None:
        self._figure_id = None
        self._panel_set = None
        self._panel_of_entry.clear()
        self._entry_of_panel.clear()
        self.entries.clear()
        self.canvas.set_figure(None, [], 1.0)
        self.canvas.show()
        self.header.setText('')
        self.hide()

    # ── internals ─────────────────────────────────────────────

    def _add_entry(self, label, description, specimen, colour, panel_index):
        text = f'{label}  {description}' if description else label
        if specimen and specimen not in description:
            text += f'  ({specimen})'
        item = QListWidgetItem(text)
        item.setToolTip(text)
        if colour:
            item.setForeground(QColor(colour))
        row = self.entries.count()
        self.entries.addItem(item)
        if panel_index is not None:
            self._panel_of_entry[row] = panel_index
            self._entry_of_panel.setdefault(panel_index, row)

    def _entry_chosen(self, row: int):
        self.canvas.light(self._panel_of_entry.get(row))

    def _panel_clicked(self, index: int):
        row = self._entry_of_panel.get(index)
        if row is None:
            self.canvas.light(index)
            return
        self.entries.setCurrentRow(row)      # lights the panel through _entry_chosen

    def _crop_ready(self, figure_id: int, image: QImage, box: tuple, page_size: tuple):
        if figure_id != self._figure_id or self._panel_set is None:
            return                              # the figure before this one
        cx0, cy0, cx1, cy1 = box
        page_w, page_h = page_size
        sx = image.width() / max(1, cx1 - cx0)
        sy = image.height() / max(1, cy1 - cy0)
        boxes = []
        for p in self._panel_set.panels:
            x0, y0, x1, y1 = p.bbox_page_1000
            rect = QRectF((x0 * page_w / 1000 - cx0) * sx, (y0 * page_h / 1000 - cy0) * sy,
                          (x1 - x0) * page_w / 1000 * sx, (y1 - y0) * page_h / 1000 * sy)
            boxes.append((rect, p.label, p.colour))
        lit = self.canvas.lit()
        self.canvas.set_figure(image, boxes, image.width() / max(1, image.height()))
        self.canvas.light(lit)

    def _ensure_worker(self) -> _CropWorker:
        if self._worker is None:
            self._worker = _CropWorker(self._pdf_path, self)
            self._worker.ready.connect(self._crop_ready)
            self._worker.start()
        return self._worker

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
