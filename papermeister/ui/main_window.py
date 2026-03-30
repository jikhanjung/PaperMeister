import html
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ── Workers ──────────────────────────────────────────────────

class ScanWorker(QThread):
    """Scans a directory, creates Source/Folder/PaperFile records (fast, no OCR)."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, int)  # source_id, new_file_count

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        from ..ingestion import import_source_directory
        source, new_files = import_source_directory(
            self.folder_path,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
        self.finished.emit(source.id, len(new_files))


class ProcessWorker(QThread):
    """OCR-processes all pending PaperFiles."""
    progress = pyqtSignal(str)
    file_done = pyqtSignal(int)  # paper_file.id
    finished = pyqtSignal(int, int)  # processed, failed

    def __init__(self, paper_file_ids):
        super().__init__()
        self.paper_file_ids = paper_file_ids

    def run(self):
        from ..models import PaperFile
        from ..text_extract import process_paper_file

        processed = failed = 0
        total = len(self.paper_file_ids)
        for i, pf_id in enumerate(self.paper_file_ids):
            pf = PaperFile.get_by_id(pf_id)
            name = os.path.basename(pf.path)
            self.progress.emit(f'OCR [{i + 1}/{total}]: {name}')
            try:
                process_paper_file(
                    pf,
                    ocr_progress_callback=lambda c, t, msg: self.progress.emit(msg),
                )
                processed += 1
            except Exception as e:
                pf.status = 'failed'
                pf.save()
                failed += 1
                self.progress.emit(f'Failed: {name} — {e}')
            self.file_done.emit(pf_id)

        self.finished.emit(processed, failed)


# ── Main Window ──────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PaperMeister')
        self.setMinimumSize(1200, 700)
        self._scan_worker = None
        self._process_worker = None
        self._setup_ui()
        self._setup_menu()
        self._refresh_source_tree()
        self._update_status_counts()

    # ── Menu ─────────────────────────────────────────────────

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('&File')

        import_action = file_menu.addAction('Import &Folder...')
        import_action.setShortcut('Ctrl+I')
        import_action.triggered.connect(self._import_folder)

        process_action = file_menu.addAction('&Process Pending...')
        process_action.setShortcut('Ctrl+P')
        process_action.triggered.connect(self._process_pending)

        retry_action = file_menu.addAction('&Retry Failed...')
        retry_action.setShortcut('Ctrl+R')
        retry_action.triggered.connect(self._retry_failed)

        file_menu.addSeparator()

        exit_action = file_menu.addAction('E&xit')
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)

    # ── Layout ───────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Search papers...')
        self.search_input.returnPressed.connect(self._do_search)
        search_btn = QPushButton('Search')
        search_btn.clicked.connect(self._do_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        # 3-pane splitter: source tree | paper list | detail view
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane: source / folder tree
        self.source_tree = QTreeWidget()
        self.source_tree.setHeaderLabel('Sources')
        self.source_tree.currentItemChanged.connect(self._on_folder_selected)
        splitter.addWidget(self.source_tree)

        # Middle pane: paper list
        self.paper_list = QTreeWidget()
        self.paper_list.setHeaderLabels(['Title', 'Year', 'Status'])
        self.paper_list.setColumnWidth(0, 350)
        self.paper_list.setColumnWidth(1, 50)
        self.paper_list.header().setStretchLastSection(True)
        self.paper_list.currentItemChanged.connect(self._on_paper_selected)
        splitter.addWidget(self.paper_list)

        # Right pane: detail view
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        splitter.addWidget(self.detail_view)

        splitter.setSizes([250, 400, 550])
        layout.addWidget(splitter)

        # Progress bar in status bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel()
        self.statusBar().addPermanentWidget(self.progress_label)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage('Ready')

    # ── Source tree ───────────────────────────────────────────

    def _refresh_source_tree(self):
        from ..models import Source, Folder

        self.source_tree.clear()

        for source in Source.select().order_by(Source.name):
            icon = '\U0001f4c1' if source.source_type == 'directory' else '\U0001f4da'
            source_item = QTreeWidgetItem([f'{icon} {source.name}'])
            source_item.setData(0, Qt.ItemDataRole.UserRole, ('source', source.id))
            self.source_tree.addTopLevelItem(source_item)

            # Add root folders (parent is None)
            root_folders = (
                Folder.select()
                .where(Folder.source == source, Folder.parent.is_null())
                .order_by(Folder.name)
            )
            for folder in root_folders:
                self._add_folder_item(source_item, folder)

            source_item.setExpanded(True)

    def _add_folder_item(self, parent_item, folder):
        from ..models import Folder

        folder_item = QTreeWidgetItem([folder.name])
        folder_item.setData(0, Qt.ItemDataRole.UserRole, ('folder', folder.id))
        parent_item.addChild(folder_item)

        children = Folder.select().where(Folder.parent == folder).order_by(Folder.name)
        for child in children:
            self._add_folder_item(folder_item, child)

    # ── Paper list ───────────────────────────────────────────

    def _load_papers(self, papers):
        self.paper_list.clear()
        self.detail_view.clear()
        for paper in papers:
            status = ''
            try:
                pf = paper.paperfile
                status = pf.status
            except Exception:
                pass
            item = QTreeWidgetItem([
                paper.title or '(Untitled)',
                str(paper.year or ''),
                status,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, paper.id)
            self.paper_list.addTopLevelItem(item)

    def _on_folder_selected(self, current, _previous):
        if not current:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        from ..search import get_papers_in_folder, get_papers_in_source

        kind, obj_id = data
        if kind == 'source':
            papers = get_papers_in_source(obj_id)
        else:
            papers = get_papers_in_folder(obj_id)

        self._load_papers(papers)
        self.statusBar().showMessage(f'{len(papers)} papers')

    # ── Paper detail ─────────────────────────────────────────

    def _on_paper_selected(self, current, _previous):
        if not current:
            return
        paper_id = current.data(0, Qt.ItemDataRole.UserRole)
        if paper_id is None:
            return

        from ..models import Author, Paper
        from ..search import get_paper_passages

        paper = Paper.get_by_id(paper_id)
        authors = Author.select().where(Author.paper == paper).order_by(Author.order)
        author_str = ', '.join(a.name for a in authors)

        parts = [f'<h2>{html.escape(paper.title)}</h2>']
        if author_str:
            parts.append(f'<p><b>Authors:</b> {html.escape(author_str)}</p>')
        if paper.year:
            parts.append(f'<p><b>Year:</b> {paper.year}</p>')
        if paper.journal:
            parts.append(f'<p><b>Journal:</b> {html.escape(paper.journal)}</p>')
        if paper.doi:
            parts.append(f'<p><b>DOI:</b> {html.escape(paper.doi)}</p>')

        passages = get_paper_passages(paper_id)
        if passages:
            parts.append('<hr><h3>Full Text</h3>')
            current_page = None
            for p in passages:
                if p.page != current_page:
                    current_page = p.page
                    parts.append(f'<h4>Page {p.page}</h4>')
                parts.append(f'<p>{html.escape(p.text)}</p>')

        self.detail_view.setHtml('\n'.join(parts))

    # ── Search ───────────────────────────────────────────────

    def _do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        from ..search import search

        results = search(query)

        self.paper_list.clear()
        self.detail_view.clear()
        for result in results:
            paper = result['paper']
            matches = result['matches']
            snippets = '; '.join(
                f'p.{m["page"]}' for m in matches[:3]
            )
            item = QTreeWidgetItem([
                paper.title or '(Untitled)',
                str(paper.year or ''),
                f'{len(matches)} hits',
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, paper.id)
            # Store matches for detail display
            item.setData(0, Qt.ItemDataRole.UserRole + 1, result)
            self.paper_list.addTopLevelItem(item)

        self.statusBar().showMessage(f'Found {len(results)} papers for "{query}"')

    # ── Import ───────────────────────────────────────────────

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Folder to Import')
        if not folder:
            return

        self.statusBar().showMessage(f'Scanning {folder}...')
        self._scan_worker = ScanWorker(folder)
        self._scan_worker.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self, source_id, new_count):
        self._scan_worker = None
        self._refresh_source_tree()
        self.statusBar().showMessage(
            f'Scan complete: {new_count} new PDFs found'
        )
        self._update_status_counts()

        # Auto-start OCR for pending files
        if new_count > 0:
            self._start_processing_source(source_id)

    def _start_processing_source(self, source_id):
        from ..models import Folder, Paper, PaperFile

        pending_ids = [
            pf.id for pf in (
                PaperFile.select(PaperFile.id)
                .join(Paper)
                .join(Folder)
                .where(Folder.source_id == source_id, PaperFile.status == 'pending')
            )
        ]
        if not pending_ids:
            return
        self._start_processing(pending_ids)

    def _process_pending(self):
        """Process all pending files across all sources."""
        from ..models import PaperFile

        pending_ids = [
            pf.id for pf in
            PaperFile.select(PaperFile.id).where(PaperFile.status == 'pending')
        ]
        if not pending_ids:
            self.statusBar().showMessage('No pending files')
            return
        self._start_processing(pending_ids)

    def _retry_failed(self):
        """Reset failed files to pending and reprocess."""
        from ..models import PaperFile

        failed = PaperFile.select().where(PaperFile.status == 'failed')
        failed_ids = [pf.id for pf in failed]
        if not failed_ids:
            self.statusBar().showMessage('No failed files')
            return
        PaperFile.update(status='pending').where(PaperFile.status == 'failed').execute()
        self.statusBar().showMessage(f'Retrying {len(failed_ids)} failed files...')
        self._start_processing(failed_ids)

    def _start_processing(self, paper_file_ids):
        if self._process_worker and self._process_worker.isRunning():
            self.statusBar().showMessage('Processing already in progress')
            return

        self._process_total = len(paper_file_ids)
        self._process_done = 0
        self.progress_bar.setRange(0, self._process_total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f'0/{self._process_total}')

        self._process_worker = ProcessWorker(paper_file_ids)
        self._process_worker.progress.connect(
            lambda msg: self.statusBar().showMessage(msg)
        )
        self._process_worker.file_done.connect(self._on_file_processed)
        self._process_worker.finished.connect(self._on_processing_finished)
        self._process_worker.start()

    def _on_file_processed(self, paper_file_id):
        self._process_done += 1
        self.progress_bar.setValue(self._process_done)
        self.progress_label.setText(f'{self._process_done}/{self._process_total}')

        # Refresh current paper list to update status column
        current = self.source_tree.currentItem()
        if current:
            self._on_folder_selected(current, None)
        self._update_status_counts()

    def _on_processing_finished(self, processed, failed):
        self._process_worker = None
        self.progress_bar.setVisible(False)
        self.progress_label.setText('')
        self.statusBar().showMessage(
            f'Processing complete: {processed} processed, {failed} failed'
        )
        self._update_status_counts()

    # ── Status ───────────────────────────────────────────────

    def _update_status_counts(self):
        from ..models import Paper, PaperFile, Passage

        total = Paper.select().count()
        pending = PaperFile.select().where(PaperFile.status == 'pending').count()
        passages = Passage.select().count()

        parts = [f'Papers: {total}']
        if pending:
            parts.append(f'Pending: {pending}')
        parts.append(f'Passages: {passages}')
        self.statusBar().showMessage(' | '.join(parts))
