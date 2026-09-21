"""A figure with its panel boxes, and the worker that crops it — the
Figures tab's building blocks (P16 Phase 5).

`CropWorker` renders a figure's page once, off the UI thread, and crops the
figure from it. `FigureCanvas` shows the crop with a quiet box on every
panel; one panel can be lit (a click, kept) and one hovered (the cursor,
transient), and hovering a box shows its entry as a tooltip. The boxes are
drawn at paint time, so lighting one costs no render and a resize only
rescales.
"""
from __future__ import annotations

import logging
import queue

from PyQt6.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from desktop.theme.tokens import COLORS_DARK

logger = logging.getLogger('papermeister')

MAX_FIGURE_HEIGHT = 1400
MIN_FIGURE_WIDTH = 220
MAX_FIGURE_WIDTH = 760
#: The figure's page is rendered so the crop is about this wide, then scaled
#: to fit — sharp enough to tell specimens apart, cheap enough per figure.
RENDER_WIDTH = 900
#: The lit panel's colour: the one loud thing on an otherwise quiet plate.
HIGHLIGHT = '#facc15'


class CropWorker(QThread):
    """Renders the figure's page once and crops the figure from it."""

    ready = pyqtSignal(int, QImage, tuple, tuple)     # figure id, crop, crop box (px), page size (px)

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._queue: queue.Queue = queue.Queue()
        self._stopping = False

    def request(self, figure_id: int, page: int, bbox_page_1000: list[int], width: int = RENDER_WIDTH):
        self._queue.put((figure_id, page, bbox_page_1000, width))

    def stop(self):
        self._stopping = True
        self._queue.put(None)

    def run(self):
        while not self._stopping:
            job = self._queue.get()
            if job is None:
                return
            figure_id, page, bbox, width = job
            try:
                from papermeister import ocr_layout, pdfdoc
                page_pt = pdfdoc.page_sizes(self._pdf_path, [page])[0][0]
                frac = max(0.05, (bbox[2] - bbox[0]) / 1000)
                dpi = int(max(72, min(300, width * 72 / (page_pt * frac))))
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
    """The figure with its panel boxes. One panel can be lit (a click, kept)
    and one hovered (the cursor, transient); the hovered one wins the paint."""

    panel_clicked = pyqtSignal(int)      # panel index
    panel_hovered = pyqtSignal(int)      # panel index, or -1 when the cursor leaves every box

    def __init__(self, parent=None, max_width: int = MAX_FIGURE_WIDTH, max_height: int = MAX_FIGURE_HEIGHT):
        super().__init__(parent)
        self._image: QImage | None = None
        self._boxes: list[tuple[QRectF, str, str]] = []   # in image pixels: rect, label, colour
        self._tips: list[str] = []                         # per panel: the entry text shown on hover
        self._lit: int | None = None
        self._hover: int | None = None
        self._aspect = 1.0
        self._max_width, self._max_height = max_width, max_height
        self.setMinimumSize(MIN_FIGURE_WIDTH, 120)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_figure(self, image: QImage | None, boxes: list[tuple[QRectF, str, str]], aspect: float,
                   tips: list[str] | None = None) -> None:
        self._image, self._boxes, self._lit, self._hover = image, boxes, None, None
        self._tips = tips or []
        self._aspect = aspect or 1.0
        self._fit()
        self.update()

    def light(self, index: int | None) -> None:
        self._lit = index
        self.update()

    def lit(self) -> int | None:
        return self._lit

    def set_limits(self, max_width: int, max_height: int | None = None) -> None:
        """Re-fit to a new width (the tab was resized); the image is scaled at paint."""
        self._max_width = max(MIN_FIGURE_WIDTH, max_width)
        if max_height is not None:
            self._max_height = max_height
        self._fit()
        self.update()

    def hover(self, index: int | None) -> None:
        """Light a panel while the cursor is on its entry."""
        if index != self._hover:
            self._hover = index
            self.update()

    def _fit(self):
        """As tall as allowed, unless that makes it too wide; never narrower than the minimum."""
        height = self._max_height
        width = int(height * self._aspect)
        if width > self._max_width:
            width = self._max_width
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
        active = self._hover if self._hover is not None else self._lit
        for index, (rect, label, colour) in enumerate(self._boxes):
            r = QRectF(target.x() + rect.x() * sx, target.y() + rect.y() * sy, rect.width() * sx, rect.height() * sy)
            lit = active == index
            faded = active is not None and not lit
            pen_colour = QColor(HIGHLIGHT if lit else colour)
            pen_colour.setAlpha(60 if faded else (255 if lit else 170))
            painter.setPen(QPen(pen_colour, 2.5 if lit else 1))
            if lit:
                fill = QColor(HIGHLIGHT)
                fill.setAlpha(50)
                painter.fillRect(r, fill)
            painter.drawRect(r)
            if label and (lit or not faded):
                tag = QColor(pen_colour)
                tag.setAlpha(255 if lit else 150)
                painter.fillRect(QRectF(r.x(), r.y(), min(r.width(), 6 * len(label) + 8), 13), tag)
                painter.setPen(QColor('#000000' if lit else '#ffffff'))
                painter.drawText(QRectF(r.x() + 3, r.y(), r.width(), 13), Qt.AlignmentFlag.AlignVCenter, label)
        painter.end()

    def _panel_at(self, p) -> int | None:
        """The smallest box under the point, so an a/b sub-panel inside a numbered one is reachable."""
        if self._image is None:
            return None
        target = self._drawn_rect()
        sx = target.width() / max(1, self._image.width())
        sy = target.height() / max(1, self._image.height())
        hits = []
        for index, (rect, _label, _colour) in enumerate(self._boxes):
            r = QRectF(target.x() + rect.x() * sx, target.y() + rect.y() * sy, rect.width() * sx, rect.height() * sy)
            if r.contains(p):
                hits.append((r.width() * r.height(), index))
        return min(hits)[1] if hits else None

    def mousePressEvent(self, event):
        index = self._panel_at(event.position())
        if index is not None:
            self.panel_clicked.emit(index)

    def mouseMoveEvent(self, event):
        index = self._panel_at(event.position())
        if index != self._hover:
            self.hover(index)
            self.panel_hovered.emit(-1 if index is None else index)
            # The entry as a tooltip, so a box can be read without finding
            # its line in the list below.
            tip = self._tips[index] if index is not None and index < len(self._tips) else ''
            if tip:
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()

    def leaveEvent(self, event):
        if self._hover is not None:
            self.hover(None)
            self.panel_hovered.emit(-1)
        super().leaveEvent(event)



def entry_text(panel) -> str:
    """A panel's entries as one tooltip: label — description (specimen)."""
    lines = []
    for label, description, specimen in panel.entries:
        text = f'{label} — {description}' if description else label
        if specimen and specimen not in description:
            text += f' ({specimen})'
        lines.append(text)
    if not lines:
        lines.append('Annotation (scale bar, key), not a specimen.' if panel.annotation else 'No caption entry matched.')
    elif panel.confidence != 'high':
        lines.insert(0, f'Confidence: {panel.confidence}.')
    return '\n'.join(lines)
