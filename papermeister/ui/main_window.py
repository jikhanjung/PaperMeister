import html
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .process_window import ProcessWindow


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


class ZoteroCollectionSyncWorker(QThread):
    """Syncs Zotero collection tree to DB (no paper import)."""
    finished = pyqtSignal()

    def __init__(self, user_id, api_key):
        super().__init__()
        self.user_id = user_id
        self.api_key = api_key

    def run(self):
        from ..ingestion import get_or_create_zotero_source, sync_zotero_collections
        from ..zotero_client import ZoteroClient, load_cached_collections

        client = ZoteroClient(self.user_id, self.api_key)
        source = get_or_create_zotero_source(self.user_id)

        # Use cache first, then refresh from API
        cached = load_cached_collections()
        if cached:
            sync_zotero_collections(client, source, cached)

        fresh = client.get_collections()  # also saves cache
        sync_zotero_collections(client, source, fresh)
        self.finished.emit()


class ZoteroFetchItemsWorker(QThread):
    """Fetches item metadata (no PDFs) for a Zotero collection."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)  # new_count

    def __init__(self, user_id, api_key, folder_id):
        super().__init__()
        self.user_id = user_id
        self.api_key = api_key
        self.folder_id = folder_id

    def run(self):
        from ..ingestion import fetch_zotero_collection_items, get_or_create_zotero_source
        from ..models import Folder
        from ..zotero_client import ZoteroClient

        client = ZoteroClient(self.user_id, self.api_key)
        source = get_or_create_zotero_source(self.user_id)
        folder = Folder.get_by_id(self.folder_id)
        new_count = fetch_zotero_collection_items(
            client, source, folder,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
        self.finished.emit(new_count)


class ZoteroScanWorker(QThread):
    """Imports papers from selected Zotero collections."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, int)  # source_id, new_file_count

    def __init__(self, user_id, api_key, collections):
        super().__init__()
        self.user_id = user_id
        self.api_key = api_key
        self.collections = collections

    def run(self):
        from ..ingestion import (
            _get_or_create_zotero_folder,
            fetch_zotero_collection_items,
            get_or_create_zotero_source,
        )
        from ..zotero_client import ZoteroClient

        client = ZoteroClient(self.user_id, self.api_key)
        source = get_or_create_zotero_source(self.user_id)
        total_new = 0

        for col in self.collections:
            self.progress.emit(f'Importing collection: {col["name"]}')
            folder = _get_or_create_zotero_folder(source, col)
            new_count = fetch_zotero_collection_items(
                client, source, folder,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            total_new += new_count

        self.finished.emit(source.id, total_new)


# ── Main Window ──────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PaperMeister')
        self.setMinimumSize(1200, 700)
        self._scan_worker = None
        self._zotero_worker = None
        self._zotero_sync_worker = None
        self._process_window = ProcessWindow(self)
        self._process_window.processing_updated.connect(self._on_processing_updated)
        self._setup_ui()
        self._setup_menu()
        self._refresh_source_tree()
        self._update_status_counts()
        self._sync_zotero_collections()

    # ── Menu ─────────────────────────────────────────────────

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('&File')

        import_action = file_menu.addAction('Import &Folder...')
        import_action.setShortcut('Ctrl+I')
        import_action.triggered.connect(self._import_folder)

        zotero_action = file_menu.addAction('Import from &Zotero...')
        zotero_action.setShortcut('Ctrl+Z')
        zotero_action.triggered.connect(self._import_zotero)

        file_menu.addSeparator()

        prefs_action = file_menu.addAction('P&references...')
        prefs_action.triggered.connect(self._open_preferences)

        file_menu.addSeparator()

        process_action = file_menu.addAction('&Process Pending...')
        process_action.setShortcut('Ctrl+P')
        process_action.triggered.connect(self._process_pending)

        retry_action = file_menu.addAction('&Retry Failed...')
        retry_action.setShortcut('Ctrl+R')
        retry_action.triggered.connect(self._retry_failed)

        reindex_action = file_menu.addAction('Re&index from Cache...')
        reindex_action.triggered.connect(self._reindex_from_cache)

        reprocess_action = file_menu.addAction('Reprocess &All...')
        reprocess_action.triggered.connect(self._reprocess_all)

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

        self.statusBar().showMessage('Ready')

    # ── Source tree ───────────────────────────────────────────

    def _refresh_source_tree(self):
        from ..models import Source, Folder

        self.source_tree.clear()

        for source in Source.select().order_by(Source.name):
            icon = '\U0001f4c1' if source.source_type == 'directory' else '\U0001f4da'
            source_item = QTreeWidgetItem([f'{icon} {source.name}'])
            self.source_tree.addTopLevelItem(source_item)

            root_folders = list(
                Folder.select()
                .where(Folder.source == source, Folder.parent.is_null())
                .order_by(Folder.name)
            )

            # If single root folder matches source name, merge them
            if len(root_folders) == 1:
                root = root_folders[0]
                source_item.setData(0, Qt.ItemDataRole.UserRole, ('folder', root.id))
                children = Folder.select().where(Folder.parent == root).order_by(Folder.name)
                for child in children:
                    self._add_folder_item(source_item, child)
            else:
                source_item.setData(0, Qt.ItemDataRole.UserRole, ('source', source.id))
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
            status = 'no PDF'
            try:
                pf = paper.paperfile
                if pf:
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
            # Zotero folder with no papers yet → fetch from API
            if not papers:
                self._try_fetch_zotero_items(obj_id)

        self._load_papers(papers)
        self.statusBar().showMessage(f'{len(papers)} papers')

    def _try_fetch_zotero_items(self, folder_id):
        """If this is a Zotero folder, fetch its items from the API."""
        from ..models import Folder
        from ..preferences import get_pref

        folder = Folder.get_by_id(folder_id)
        if not folder.zotero_key:
            return

        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')
        if not user_id or not api_key:
            return

        if self._zotero_worker and self._zotero_worker.isRunning():
            return

        self.statusBar().showMessage(f'Fetching items from "{folder.name}"...')
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        self._zotero_worker = ZoteroFetchItemsWorker(user_id, api_key, folder_id)
        self._zotero_worker.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self._zotero_worker.finished.connect(self._on_zotero_fetch_finished)
        self._zotero_worker.start()

    def _on_zotero_fetch_finished(self, new_count):
        QApplication.restoreOverrideCursor()
        self._zotero_worker = None
        self.statusBar().showMessage(f'Fetched {new_count} new papers')
        self._update_status_counts()
        # Reload the currently selected folder
        current = self.source_tree.currentItem()
        if current:
            self._on_folder_selected(current, None)

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
            item = QTreeWidgetItem([
                paper.title or '(Untitled)',
                str(paper.year or ''),
                f'{len(matches)} hits',
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, paper.id)
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
        self.statusBar().showMessage(f'Scan complete: {new_count} new PDFs found')
        self._update_status_counts()

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
        if pending_ids:
            self._start_processing(pending_ids)

    # ── Processing actions ───────────────────────────────────

    def _process_pending(self):
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
        from ..models import PaperFile

        failed_ids = [
            pf.id for pf in
            PaperFile.select(PaperFile.id).where(PaperFile.status == 'failed')
        ]
        if not failed_ids:
            self.statusBar().showMessage('No failed files')
            return
        PaperFile.update(status='pending').where(PaperFile.status == 'failed').execute()
        self._start_processing(failed_ids)

    def _reindex_from_cache(self):
        from ..models import PaperFile, Passage
        from ..text_extract import OCR_JSON_DIR

        targets = []
        for pf in PaperFile.select().where(~PaperFile.path.endswith('.json')):
            has_passages = Passage.select().where(Passage.paper == pf.paper).exists()
            if has_passages:
                continue
            json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
            if os.path.exists(json_path):
                targets.append(pf.id)

        if not targets:
            self.statusBar().showMessage('No files to reindex')
            return
        PaperFile.update(status='pending').where(PaperFile.id.in_(targets)).execute()
        self._start_processing(targets)

    def _reprocess_all(self):
        from ..models import PaperFile

        all_ids = [pf.id for pf in PaperFile.select(PaperFile.id)]
        if not all_ids:
            self.statusBar().showMessage('No files to reprocess')
            return
        PaperFile.update(status='pending').execute()
        self._start_processing(all_ids)

    def _start_processing(self, paper_file_ids):
        self._process_window.start(paper_file_ids)

    # ── Zotero import ───────────────────────────────────────────

    def _open_preferences(self):
        from .preferences_dialog import PreferencesDialog
        dlg = PreferencesDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._sync_zotero_collections()

    def _sync_zotero_collections(self):
        """Sync Zotero collection tree to source panel (background)."""
        from ..preferences import get_pref
        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')
        if not user_id or not api_key:
            return
        if self._zotero_sync_worker and self._zotero_sync_worker.isRunning():
            return
        self._zotero_sync_worker = ZoteroCollectionSyncWorker(user_id, api_key)
        self._zotero_sync_worker.finished.connect(self._on_zotero_sync_done)
        self._zotero_sync_worker.start()

    def _on_zotero_sync_done(self):
        self._zotero_sync_worker = None
        self._refresh_source_tree()

    def _import_zotero(self):
        from ..preferences import get_pref

        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')

        if not user_id or not api_key:
            from .preferences_dialog import PreferencesDialog
            dlg = PreferencesDialog(self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            user_id = get_pref('zotero_user_id', '')
            api_key = get_pref('zotero_api_key', '')
            if not user_id or not api_key:
                return

        from .zotero_import_dialog import ZoteroImportDialog
        dlg = ZoteroImportDialog(user_id, api_key, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        collections = dlg.selected_collections
        if not collections:
            return

        self.statusBar().showMessage(f'Importing {len(collections)} Zotero collection(s)...')
        self._zotero_worker = ZoteroScanWorker(user_id, api_key, collections)
        self._zotero_worker.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        self._zotero_worker.finished.connect(self._on_zotero_scan_finished)
        self._zotero_worker.start()

    def _on_zotero_scan_finished(self, source_id, new_count):
        self._zotero_worker = None
        self._refresh_source_tree()
        self.statusBar().showMessage(f'Zotero import complete: {new_count} new PDFs')
        self._update_status_counts()

        if new_count > 0:
            self._start_processing_source(source_id)

    def _on_processing_updated(self):
        # Refresh paper list and status counts
        current = self.source_tree.currentItem()
        if current:
            self._on_folder_selected(current, None)
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
