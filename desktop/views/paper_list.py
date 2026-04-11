"""Center paper list — flat table with status badges."""
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from desktop.services import paper_service
from desktop.theme.tokens import COLORS_DARK, FONT, RADIUS


COLUMNS = ['Status', 'Authors', 'Title', 'Year']


_STATUS_STYLES: dict[str, tuple[QColor, QColor, str]] = {
    # key: (background, foreground, short_label)
    'processed': (QColor(74, 222, 128, 40),  QColor(74, 222, 128),  'done'),
    'pending':   (QColor(107, 112, 128, 46), QColor(160, 165, 180), 'wait'),
    'failed':    (QColor(248, 113, 113, 38), QColor(248, 113, 113), 'err'),
    'review':    (QColor(251, 191, 36, 38),  QColor(251, 191, 36),  'rev'),
    'none':      (QColor(43, 47, 61, 0),     QColor(107, 112, 128), '—'),
}


class StatusPillDelegate(QStyledItemDelegate):
    """Renders the Status column as a small colored pill."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # Let the default paint handle the selection background first.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''  # we'll draw it ourselves
        widget = opt.widget
        style = widget.style() if widget is not None else opt.widget
        from PyQt6.QtWidgets import QApplication, QStyle
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        status_value = index.data(Qt.ItemDataRole.DisplayRole) or 'none'
        bg, fg, label = _STATUS_STYLES.get(status_value, _STATUS_STYLES['none'])

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Compute pill geometry — vertical center, padded horizontally.
        rect = option.rect
        pad_x = 6
        pad_y = 4
        font = QFont(painter.font())
        font.setPointSize(FONT['size.xs'])
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(label)
        text_h = metrics.height()
        pill_w = text_w + pad_x * 2
        pill_h = text_h + pad_y
        pill_x = rect.x() + 6
        pill_y = rect.y() + (rect.height() - pill_h) // 2
        pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)

        if label == '—':
            # Muted dash, no pill.
            painter.setPen(QPen(fg))
            painter.drawText(rect.adjusted(8, 0, 0, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             '—')
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(pill_rect, RADIUS['sm'], RADIUS['sm'])
            painter.setPen(QPen(fg))
            painter.drawText(pill_rect,
                             int(Qt.AlignmentFlag.AlignCenter),
                             label)
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(max(hint.width(), 56), max(hint.height(), 26))


class PaperListView(QTreeWidget):
    """Shows PaperRow list. `paper_selected` fires on selection changes."""

    paper_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PaperList')
        self.setRootIsDecorated(False)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(COLUMNS)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setIndentation(0)

        # All columns user-resizable (Interactive); Title stretches to fill.
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Status
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Authors
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)      # Title (fills)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # Year
        header.setStretchLastSection(False)
        self.setColumnWidth(0, 60)   # Status (small)
        self.setColumnWidth(1, 160)  # Authors (narrow)
        self.setColumnWidth(3, 64)   # Year

        self._pill_delegate = StatusPillDelegate(self)
        self.setItemDelegateForColumn(0, self._pill_delegate)

        self.currentItemChanged.connect(self._on_selection_changed)

    # ── Loading ──────────────────────────────────────────────

    def load_library(self, key: str):
        try:
            rows = paper_service.list_by_library(key)
        except Exception as exc:
            rows = []
            self._show_error(f'Query failed: {exc}')
        # In the 'needs_review' view, render the status column as 'review'
        # rather than the underlying PaperFile status so the badge reflects
        # the reason the row is here.
        override = 'review' if key == 'needs_review' else None
        self._populate(rows, status_override=override)

    def load_folder(self, folder_id: int):
        rows = paper_service.list_by_folder(folder_id)
        self._populate(rows)

    def load_source(self, source_id: int):
        rows = paper_service.list_by_source(source_id)
        self._populate(rows)

    def load_search(self, query: str):
        """Populate with FTS5 search results in BM25 rank order."""
        from desktop.services.search_service import search_papers
        try:
            rows = search_papers(query)
        except Exception as exc:
            self._show_error(f'Search failed: {exc}')
            return
        if not rows:
            self.clear()
            item = QTreeWidgetItem(['', '', f'No results for "{query}"', ''])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addTopLevelItem(item)
            return
        self._populate(rows)

    def clear_rows(self):
        self.clear()

    def _populate(self, rows, *, status_override: str | None = None):
        self.clear()
        for row in rows:
            year = str(row.year) if row.year is not None else '—'
            # Stub papers are conveyed via italic; no text prefix (it looked like
            # an empty-field placeholder next to real em-dash blanks).
            title = row.title
            status_cell = status_override or (row.status if row.status != 'none' else 'none')
            item = QTreeWidgetItem([
                status_cell,
                row.authors or '—',
                title,
                year,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row.paper_id)
            if row.is_stub:
                font = item.font(2)
                font.setItalic(True)
                item.setFont(2, font)
            self.addTopLevelItem(item)

    def _show_error(self, msg: str):
        item = QTreeWidgetItem(['', '', msg, ''])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.clear()
        self.addTopLevelItem(item)

    # ── Events ───────────────────────────────────────────────

    def _on_selection_changed(self, current, _prev):
        if current is None:
            return
        paper_id = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(paper_id, int):
            self.paper_selected.emit(paper_id)
