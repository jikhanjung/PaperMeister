"""Panel tiles under the Text tab's figure list — P16 Phase 5, step 2.

The split stage (③) draws a box around every specimen on a plate and matches
it to a caption entry. A count on the figure's line says it ran; whether it
ran *right* — the box on the specimen, the label on the right specimen — a
person can only tell by looking. So choosing a figure shows its panels as
tiles: the crop, the label, and on hover or click the entry it was matched to.

Crops come off a worker thread like the reader's figures (`ocr_view`): one
page render per figure, then one crop per panel. The tiles go up at once as
blank slots the size of the finished crop, so the grid does not jump as the
images land.
"""
from __future__ import annotations

import logging
import queue

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from desktop.theme.tokens import COLORS_DARK, FONT, SPACING

logger = logging.getLogger('papermeister')

#: Tile size on screen. A specimen photo is rarely wider than tall; the box
#: keeps the crop's proportions inside it.
TILE = 112
#: The page is rendered once per figure at this resolution; a plate panel is
#: a tenth of the page, so this leaves it a little sharper than the tile.
RENDER_DPI = 150
_MAX_HEIGHT = 300


class _TileWorker(QThread):
    """Renders the figure's page once and crops each panel from it."""

    ready = pyqtSignal(int, int, QImage)      # figure id, panel index, image

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._queue: queue.Queue = queue.Queue()
        self._stopping = False

    def request(self, figure_id: int, page: int, boxes: list[tuple[list[int], str]]):
        self._queue.put((figure_id, page, boxes))

    def stop(self):
        self._stopping = True
        self._queue.put(None)

    def run(self):
        while not self._stopping:
            job = self._queue.get()
            if job is None:
                return
            figure_id, page, boxes = job
            try:
                from papermeister import pdfdoc
                page_image = pdfdoc.render_page(self._pdf_path, page, dpi=RENDER_DPI)
            except Exception:
                # A page that will not render leaves blank tiles; the list
                # above still says what the split found.
                logger.debug('panel page render failed: figure %s page %s', figure_id, page, exc_info=True)
                continue
            width, height = page_image.size
            for index, (box, colour) in enumerate(boxes):
                if self._stopping:
                    return
                x0, y0, x1, y1 = (int(box[0] * width / 1000), int(box[1] * height / 1000),
                                  int(box[2] * width / 1000), int(box[3] * height / 1000))
                if x1 - x0 < 1 or y1 - y0 < 1:
                    continue
                crop = page_image.crop((x0, y0, x1, y1)).convert('RGB')
                crop.thumbnail((TILE * 2, TILE * 2))          # hidpi-sharp, then Qt scales down
                # The frame is the box's colour in the reader: tile ↔ box.
                from PIL import ImageDraw
                ImageDraw.Draw(crop).rectangle((0, 0, crop.width - 1, crop.height - 1), outline=colour, width=4)
                data = crop.tobytes('raw', 'RGB')
                image = QImage(data, crop.width, crop.height, 3 * crop.width, QImage.Format.Format_RGB888)
                self.ready.emit(figure_id, index, image.copy())


class PanelTiles(QFrame):
    """The panels of one figure. `show()` a PanelSet; `clear()` between figures."""

    def __init__(self, pdf_path: str | None, parent=None):
        super().__init__(parent)
        self.setObjectName('PanelTiles')
        self._pdf_path = pdf_path
        self._worker: _TileWorker | None = None
        self._figure_id: int | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], 0, SPACING['lg'], SPACING['sm'])
        layout.setSpacing(SPACING['xs'])
        self.header = QLabel('')
        self.header.setStyleSheet(f"font-weight: {FONT['weight.bold']};")
        layout.addWidget(self.header)
        self.grid = QListWidget()
        self.grid.setObjectName('PanelTileGrid')
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setFlow(QListWidget.Flow.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(TILE, TILE))
        self.grid.setGridSize(QSize(TILE + SPACING['md'], TILE + 2 * FONT['size.sm'] + SPACING['sm']))
        self.grid.setSpacing(SPACING['xs'])
        self.grid.setMaximumHeight(_MAX_HEIGHT)
        self.grid.setWordWrap(False)
        self.grid.currentItemChanged.connect(self._describe)
        layout.addWidget(self.grid)
        self.detail = QLabel('')
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {COLORS_DARK['text.secondary']}; font-size: {FONT['size.sm']}px;")
        layout.addWidget(self.detail)
        self.hide()

    # ── driven by the figure list ─────────────────────────────

    def show_panels(self, panel_set) -> None:
        self.clear()
        if panel_set is None or not panel_set.panels:
            return
        self._figure_id = panel_set.figure_id
        title = f'{panel_set.name or "Figure"} — {len(panel_set.panels)} panels'
        if panel_set.unmatched:
            title += f'  ·  no panel for {", ".join(panel_set.unmatched)}'
        self.header.setText(title)
        blank = QPixmap(TILE, TILE)
        blank.fill(QColor(COLORS_DARK['bg.elevated']))
        for p in panel_set.panels:
            item = QListWidgetItem(QIcon(blank), p.label or '?')
            item.setData(Qt.ItemDataRole.UserRole, _entry_text(p))
            item.setToolTip(_entry_text(p) or 'No caption entry matched')
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            if p.annotation or p.confidence != 'high':
                item.setForeground(QColor(COLORS_DARK['text.secondary']))
            self.grid.addItem(item)
        self.show()
        if self._pdf_path:
            self._ensure_worker().request(panel_set.figure_id, panel_set.page,
                                          [(p.bbox_page_1000, p.colour) for p in panel_set.panels])

    def clear(self) -> None:
        self._figure_id = None
        self.grid.clear()
        self.header.setText('')
        self.detail.setText('')
        self.hide()

    # ── internals ─────────────────────────────────────────────

    def _describe(self, current, _previous=None):
        self.detail.setText((current.data(Qt.ItemDataRole.UserRole) or '') if current else '')

    def _tile_ready(self, figure_id: int, index: int, image: QImage):
        if figure_id != self._figure_id or index >= self.grid.count():
            return                              # a crop for the figure before this one
        self.grid.item(index).setIcon(QIcon(QPixmap.fromImage(image)))

    def _ensure_worker(self) -> _TileWorker:
        if self._worker is None:
            self._worker = _TileWorker(self._pdf_path, self)
            self._worker.ready.connect(self._tile_ready)
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


def _entry_text(p) -> str:
    parts = []
    for label, description, specimen in p.entries:
        text = f'{label} — {description}' if description else label
        if specimen and specimen not in description:
            text += f' ({specimen})'
        parts.append(text)
    if p.annotation:
        parts.insert(0, 'Annotation (scale bar, key), not a specimen.')
    elif p.confidence != 'high':
        parts.insert(0, f'Confidence: {p.confidence}.')
    return '\n'.join(parts)
