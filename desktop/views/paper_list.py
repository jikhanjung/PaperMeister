"""Center paper list — flat table with status badges."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
)

from desktop.services import paper_service


COLUMNS = ['Status', 'Title', 'Authors', 'Year', 'Source']


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

        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.setColumnWidth(2, 260)
        self.setColumnWidth(4, 160)

        self.currentItemChanged.connect(self._on_selection_changed)

    # ── Loading ──────────────────────────────────────────────

    def load_library(self, key: str):
        try:
            rows = paper_service.list_by_library(key)
        except Exception as exc:
            rows = []
            self._show_error(f'Query failed: {exc}')
        self._populate(rows)

    def load_folder(self, folder_id: int):
        rows = paper_service.list_by_folder(folder_id)
        self._populate(rows)

    def load_source(self, source_id: int):
        rows = paper_service.list_by_source(source_id)
        self._populate(rows)

    def clear_rows(self):
        self.clear()

    def _populate(self, rows):
        self.clear()
        for row in rows:
            year = str(row.year) if row.year is not None else '—'
            title = row.title if not row.is_stub else f'— {row.title}'
            item = QTreeWidgetItem([
                row.status if row.status != 'none' else '—',
                title,
                row.authors or '—',
                year,
                row.source_name or '—',
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row.paper_id)
            if row.is_stub:
                font = item.font(1)
                font.setItalic(True)
                item.setFont(1, font)
            self.addTopLevelItem(item)

    def _show_error(self, msg: str):
        item = QTreeWidgetItem(['', msg, '', '', ''])
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
