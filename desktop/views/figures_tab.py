"""The Figures tab — a paper by its figures and plates (P16 Phase 5).

One block per figure, in page order: the whole figure or plate with a box on
every sub-figure the split stage (③) found, and under it the caption
entries the linking stage (②) cut. The cursor ties the two: over a box, its
entry lights; over an entry, its box fills. A click keeps the pairing.

A figure without panels shows its entries under a plain crop; one without
entries shows its caption. The rows the Text tab lists are the same rows —
this tab is the same paper read by its figures instead of its text.

Rendering is lazy and bounded. A plate volume has a hundred figures and a
page render is a tenth of a second and a few megabytes; the tab renders the
blocks in and near the viewport as it scrolls, and lets go of crops far
above or below, so scrolling a 121-plate paper never holds it all in memory.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.components.figure_canvas import HIGHLIGHT, CropWorker, FigureCanvas, entry_text
from desktop.services import paper_service
from desktop.theme.tokens import COLORS_DARK, FONT, SPACING

#: The figure fills the tab's width (re-fitted on resize); a plate taller
#: than this is scaled down, so a page-tall plate stays one screen.
FIGURE_MAX_WIDTH = 760           # until the tab is laid out; then the viewport decides
FIGURE_MAX_HEIGHT = 1400
#: Crops are rendered a little wider than shown, so a hidpi screen stays sharp.
OVERSAMPLE = 1.5
#: Blocks this far outside the viewport are rendered ahead; farther ones are let go.
PREFETCH = 600
RELEASE = 2400
#: Crops kept at once, whatever the scroll position.
MAX_LIVE = 10
_ROW_HEIGHT = 22


class _EntryList(QListWidget):
    """The caption entries under a figure; hover and click name a row."""

    row_hovered = pyqtSignal(int)      # row, or -1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('EntryList')
        self.setMouseTracking(True)
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizeAdjustPolicy(QListWidget.SizeAdjustPolicy.AdjustToContents)
        self.entered.connect(lambda index: self.row_hovered.emit(index.row()))
        self._hovered: int | None = None

    def mark_hover(self, row: int | None) -> None:
        """Fill the row the cursor's box belongs to."""
        if self._hovered is not None and self._hovered < self.count():
            self.item(self._hovered).setBackground(QColor(0, 0, 0, 0))
        self._hovered = row
        if row is not None and row < self.count():
            fill = QColor(HIGHLIGHT)
            fill.setAlpha(60)
            self.item(row).setBackground(fill)
            self.scrollToItem(self.item(row))

    def leaveEvent(self, event):
        self.row_hovered.emit(-1)
        super().leaveEvent(event)

    def fit_height(self) -> None:
        """Tall enough for every row; the tab scrolls, the list does not."""
        height = sum(self.sizeHintForRow(i) for i in range(self.count())) + 2 * self.frameWidth() + 4
        self.setFixedHeight(max(_ROW_HEIGHT, height))


class FigureBlock(QFrame):
    """One figure: the canvas with its boxes, the entries under it."""

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setObjectName('FigureBlock')
        self.row = row
        self.figure_id = row.id
        self.panel_set = paper_service.load_panels(row.id) if row.panels else None
        self._panel_of_entry: dict[int, int] = {}
        self._entry_of_panel: dict[int, int] = {}
        self.requested = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING['lg'], 0, SPACING['lg'])
        layout.setSpacing(SPACING['sm'])

        title = QLabel(self._title())
        title.setStyleSheet(f"font-weight: {FONT['weight.bold']}; font-size: {FONT['size.md']}px;")
        layout.addWidget(title)

        self.canvas = FigureCanvas(max_width=FIGURE_MAX_WIDTH, max_height=FIGURE_MAX_HEIGHT)
        x0, y0, x1, y1 = row.bbox_page_1000
        self.canvas.set_figure(None, [], max(1, x1 - x0) / max(1, y1 - y0))
        self.canvas.panel_hovered.connect(self._panel_hovered)
        self.canvas.panel_clicked.connect(self._panel_clicked)
        layout.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignLeft)

        self.entries = _EntryList()
        self.entries.row_hovered.connect(self._entry_hovered)
        self.entries.currentRowChanged.connect(self._entry_chosen)
        self._fill_entries()
        # The caption two ways: cut into entries (what the boxes tie to) and
        # as printed (what to check them against). Both, on small tabs, when
        # there are entries; the printed one alone otherwise.
        self.caption_tabs: QTabWidget | None = None
        if self.entries.count() and row.caption:
            self.caption_tabs = QTabWidget()
            self.caption_tabs.setObjectName('CaptionTabs')
            self.caption_tabs.setDocumentMode(True)
            self.caption_tabs.addTab(self.entries, f'Entries ({self.entries.count()})')
            self.caption_tabs.addTab(self._caption_label(row.caption), 'Caption')
            self.caption_tabs.currentChanged.connect(lambda _i: self.caption_tabs.adjustSize())
            layout.addWidget(self.caption_tabs)
        elif self.entries.count():
            layout.addWidget(self.entries)
        elif row.caption:
            layout.addWidget(self._caption_label(row.caption))
        else:
            note = QLabel('No caption linked yet.')
            note.setStyleSheet(f"color: {COLORS_DARK['text.secondary']};")
            layout.addWidget(note)

    # ── content ───────────────────────────────────────────────

    @staticmethod
    def _caption_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(f"color: {COLORS_DARK['text.secondary']}; padding: {SPACING['xs']}px 0;")
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        return label

    def _title(self) -> str:
        r = self.row
        bits = [r.name or 'Unnamed figure', f'p. {r.page + 1}']
        if self.panel_set:
            bits.append(f'{len(self.panel_set.panels)} panels / {r.entries} entries')
            if self.panel_set.unmatched:
                bits.append(f'no panel for {", ".join(self.panel_set.unmatched)}')
        elif r.entries:
            bits.append(f'{r.entries} entries')
        if r.panel_state == 'failed':
            bits.append('panel split failed')
        return '  ·  '.join(bits)

    def _fill_entries(self) -> None:
        if self.panel_set:
            for index, p in enumerate(self.panel_set.panels):
                for label, description, specimen in p.entries:
                    self._add_entry(label, description, specimen, p.colour, index)
            for index, p in enumerate(self.panel_set.panels):
                if not p.entries:
                    what = 'annotation (scale bar, key)' if p.annotation else 'no caption entry'
                    self._add_entry(p.label or '?', what, '', p.colour, index)
            for label in self.panel_set.unmatched:
                self._add_entry(label, 'no panel — check the plate', '', COLORS_DARK['text.secondary'], None)
        elif self.row.entries:
            _name, entries = paper_service.load_entries(self.row.id)
            for label, description, specimen in entries:
                self._add_entry(label, description, specimen, None, None)
        self.entries.fit_height()

    def _add_entry(self, label, description, specimen, colour, panel_index):
        text = f'{label}  {description}' if description else label
        if specimen and specimen not in description:
            text += f'  ({specimen})'
        item = QListWidgetItem(text)
        item.setToolTip(text)
        if panel_index is None and colour:
            item.setForeground(QColor(colour))          # greyed: an entry no panel claims
        row = self.entries.count()
        self.entries.addItem(item)
        if panel_index is not None:
            self._panel_of_entry[row] = panel_index
            self._entry_of_panel.setdefault(panel_index, row)

    # ── the cursor ties box and entry ─────────────────────────

    def _panel_hovered(self, index: int):
        self.entries.mark_hover(self._entry_of_panel.get(index) if index >= 0 else None)

    def _panel_clicked(self, index: int):
        row = self._entry_of_panel.get(index)
        if row is None:
            self.canvas.light(index)
        else:
            self.entries.setCurrentRow(row)

    def _entry_hovered(self, row: int):
        self.canvas.hover(self._panel_of_entry.get(row) if row >= 0 else None)

    def _entry_chosen(self, row: int):
        self.canvas.light(self._panel_of_entry.get(row))

    # ── the crop ──────────────────────────────────────────────

    def crop_ready(self, image: QImage, box: tuple, page_size: tuple) -> None:
        cx0, cy0, cx1, cy1 = box
        page_w, page_h = page_size
        sx = image.width() / max(1, cx1 - cx0)
        sy = image.height() / max(1, cy1 - cy0)
        boxes = []
        for p in (self.panel_set.panels if self.panel_set else []):
            x0, y0, x1, y1 = p.bbox_page_1000
            boxes.append((QRectF((x0 * page_w / 1000 - cx0) * sx, (y0 * page_h / 1000 - cy0) * sy,
                                 (x1 - x0) * page_w / 1000 * sx, (y1 - y0) * page_h / 1000 * sy),
                          p.label, p.colour))
        lit = self.canvas.lit()
        self.canvas.set_figure(image, boxes, image.width() / max(1, image.height()),
                               [entry_text(p) for p in (self.panel_set.panels if self.panel_set else [])])
        self.canvas.light(lit)

    def release(self) -> None:
        """Let the crop go; the block keeps its shape and can be rendered again."""
        if self.canvas._image is not None:
            x0, y0, x1, y1 = self.row.bbox_page_1000
            lit = self.canvas.lit()
            self.canvas.set_figure(None, [], max(1, x1 - x0) / max(1, y1 - y0))
            self.canvas.light(lit)
        self.requested = False


class FiguresTab(QScrollArea):
    """A paper's figures, one block each, rendered as they come into view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('FiguresTab')
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)   # a stable width to fit to
        self._host = QWidget()
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(SPACING['lg'], 0, SPACING['lg'], SPACING['lg'])
        self._layout.setSpacing(0)
        self.setWidget(self._host)
        self._blocks: dict[int, FigureBlock] = {}
        self._order: list[int] = []                 # figure ids, page order
        self._live: list[int] = []                  # figure ids holding a crop, oldest first
        self._worker: CropWorker | None = None
        self._pdf_path: str | None = None
        self._scrolled = QTimer(self)
        self._scrolled.setSingleShot(True)
        self._scrolled.setInterval(120)
        self._scrolled.timeout.connect(self._render_visible)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._scrolled.start())
        self._fitted_width = 0
        self._resized = QTimer(self)
        self._resized.setSingleShot(True)
        self._resized.setInterval(200)
        self._resized.timeout.connect(self._refit)

    def set_paper(self, paper_id: int, pdf_path: str | None) -> int:
        """Build the blocks. Returns how many figures the paper has."""
        self._stop_worker()
        self._pdf_path = pdf_path
        for block in self._blocks.values():
            block.setParent(None)
            block.deleteLater()
        self._blocks.clear()
        self._order.clear()
        self._live.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rows = paper_service.load_figures(paper_id)
        if not rows:
            empty = QLabel('No figures assembled for this paper yet — run OCR, then Process Figures.')
            empty.setStyleSheet(f"color: {COLORS_DARK['text.secondary']}; padding: {SPACING['lg']}px;")
            self._layout.addWidget(empty)
            self._layout.addStretch()
            return 0
        for row in rows:
            block = FigureBlock(row)
            self._blocks[row.id] = block
            self._order.append(row.id)
            self._layout.addWidget(block)
        self._layout.addStretch()
        if pdf_path:
            self._worker = CropWorker(pdf_path, self)
            self._worker.ready.connect(self._crop_ready)
            self._worker.start()
        self._fitted_width = 0
        QTimer.singleShot(0, self._refit)
        QTimer.singleShot(0, self._render_visible)
        return len(rows)

    def figure_width(self) -> int:
        """How wide a figure may be: the viewport minus the gutters."""
        width = self.viewport().width()
        if width < 100:
            return FIGURE_MAX_WIDTH
        return width - 2 * SPACING['lg'] - 4

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resized.start()

    def _refit(self) -> None:
        """Width-fit every block to the tab; crops already held are rescaled at
        paint, blocks not yet rendered will be rendered for the new width."""
        width = self.figure_width()
        if abs(width - self._fitted_width) < 8:
            return
        self._fitted_width = width
        for block in self._blocks.values():
            block.canvas.set_limits(width)
        self._scrolled.start()

    def show_figure(self, figure_id: int) -> None:
        block = self._blocks.get(figure_id)
        if block is not None:
            self.ensureWidgetVisible(block, 0, 0)

    # ── lazy rendering ────────────────────────────────────────

    def _render_visible(self) -> None:
        if self._worker is None or not self._blocks:
            return
        # Positions decide what to render, and the scroll area sizes the host to
        # its content one event-loop turn late; the first pass after a build
        # would otherwise see every block at the top and render them all.
        self._layout.activate()
        wanted = self._host.minimumSizeHint().height()
        if self._host.height() < wanted:
            self._host.resize(self._host.width(), wanted)
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        for fid in self._order:
            block = self._blocks[fid]
            y0 = block.y()
            y1 = y0 + block.height()
            near = y1 >= top - PREFETCH and y0 <= bottom + PREFETCH
            far = y1 < top - RELEASE or y0 > bottom + RELEASE
            if near and not block.requested:
                block.requested = True
                self._worker.request(fid, block.row.page, block.row.bbox_page_1000,
                                     int(self.figure_width() * OVERSAMPLE))
            elif far and block.canvas._image is not None:
                block.release()
                if fid in self._live:
                    self._live.remove(fid)

    def _crop_ready(self, figure_id: int, image: QImage, box: tuple, page_size: tuple) -> None:
        block = self._blocks.get(figure_id)
        if block is None or not block.requested:
            return
        block.crop_ready(image, box, page_size)
        self._live.append(figure_id)
        # Bound what is held: the oldest crops go first, but never one on screen.
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        while len(self._live) > MAX_LIVE:
            victim = next((f for f in self._live
                           if self._blocks[f].y() + self._blocks[f].height() < top - PREFETCH
                           or self._blocks[f].y() > bottom + PREFETCH), None)
            if victim is None:
                break
            self._live.remove(victim)
            self._blocks[victim].release()

    # ── lifetime ──────────────────────────────────────────────

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
