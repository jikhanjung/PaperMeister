"""Cited Works browser (P11 Phase 2).

Lists external works (papers we do NOT hold) ranked by how many of our papers
cite them — i.e. acquisition candidates ("frequently cited but not in library").
Selecting a work shows the library papers that cite it; double-clicking one of
those emits `open_paper` so the main window can navigate to it.
"""
from typing import ClassVar

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.services import paper_service


class CitedWorksWindow(QWidget):
    open_paper = pyqtSignal(int)  # a citing library paper was activated

    _COLS: ClassVar = ['Cites', 'Year', 'Authors', 'Title', 'In', 'DOI']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cited Works — external papers your library references')
        self.setMinimumSize(960, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._current_work_id: int | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── Controls row ──
        controls = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('Filter by title or author…')
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._reload)
        controls.addWidget(self.filter_edit, 1)

        self.freq_only = QCheckBox('Only frequently cited (≥2)')
        self.freq_only.setChecked(True)
        self.freq_only.toggled.connect(self._reload)
        controls.addWidget(self.freq_only)

        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self._reload)
        controls.addWidget(refresh)
        layout.addLayout(controls)

        # ── Splitter: works table | citing-papers list ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Title
        for c in (0, 1, 2, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_work_selected)
        splitter.addWidget(self.table)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(8, 0, 0, 0)
        self.cociters_header = QLabel('Select a work to see who cites it')
        self.cociters_header.setStyleSheet('font-weight: bold;')
        self.cociters_header.setWordWrap(True)
        rlay.addWidget(self.cociters_header)
        self.cociters = QListWidget()
        self.cociters.itemActivated.connect(self._on_cociter_activated)
        self.cociters.itemDoubleClicked.connect(self._on_cociter_activated)
        rlay.addWidget(self.cociters, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([680, 280])
        layout.addWidget(splitter, 1)

        self.status = QLabel('')
        self.status.setStyleSheet('color: #888; font-size: 12px;')
        layout.addWidget(self.status)

    # ── Loading ──────────────────────────────────────────────

    def load(self):
        """(Re)load from the DB — call each time the window is opened."""
        self._reload()

    def _reload(self):
        min_cites = 2 if self.freq_only.isChecked() else 1
        rows = paper_service.top_cited_works(
            limit=500, min_cites=min_cites, query=self.filter_edit.text())
        self.table.setRowCount(0)
        self.cociters.clear()
        self._current_work_id = None
        self.cociters_header.setText('Select a work to see who cites it')
        for r in rows:
            self._add_row(r)
        if not rows:
            self.status.setText(
                'No external works yet. Extract references first — '
                '(right-click a paper / folder / My Library → "Extract References").'
            )
        else:
            self.status.setText(f'{len(rows)} work(s)')

    def _add_row(self, r):
        row = self.table.rowCount()
        self.table.insertRow(row)
        cites = QTableWidgetItem(str(r.cite_count))
        cites.setData(Qt.ItemDataRole.UserRole, r.work_id)
        cites.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, cites)
        self.table.setItem(row, 1, QTableWidgetItem(str(r.year) if r.year else ''))
        self.table.setItem(row, 2, QTableWidgetItem(r.authors))
        self.table.setItem(row, 3, QTableWidgetItem(r.title))
        self.table.setItem(row, 4, QTableWidgetItem(r.container))
        self.table.setItem(row, 5, QTableWidgetItem(r.doi))

    # ── Selection ────────────────────────────────────────────

    def _on_work_selected(self):
        items = self.table.selectedItems()
        if not items:
            return
        work_id = self.table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if work_id is None or work_id == self._current_work_id:
            return
        self._current_work_id = work_id
        cociters = paper_service.load_work_cociters(work_id)
        self.cociters.clear()
        self.cociters_header.setText(
            f'Cited by {len(cociters)} paper(s) in your library '
            '(double-click to open)')
        for c in cociters:
            label = c.title or f'paper #{c.paper_id}'
            bits = [b for b in (c.authors, str(c.year) if c.year else '') if b]
            if bits:
                label += '  ·  ' + ' · '.join(bits)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c.paper_id)
            self.cociters.addItem(item)

    def _on_cociter_activated(self, item: QListWidgetItem):
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self.open_paper.emit(int(pid))
