"""Top-level QMainWindow for the new desktop app."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from desktop.components.search_bar import SearchBar
from desktop.components.sidebar import Rail
from desktop.components.status_bar import StatusBar
from desktop.services import library as library_svc
from desktop.theme.tokens import LAYOUT, SPACING
from desktop.views.detail_panel import DetailPanel
from desktop.views.paper_list import PaperListView
from desktop.views.source_nav import SourceNav


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PaperMeister')
        self.resize(1300, 820)
        self.setMinimumSize(LAYOUT['window.min.width'], LAYOUT['window.min.height'])

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())
        root_layout.addWidget(self._build_body(), 1)
        self.status_bar = StatusBar()
        root_layout.addWidget(self.status_bar)

        self.setCentralWidget(root)
        self._current_selection: tuple[str, object] | None = None
        self._process_window = None  # lazy-init; reuses frozen papermeister/ui ProcessWindow
        self._wire_events()
        self._load_initial()

    # ── Top bar ──────────────────────────────────────────────

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName('TopBar')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(SPACING['md'], 0, SPACING['md'], 0)
        layout.setSpacing(SPACING['md'])

        title = QLabel('PaperMeister')
        title.setObjectName('AppTitle')
        layout.addWidget(title)

        layout.addSpacing(SPACING['lg'])

        self.search_bar = SearchBar()
        self.search_bar.setMinimumWidth(420)
        layout.addWidget(self.search_bar, 1)

        return bar

    # ── Body ─────────────────────────────────────────────────

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = Rail()
        layout.addWidget(self.rail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        self.source_nav = SourceNav()
        self.source_nav.setMinimumWidth(LAYOUT['sourcenav.min'])

        self.paper_list = PaperListView()

        self.detail_panel = DetailPanel()
        self.detail_panel.setMinimumWidth(LAYOUT['detail.min'])

        splitter.addWidget(self.source_nav)
        splitter.addWidget(self.paper_list)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([LAYOUT['sourcenav.default'], 600, LAYOUT['detail.default']])

        layout.addWidget(splitter, 1)
        return body

    # ── Events ───────────────────────────────────────────────

    def _wire_events(self):
        self.rail.section_changed.connect(self._on_rail_section)
        self.rail.action_triggered.connect(self._on_rail_action)
        self.source_nav.selection_changed.connect(self._on_nav_selection)
        self.paper_list.paper_selected.connect(self.detail_panel.show_paper)
        self.detail_panel.apply_completed.connect(self._on_apply_completed)

    # ── Rail handlers ────────────────────────────────────────

    def _on_rail_section(self, section: str):
        """Persistent mode switch (library | search)."""
        if section == 'library':
            self.source_nav.setFocus()
            self.status_bar.set_task('Library')
        elif section == 'search':
            self.search_bar.setFocus()
            self.search_bar.selectAll()
            self.status_bar.set_task('Search')

    def _on_rail_action(self, action: str):
        """One-shot action (process | settings). Does not change persistent mode."""
        if action == 'process':
            self._open_process()
        elif action == 'settings':
            self._open_preferences()

    def _open_process(self):
        """Trigger OCR processing of all pending PaperFiles via the frozen ProcessWindow."""
        from papermeister.models import PaperFile
        from papermeister.ui.process_window import ProcessWindow

        pending_ids = [pf.id for pf in PaperFile.select(PaperFile.id).where(PaperFile.status == 'pending')]
        if not pending_ids:
            self.status_bar.set_task('No pending files to process')
            QMessageBox.information(self, 'Process', 'No pending files to process.')
            return

        resp = QMessageBox.question(
            self,
            'Process',
            f'Process {len(pending_ids)} pending file(s) via RunPod OCR?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        if self._process_window is None:
            self._process_window = ProcessWindow(self)
            self._process_window.processing_updated.connect(self._on_processing_updated)
        self._process_window.start(pending_ids)
        self.status_bar.set_task(f'Processing {len(pending_ids)} file(s)…')

    def _on_processing_updated(self):
        """Refresh counts and source tree after each processed file."""
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass

    def _open_preferences(self):
        """Open the frozen PreferencesDialog for RunPod / Zotero credentials."""
        from papermeister.ui.preferences_dialog import PreferencesDialog

        dlg = PreferencesDialog(self)
        dlg.exec()

    def _on_nav_selection(self, kind: str, value):
        self._current_selection = (kind, value)
        if kind == 'library':
            self.paper_list.load_library(str(value))
        elif kind == 'source':
            self.paper_list.load_source(int(value))
        elif kind == 'folder':
            self.paper_list.load_folder(int(value))

    def _on_apply_completed(self, paper_id: int, changed: bool, action: str):
        # Refresh counts and the library tree (needs_review bucket may change).
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass
        self.source_nav.refresh()
        self.status_bar.set_task(
            f'Applied paper #{paper_id} ({action})' if changed else f'No changes for paper #{paper_id}'
        )

    def _load_initial(self):
        try:
            total, pending, review = library_svc.corpus_counts()
        except Exception:
            total = pending = review = 0
        self.status_bar.set_counts(total, pending, review)
        self.status_bar.set_task('Idle')
        # Default: show All Files
        self.paper_list.load_library('all')
