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
        self.resize(1500, 900)
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
        self._biblio_task = None     # single biblio extraction background task
        self._auto_biblio_queue = []  # [(paper_id, file_id), ...] queued after OCR
        self._biblio_window = None   # batch biblio progress window (lazy)
        self._biblio_guard = self._make_biblio_guard()  # server-down pause/resume
        self._refs_task = None        # single references extraction background task
        self._refs_queue = []         # [(paper_id, file_id), ...] for references parsing
        self._refs_window = None      # batch references progress window (lazy)
        self._refs_index = None       # held-paper resolution index (per-batch cache)
        self._refs_work_index = None  # external CitedWork dedup index (per-batch cache)
        self._refs_guard = self._make_refs_guard()  # server-down pause/resume
        self._cited_works_window = None  # Cited Works browser (lazy)
        self._network_window = None  # citation-network ego view (lazy)
        self._sync_worker = None  # ZoteroSyncWorker
        self._scan_worker = None   # local-folder import worker (ScanWorker)
        self._scan_window = None   # import progress window (lazy)
        self._wire_events()
        self._load_initial()
        self._sync_zotero()  # auto-sync on startup, like the old GUI

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
        self.rail.full_sync_triggered.connect(self._full_sync_zotero)
        self.source_nav.selection_changed.connect(self._on_nav_selection)
        self.source_nav.folder_action.connect(self._on_folder_action)
        self.source_nav.source_action.connect(self._on_source_action)
        self.paper_list.paper_selected.connect(self.detail_panel.show_paper)
        self.paper_list.folder_reveal_requested.connect(self.source_nav.reveal_folder)
        self.paper_list.context_action.connect(self._on_context_action)
        self.detail_panel.apply_completed.connect(self._on_apply_completed)
        self.detail_panel.reference_navigate.connect(self._on_reference_navigate)
        self.search_bar.returnPressed.connect(self._on_search_submitted)
        self.search_bar.textChanged.connect(self._on_search_text_changed)

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
        """One-shot action (import | sync | works | process | settings). Does not change persistent mode."""
        if action == 'import':
            self._import_folder()
        elif action == 'sync':
            self._sync_zotero()
        elif action == 'works':
            self._open_cited_works()
        elif action == 'process':
            self._open_process()
        elif action == 'settings':
            self._open_preferences()

    def _open_cited_works(self):
        """Open the Cited Works browser (external papers ranked by citations)."""
        from desktop.windows.cited_works_window import CitedWorksWindow
        if self._cited_works_window is None:
            self._cited_works_window = CitedWorksWindow(self)
            self._cited_works_window.open_paper.connect(self._on_cited_work_open_paper)
        self._cited_works_window.load()
        self._cited_works_window.show()
        self._cited_works_window.raise_()
        self._cited_works_window.activateWindow()

    def _on_cited_work_open_paper(self, paper_id: int):
        """A citing paper was activated in the Cited Works browser → reveal it."""
        self._on_reference_navigate(paper_id)
        self.raise_()
        self.activateWindow()

    # ── Local folder import ──────────────────────────────────

    def _import_folder(self):
        """Pick a local directory, scan it into a 'directory' Source in the
        background (filesystem walk + SHA256 dedup, no OCR), then offer to
        process the newly-found PDFs. Mirrors the old GUI's Import Folder flow.
        """
        from PyQt6.QtWidgets import QFileDialog

        if self._scan_worker and self._scan_worker.isRunning():
            self.status_bar.set_task('A folder import is already running…')
            return

        directory = QFileDialog.getExistingDirectory(
            self, 'Import Local Folder of PDFs', '',
            QFileDialog.Option.ShowDirsOnly,
        )
        if not directory:
            return
        self._start_scan(directory)

    def _start_scan(self, directory: str):
        """Run the background scan of `directory` with the progress window.
        Shared by first-time import and tab right-click 'Re-scan folder'
        (re-import is idempotent — get-or-create source + SHA256 dedup)."""
        from desktop.windows.scan_window import ScanWindow
        from desktop.workers.scan import ScanWorker

        if self._scan_window is None:
            self._scan_window = ScanWindow(self)
        self._scan_window.begin(directory)

        self.status_bar.set_task(f'Importing {directory}…')
        self._scan_worker = ScanWorker(directory)
        self._scan_worker.counted.connect(self._scan_window.set_total)
        self._scan_worker.progress.connect(self._scan_window.on_progress)
        self._scan_worker.done.connect(self._on_import_done)
        self._scan_worker.failed.connect(self._on_import_failed)
        self._scan_worker.start()

    def _on_import_done(self, result):
        source_id, source_name, new_count = result
        self._scan_worker = None
        if self._scan_window is not None:
            self._scan_window.finish(source_name, new_count)
        self.source_nav.refresh()
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass
        self.status_bar.set_task(f'Imported "{source_name}": {new_count} new PDF(s)')

        # Collect this source's pending PDFs (covers newly-added + any left
        # unprocessed from a previous import of the same folder).
        from papermeister.models import Folder, Paper, PaperFile
        pending_ids = [
            pf.id for pf in (
                PaperFile.select(PaperFile.id)
                .join(Paper).join(Folder, on=(Paper.folder == Folder.id))
                .where(
                    Folder.source == source_id,
                    PaperFile.status == 'pending',
                    PaperFile.path.endswith('.pdf'),
                )
            )
        ]
        if not pending_ids:
            if new_count == 0:
                msg = (f'"{source_name}" — every PDF was already in the database '
                       f'(e.g. already in Zotero).\nThey were linked into this '
                       f'folder (no duplicates) and now appear under its tab. '
                       f'Nothing new to OCR.')
            else:
                msg = f'Imported "{source_name}".\nNo pending PDFs to process.'
            QMessageBox.information(self, 'Import', msg)
            return

        resp = QMessageBox.question(
            self, 'Import',
            f'Imported "{source_name}" — {len(pending_ids)} PDF(s) pending.\n'
            f'Process them now via RunPod OCR?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        from papermeister.ui.process_window import ProcessWindow
        if self._process_window is None:
            self._process_window = ProcessWindow(self)
            self._process_window.processing_updated.connect(self._on_processing_updated)
            self._process_window.file_processed.connect(self._on_file_processed)
        self._process_window.start(pending_ids)
        self.status_bar.set_task(f'Processing {len(pending_ids)} file(s)…')

    def _on_import_failed(self, message: str):
        self._scan_worker = None
        if self._scan_window is not None:
            self._scan_window.fail(message)
        self.status_bar.set_task(f'Import failed: {message}')
        QMessageBox.warning(self, 'Import failed', message)

    # ── Zotero sync ──────────────────────────────────────────

    def _sync_zotero(self):
        """Sync Zotero collections + items in background with progress."""
        from papermeister.preferences import get_pref
        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')
        if not user_id or not api_key:
            self.status_bar.set_task('Zotero credentials not configured')
            return
        if self._sync_worker and self._sync_worker.isRunning():
            return  # button pulse already shows it's running

        from desktop.workers.zotero_sync import ZoteroSyncWorker
        self._sync_worker = ZoteroSyncWorker(user_id, api_key)
        self._sync_worker.progress.connect(self.status_bar.set_task)
        self._sync_worker.done.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_sync_failed)
        # Safety net: always stop animation when thread exits, even if
        # done/failed signals were missed (e.g. unhandled C++ exception).
        self._sync_worker.finished.connect(self._on_sync_finished)
        self.rail.set_sync_running(True)
        self._sync_worker.start()

    def _on_sync_finished(self):
        """QThread.finished — always fires when the thread exits."""
        self.rail.set_sync_running(False)
        self._sync_worker = None

    def _on_sync_done(self, result):
        self.source_nav.refresh()
        self._apply_current_selection()
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass
        parts = [f'{result["collections"]} col']
        if result['new']:
            parts.append(f'{result["new"]} new')
        if result['updated']:
            parts.append(f'{result["updated"]} updated')
        self.status_bar.set_task(f'Synced: {", ".join(parts)} (v{result["version"]})')

    def _on_sync_failed(self, message: str):
        self.status_bar.set_task(f'Sync failed: {message}')

    def _full_sync_zotero(self):
        """Force a full item re-fetch (right-click → Full Sync)."""
        if self._sync_worker and self._sync_worker.isRunning():
            return
        from papermeister.preferences import set_pref
        set_pref('paperfolder_needs_full_sync', True)
        self._sync_zotero()

    # ── Process / Settings ──────────────────────────────────

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
            self._process_window.file_processed.connect(self._on_file_processed)
        self._process_window.start(pending_ids)
        self.status_bar.set_task(f'Processing {len(pending_ids)} file(s)…')

    def _on_processing_updated(self):
        """Refresh counts and source tree after each processed file."""
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass

    def _on_file_processed(self, paper_file_id: int, status: str):
        """Update the pill for a single paper after OCR completes,
        then auto-run biblio extraction if OCR succeeded and the
        auto-extract pref is on."""
        from papermeister.models import PaperFile
        from papermeister.preferences import get_pref
        pf = PaperFile.get_or_none(PaperFile.id == paper_file_id)
        if not pf:
            return
        self.paper_list.update_status(pf.paper_id, status)
        if (
            status == 'processed'
            and pf.hash
            and get_pref('auto_biblio_extract', True)
        ):
            self._auto_biblio_queue.append((pf.paper_id, pf.id))
            # If a batch biblio window is open, keep its total in sync so the
            # post-OCR auto-biblio items don't overflow the progress count.
            if self._biblio_window and self._biblio_window.isVisible():
                self._biblio_window.add_total(1)
            self._drain_biblio_queue()

    def _on_context_action(self, action: str, paper_id: int, file_id: int):
        from papermeister.models import PaperFile
        if action in ('process', 'retry'):
            if not file_id:
                return
            force_ids = set()
            if action == 'retry':
                # Retrying a failed PDF — re-OCR ignoring any cached JSON.
                PaperFile.update(status='pending').where(PaperFile.id == file_id).execute()
                force_ids = {file_id}
            if self._process_window is None:
                from papermeister.ui.process_window import ProcessWindow
                self._process_window = ProcessWindow(self)
                self._process_window.processing_updated.connect(self._on_processing_updated)
                self._process_window.file_processed.connect(self._on_file_processed)
            self._process_window.start([file_id], force_ids=force_ids)
            self.status_bar.set_task('Processing 1 file…')
        elif action == 'open_pdf':
            self.detail_panel.show_paper(paper_id)
            self.detail_panel._tabs.setCurrentIndex(1)  # PDF tab
        elif action == 'extract_biblio':
            self._run_biblio_extraction(paper_id, file_id)
        elif action == 'extract_references':
            self._run_references_extraction(paper_id, file_id)
        elif action == 'review_biblio':
            self.detail_panel.show_paper(paper_id)
            self.detail_panel._tabs.setCurrentIndex(0)  # Metadata tab (includes biblio)
        elif action == 'network':
            self._open_network(paper_id)

    def _open_network(self, paper_id: int):
        """Open the citation-network ego view centered on this paper."""
        if getattr(self, '_network_window', None) is None:
            from desktop.windows.network_window import NetworkWindow
            self._network_window = NetworkWindow(self)
            self._network_window.open_paper.connect(self._on_reference_navigate)
        self._network_window.show_ego(paper_id)

    def _on_folder_action(self, action: str, folder_id: int):
        if action == 'process_folder':
            self._process_folder(folder_id)
        elif action == 'process_source':
            self._process_source(folder_id)  # value is a Source.id here
        elif action == 'extract_references_folder':
            self._run_references_scope(self._collect_folder_ids(folder_id), 'this folder')
        elif action == 'extract_references_source':
            self._run_references_scope(None, 'My Library (all)')
        elif action == 'upload_ocr_json':
            self._upload_ocr_json(folder_id)

    # ── Source (tab) actions ─────────────────────────────────

    def _on_source_action(self, action: str, source_id: int):
        if action == 'remove_source':
            self._remove_directory_source(source_id)
        elif action == 'rescan_source':
            self._rescan_directory_source(source_id)

    def _rescan_directory_source(self, source_id: int):
        """Re-import a directory source's folder to pick up newly-added PDFs.
        Idempotent: same Source (path-keyed), existing files dedup by hash."""
        if self._scan_worker and self._scan_worker.isRunning():
            self.status_bar.set_task('A folder import is already running…')
            return
        from papermeister.models import Source
        src = Source.get_or_none(Source.id == source_id)
        if src is None or src.source_type != 'directory':
            return
        import os
        if not src.path or not os.path.isdir(src.path):
            self.status_bar.set_task(f'Folder not found: {src.path}')
            QMessageBox.warning(
                self, 'Re-scan',
                f'The folder no longer exists or is not accessible:\n{src.path}',
            )
            return
        self._start_scan(src.path)

    def _remove_directory_source(self, source_id: int):
        """Remove an imported local-folder source. Pure-local PDFs are deleted
        from the DB (their OCR cache + files on disk are kept); PDFs also in
        Zotero are kept and just unlinked from this folder."""
        from papermeister.models import Source
        src = Source.get_or_none(Source.id == source_id)
        if src is None or src.source_type != 'directory':
            return

        resp = QMessageBox.question(
            self, 'Remove Local Folder',
            f'Remove the local folder source "{src.name}"?\n\n'
            f'• PDFs that exist only here are removed from the database '
            f'(OCR cache and the files on disk are kept).\n'
            f'• PDFs also in Zotero are kept — only their link to this folder '
            f'is dropped.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            from papermeister.ingestion import delete_directory_source
            deleted, unlinked = delete_directory_source(source_id)
        except Exception as exc:
            self.status_bar.set_task(f'Remove failed: {exc}')
            QMessageBox.warning(self, 'Remove failed', str(exc))
            return

        # The removed source's tab (and possibly the shown paper) is gone.
        self._current_selection = ('library', 'all')
        self.detail_panel._empty_state()
        self.source_nav.refresh()
        self._apply_current_selection()
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass
        self.status_bar.set_task(
            f'Removed "{src.name}": {deleted} deleted, {unlinked} unlinked'
        )

    @staticmethod
    def _collect_folder_ids(folder_id: int) -> list[int]:
        """Collect folder_id and all descendant folder IDs recursively."""
        from papermeister.models import Folder
        ids = [folder_id]
        children = list(Folder.select(Folder.id).where(Folder.parent == folder_id))
        for child in children:
            ids.extend(MainWindow._collect_folder_ids(child.id))
        return ids

    def _process_folder(self, folder_id: int):
        """Process a folder and its subfolders (OCR pending/failed + biblio)."""
        self._run_process_scope(self._collect_folder_ids(folder_id), 'this folder')

    def _process_source(self, source_id: int):
        """Process the whole library/source — every remaining PDF, any collection
        (and uncollected). Right-click 'My Library' → 'Process All'."""
        self._run_process_scope(None, 'My Library (all)')

    def _run_process_scope(self, folder_ids, scope_label: str):
        """Shared OCR + biblio processing over a scope.

        folder_ids None → whole library (no collection filter); otherwise restrict
        to PaperFiles whose paper is in one of those folders.

        Failed files (e.g. from a server restart mid-OCR) are retried — reset to
        'pending' before submission so the pill transitions cleanly.
        """
        from papermeister.models import Paper, PaperBiblio, PaperFile, PaperFolder

        def _ocr_rows():
            if folder_ids is None:
                return list(
                    PaperFile.select(PaperFile.id, PaperFile.status).where(
                        PaperFile.status.in_(['pending', 'failed']),
                        PaperFile.path.endswith('.pdf'),
                    )
                )
            return list(
                PaperFile.select(PaperFile.id, PaperFile.status)
                .join(Paper).join(PaperFolder, on=(PaperFolder.paper == Paper.id))
                .where(
                    PaperFolder.folder << folder_ids,
                    PaperFile.status.in_(['pending', 'failed']),
                    PaperFile.path.endswith('.pdf'),
                )
            )

        def _biblio_pdfs():
            if folder_ids is None:
                return (
                    PaperFile.select(PaperFile.id, PaperFile.paper)
                    .where(PaperFile.status == 'processed', PaperFile.path.endswith('.pdf'))
                    .order_by(PaperFile.paper.desc())
                )
            return (
                PaperFile.select(PaperFile.id, PaperFile.paper)
                .join(Paper).join(PaperFolder, on=(PaperFolder.paper == Paper.id))
                .where(
                    PaperFolder.folder << folder_ids,
                    PaperFile.status == 'processed',
                    PaperFile.path.endswith('.pdf'),
                )
                .order_by(Paper.id.desc())
            )

        rows = _ocr_rows()
        pending_ids = [r.id for r in rows if r.status == 'pending']
        failed_ids = [r.id for r in rows if r.status == 'failed']
        file_ids = pending_ids + failed_ids

        # OCR-completed PDFs whose paper has no biblio yet → biblio extraction.
        papers_with_biblio = {
            b.paper_id for b in PaperBiblio.select(PaperBiblio.paper).distinct()
        }
        queued_papers = {pid for pid, _ in self._auto_biblio_queue}
        biblio_targets: list[tuple[int, int]] = []
        seen_papers: set[int] = set()
        for pf in _biblio_pdfs():
            pid = pf.paper_id
            if pid in papers_with_biblio or pid in seen_papers or pid in queued_papers:
                continue
            seen_papers.add(pid)
            biblio_targets.append((pid, pf.id))

        # Process in the same order the PaperList currently shows (honours any
        # header-click sort). Papers not on screen keep the Paper.id-desc
        # fallback at the end. Stable sort preserves both.
        rank = {pid: i for i, pid in enumerate(self.paper_list.visible_paper_ids())}
        biblio_targets.sort(key=lambda t: rank.get(t[0], len(rank)))

        if not file_ids and not biblio_targets:
            self.status_bar.set_task(
                f'Nothing to do — OCR complete and biblio already extracted ({scope_label})'
            )
            return

        lines = []
        if pending_ids and failed_ids:
            lines.append(f'OCR: {len(pending_ids)} pending + retry {len(failed_ids)} failed PDF(s)')
        elif pending_ids:
            lines.append(f'OCR: {len(pending_ids)} pending PDF(s)')
        elif failed_ids:
            lines.append(f'OCR: retry {len(failed_ids)} failed PDF(s)')
        if biblio_targets:
            lines.append(f'Biblio extraction: {len(biblio_targets)} OCR-completed paper(s)')
        message = f'Process {scope_label}?\n' + '\n'.join(lines)

        resp = QMessageBox.question(
            self,
            'Process',
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Flip failed → pending so pill state matches what's about to happen.
        if failed_ids:
            PaperFile.update(status='pending').where(PaperFile.id.in_(failed_ids)).execute()
            for fid in failed_ids:
                pf = PaperFile.get_or_none(PaperFile.id == fid)
                if pf:
                    self.paper_list.update_status(pf.paper_id, 'pending')

        if file_ids:
            if self._process_window is None:
                from papermeister.ui.process_window import ProcessWindow
                self._process_window = ProcessWindow(self)
                self._process_window.processing_updated.connect(self._on_processing_updated)
                self._process_window.file_processed.connect(self._on_file_processed)
            # failed PDFs being retried → force re-OCR (ignore any cached JSON).
            self._process_window.start(file_ids, force_ids=set(failed_ids))

        # Queue biblio extraction for the already-OCR'd papers (runs through the
        # same serialized queue as the post-OCR auto-biblio path), with a
        # progress window so the user sees per-paper results.
        if biblio_targets:
            self._ensure_biblio_window()
            self._biblio_window.begin(len(biblio_targets))
            self._auto_biblio_queue.extend(biblio_targets)
            self._drain_biblio_queue()

        status_parts = []
        if file_ids:
            status_parts.append(f'OCR {len(file_ids)} file(s)')
        if biblio_targets:
            status_parts.append(f'biblio {len(biblio_targets)} paper(s)')
        self.status_bar.set_task('Processing: ' + ' + '.join(status_parts) + '…')

    def _upload_ocr_json(self, folder_id: int):
        """Upload OCR JSON files to Zotero for processed papers in a folder."""
        import os

        from desktop.workers.background import BackgroundTask
        from papermeister.models import Paper, PaperFile, PaperFolder
        from papermeister.text_extract import OCR_JSON_DIR

        # Find processed PDF files in this folder tree that have a hash and OCR JSON,
        # but no JSON sibling already uploaded.
        all_folder_ids = self._collect_folder_ids(folder_id)
        pdf_files = list(
            PaperFile.select(PaperFile, Paper)
            .join(Paper)
            .join(PaperFolder, on=(PaperFolder.paper == Paper.id))
            .where(
                PaperFolder.folder << all_folder_ids,
                PaperFile.status == 'processed',
                PaperFile.hash != '',
                PaperFile.zotero_key != '',
                ~PaperFile.path.endswith('.json'),
            )
        )

        # Filter: has OCR JSON on disk AND no JSON sibling yet — per PDF, not
        # per paper. A parent item with multiple PDF children needs one JSON
        # each; checking only "any JSON on this paper" would skip PDF #2/#3
        # incorrectly. JSON filename comes from ocr_json_filename().
        from papermeister.text_extract import ocr_json_filename
        existing_jsons = set()
        for jpf in PaperFile.select(PaperFile.paper, PaperFile.path).where(
            PaperFile.path.endswith('.json')
        ):
            existing_jsons.add((jpf.paper_id, jpf.path))

        todo = [
            pf for pf in pdf_files
            if (pf.paper_id, ocr_json_filename(pf)) not in existing_jsons
            and os.path.exists(os.path.join(OCR_JSON_DIR, ocr_json_filename(pf)))
        ]

        if not todo:
            self.status_bar.set_task('No OCR JSON files to upload in this folder')
            return

        resp = QMessageBox.question(
            self,
            'Upload OCR JSON',
            f'Upload {len(todo)} OCR JSON file(s) to Zotero?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        self.status_bar.set_task(f'Uploading {len(todo)} OCR JSON files…')

        def _do_upload():
            import time

            from papermeister.ingestion import hash_file
            from papermeister.preferences import get_pref
            from papermeister.zotero_client import ZoteroClient

            user_id = get_pref('zotero_user_id', '')
            api_key = get_pref('zotero_api_key', '')
            if not user_id or not api_key:
                return 0, 0, 'Zotero credentials not configured'

            client = ZoteroClient(user_id, api_key)
            success = 0
            failed = 0
            for pf in todo:
                json_name = ocr_json_filename(pf)
                json_path = os.path.join(OCR_JSON_DIR, json_name)
                try:
                    new_key = client.upload_sibling_attachment(pf.zotero_key, json_path)
                    if new_key:
                        PaperFile.create(
                            paper=pf.paper,
                            path=json_name,
                            hash=hash_file(json_path),
                            status='processed',
                            zotero_key=new_key,
                        )
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                time.sleep(0.1)
            return success, failed, None

        def _on_done(result):
            success, failed, err = result
            if err:
                self.status_bar.set_task(f'Upload failed: {err}')
            else:
                self.status_bar.set_task(f'Uploaded {success} OCR JSON, {failed} failed')

        task = BackgroundTask(_do_upload)
        task.done.connect(_on_done)
        task.failed.connect(lambda msg: self.status_bar.set_task(f'Upload failed: {msg}'))
        self._upload_task = task
        task.start()

    def _run_biblio_extraction(self, paper_id: int, file_id: int):
        """Run LLM biblio extraction for a single paper in background."""
        from papermeister.models import PaperFile
        from papermeister.preferences import get_pref

        pf = PaperFile.get_or_none(PaperFile.id == file_id) if file_id else None
        if not pf or not pf.hash:
            self.status_bar.set_task('No file hash — cannot extract biblio')
            return

        biblio_backend = get_pref('biblio_backend', 'claude')
        if biblio_backend == 'qwen':
            engine_label = 'Qwen3-14B (local server)'
        else:
            engine_label = 'Claude Sonnet 4.6 (Max plan quota)'

        resp = QMessageBox.question(
            self,
            'Extract Biblio',
            f'Extract bibliographic info using {engine_label}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Route through the shared serialized biblio queue (same path as the
        # folder batch) + show the progress window so a single extraction gets
        # the same per-paper result display.
        self._ensure_biblio_window()
        if (paper_id, file_id) not in self._auto_biblio_queue:
            self._auto_biblio_queue.append((paper_id, file_id))
            self._biblio_window.begin(1)  # shows window; extends total if a batch is live
        else:
            self._biblio_window.show()
            self._biblio_window.raise_()
        self.status_bar.set_task(f'Queued biblio extraction for paper {paper_id}…')
        self._drain_biblio_queue()

    def _biblio_title(self, paper_id: int) -> str:
        from papermeister.models import Paper
        p = Paper.get_or_none(Paper.id == paper_id)
        return (p.title[:55] if (p and p.title) else f'paper {paper_id}')

    def _biblio_pred_summary(self, pred, paper_id: int) -> str:
        """One-line 'title · first author et al. · year' from an extraction."""
        title = (pred.get('title') or '').strip() if isinstance(pred, dict) else ''
        if not title:
            title = self._biblio_title(paper_id)
        authors = (pred.get('authors') or []) if isinstance(pred, dict) else []
        year = pred.get('year') if isinstance(pred, dict) else None
        parts = [f'"{title[:55]}"']
        if authors:
            parts.append(authors[0] + (' et al.' if len(authors) > 1 else ''))
        if year:
            parts.append(str(year))
        return ' · '.join(parts)

    def _materialize_applied_biblio(self, paper_id: int, meta: dict):
        """The OCR JSON says biblio was applied, but there's no local PaperBiblio
        (e.g. the DB was rebuilt while the cached/Zotero JSON kept its
        papermeister_meta). Create a marker row from the Paper's current
        (already-applied) metadata so the paper drops out of biblio targets and
        shows 'done' instead of being re-listed and skipped forever."""
        import json

        from papermeister.models import Author, Paper, PaperBiblio, PaperFile
        paper = Paper.get_or_none(Paper.id == paper_id)
        if paper is None:
            return
        if PaperBiblio.select().where(
            (PaperBiblio.paper == paper)
            & (PaperBiblio.status.in_(['applied', 'auto_committed']))
        ).exists():
            return
        pdf = (
            PaperFile.select()
            .where((PaperFile.paper == paper) & (~PaperFile.path.endswith('.json')))
            .order_by(PaperFile.id)
            .first()
        )
        authors = [
            a.name for a in
            Author.select(Author.name).where(Author.paper == paper).order_by(Author.order)
        ]
        state = meta.get('biblio_state') or 'auto_committed'
        PaperBiblio.create(
            paper=paper,
            file_hash=(pdf.hash if pdf else ''),
            title=paper.title or '',
            authors_json=json.dumps(authors, ensure_ascii=False),
            year=paper.year,
            journal=paper.journal or '',
            doi=paper.doi or '',
            source=meta.get('biblio_source') or 'cross-machine-meta',
            status=state if state in ('applied', 'auto_committed') else 'auto_committed',
        )

    def _on_biblio_failed(self, paper_id: int, msg: str):
        """task.failed handler: record the failure in the progress window and
        advance the queue (so a failed extraction doesn't look like a stall)."""
        self.status_bar.set_task(f'Biblio failed for paper {paper_id}: {msg}')
        win = self._biblio_window if (self._biblio_window and self._biblio_window.isVisible()) else None
        if win:
            win.record(f'{self._biblio_title(paper_id)} — failed: {msg}', 'error')
        self._biblio_guard.record_fail()
        self._after_biblio(paper_id)

    def _after_biblio(self, paper_id: int):
        """Shared tail: refresh detail panel, drain queue, finish window."""
        if self.detail_panel._current_paper_id == paper_id:
            self.detail_panel.show_paper(paper_id)
        self._drain_biblio_queue()
        win = self._biblio_window
        if (
            win and win.isVisible()
            and not self._auto_biblio_queue
            and not (self._biblio_task and self._biblio_task.isRunning())
        ):
            win.finish()

    def _on_biblio_extracted(self, paper_id: int, result):
        win = self._biblio_window if (self._biblio_window and self._biblio_window.isVisible()) else None
        # Wrap everything: a single paper's error (apply, network, parse, …) must
        # never break the drain chain and stall the whole batch. The finally
        # always advances the queue.
        try:
            pred, err = result

            if err:
                self._biblio_guard.record_fail()
                self.status_bar.set_task(f'Biblio extraction failed: {err}')
                if win:
                    win.record(f'{self._biblio_title(paper_id)} — extraction failed', 'error')
                return
            # A valid prediction means the LLM server responded — reset the
            # server-down streak even if a downstream apply step later fails.
            self._biblio_guard.record_ok()

            # LLM skipped because the OCR JSON already carries an applied
            # papermeister_meta. Materialize a local PaperBiblio so the paper
            # stops re-appearing as a target and its pill turns 'done'.
            if isinstance(pred, dict) and pred.get('skipped'):
                meta = pred.get('meta') or {}
                state = meta.get('biblio_state', '?')
                source = meta.get('biblio_source', '?')
                self._materialize_applied_biblio(paper_id, meta)
                self.status_bar.set_task(
                    f'Biblio already {state} on Zotero ({source}) — skipped LLM for paper {paper_id}'
                )
                if win:
                    win.record(f'{self._biblio_title(paper_id)} — already {state} (skipped LLM)', 'skip')
                self.paper_list.refresh_row(paper_id)
                return

            # Try auto-apply if biblio matches Zotero data
            from papermeister import biblio_reflect
            from papermeister.models import Paper
            from papermeister.zotero_writeback import ZoteroPatchRejected, ZoteroWriteAccessDenied
            paper = Paper.get_or_none(Paper.id == paper_id)
            biblio = biblio_reflect.select_best_biblio(paper) if paper else None
            summary = self._biblio_pred_summary(pred, paper_id)
            kind, line = 'skip', summary
            if biblio:
                decision = biblio_reflect.evaluate(biblio, paper)
                if decision.action == 'auto_commit':
                    try:
                        biblio_reflect.apply_single(paper_id)
                    except ZoteroWriteAccessDenied as e:
                        self.status_bar.set_task(f'Biblio auto-apply blocked: {e}')
                        kind, line = 'error', f'{summary} — apply blocked'
                    except ZoteroPatchRejected as e:
                        self.status_bar.set_task(f'Zotero rejected biblio patch (paper {paper_id}): {e}')
                        kind, line = 'error', f'{summary} — Zotero rejected patch'
                    else:
                        self.status_bar.set_task(f'Biblio extracted & auto-applied for paper {paper_id}')
                        self.paper_list.refresh_row(paper_id)
                        kind, line = 'applied', f'applied — {summary}'
                elif decision.action == 'needs_review':
                    # Stamp the biblio so the Library "Needs Review" filter and
                    # the list pill both pick it up (reflect_all does the same).
                    if biblio.status not in ('applied', 'auto_committed', 'rejected'):
                        biblio.status = 'needs_review'
                        biblio.review_reason = decision.reason
                        biblio.save()
                    self.status_bar.set_task(
                        f'Biblio extracted for paper {paper_id} (needs review: {decision.reason})')
                    kind, line = 'review', f'needs review ({decision.reason}) — {summary}'
                    self.paper_list.refresh_row(paper_id)
                else:  # skip — already complete (Zotero already matches)
                    # Terminal: stamp so the paper shows 'done' instead of
                    # lingering on the OCR pill (mirrors reflect_all).
                    if (
                        decision.reason == 'already_complete'
                        and biblio.status not in ('applied', 'auto_committed', 'rejected')
                    ):
                        biblio.status = 'auto_committed'
                        biblio.review_reason = 'already_complete'
                        biblio.save()
                    self.status_bar.set_task(
                        f'Biblio extracted for paper {paper_id} ({decision.reason})')
                    kind, line = 'skip', f'{decision.reason} — {summary}'
                    self.paper_list.refresh_row(paper_id)
            else:
                self.status_bar.set_task(f'Biblio extracted for paper {paper_id}')
                kind, line = 'skip', f'extracted — {summary}'

            if win:
                win.record(line, kind)
        except Exception as e:
            self.status_bar.set_task(f'Biblio error for paper {paper_id}: {e}')
            if win:
                win.record(f'{self._biblio_title(paper_id)} — error: {e}', 'error')
        finally:
            self._after_biblio(paper_id)

    def _ensure_biblio_window(self):
        """Lazily create the biblio progress window and wire its Cancel."""
        if self._biblio_window is None:
            from desktop.windows.biblio_window import BiblioWindow
            self._biblio_window = BiblioWindow(self)
            self._biblio_window.cancel_requested.connect(self._cancel_biblio)
        return self._biblio_window

    def _cancel_biblio(self):
        """Cancel the biblio batch: drop the pending queue, let the in-flight
        paper finish (its LLM call can't be safely killed)."""
        dropped = len(self._auto_biblio_queue)
        self._auto_biblio_queue.clear()
        self._biblio_guard.cancel()     # in case we were paused waiting on the server
        if self._biblio_window:
            self._biblio_window.mark_cancelling(dropped)
        running = bool(self._biblio_task and self._biblio_task.isRunning())
        self.status_bar.set_task(
            f'Biblio cancelled — dropped {dropped} queued'
            + (', finishing current paper…' if running else '.'))
        if not running and self._biblio_window and self._biblio_window.isVisible():
            self._biblio_window.finish()

    def _make_biblio_guard(self):
        """ServerGuard for the biblio batch: pause on repeated LLM-server failure,
        poll, auto-resume. With the Claude backend biblio_server_alive() reports
        'up', so the guard never pauses (nothing to poll)."""
        from desktop.workers.server_guard import ServerGuard
        from papermeister.biblio import biblio_server_alive

        def on_pause(remaining):
            if self._biblio_window:
                self._biblio_window.mark_paused(
                    remaining, 'Biblio extractions kept failing and the LLM '
                    'server did not answer a health check.')
            self.status_bar.set_task(
                'Biblio paused — waiting for the LLM server to recover…')

        def on_resume(remaining):
            if self._biblio_window:
                self._biblio_window.mark_resumed(remaining)
            self.status_bar.set_task('Biblio server back — resuming…')

        return ServerGuard(
            health_check=biblio_server_alive,
            on_pause=on_pause, on_resume=on_resume,
            on_drain=self._drain_biblio_queue,
            remaining=lambda: len(self._auto_biblio_queue), parent=self)

    def _drain_biblio_queue(self):
        """Start biblio extraction for the next queued item, if idle."""
        if self._biblio_guard.paused():  # waiting for the LLM server to recover
            return
        if self._biblio_task and self._biblio_task.isRunning():
            return  # already running, will drain again when it finishes
        if not self._auto_biblio_queue:
            return
        paper_id, file_id = self._auto_biblio_queue.pop(0)
        self._run_biblio_extraction_silent(paper_id, file_id)

    def _run_biblio_extraction_silent(self, paper_id: int, file_id: int):
        """Run biblio extraction without confirmation dialog (for auto pipeline)."""
        import json

        from desktop.workers.background import BackgroundTask
        from papermeister.models import PaperBiblio, PaperFile
        from papermeister.preferences import get_pref

        pf = PaperFile.get_or_none(PaperFile.id == file_id) if file_id else None
        if not pf or not pf.hash:
            self._drain_biblio_queue()
            return

        import os
        biblio_backend = get_pref('biblio_backend', 'claude')
        file_hash = pf.hash
        biblio_filename = os.path.basename(pf.path)
        self.status_bar.set_task(f'Extracting biblio for paper {paper_id}…')
        if self._biblio_window and self._biblio_window.isVisible():
            title = self._biblio_title(paper_id)
            self._biblio_window.set_current(f'Extracting: {title}')

        def _do_extract():
            from papermeister.biblio import BiblioAlreadyApplied, extract_biblio_llm
            try:
                pred, source, model_version = extract_biblio_llm(
                    file_hash, backend=biblio_backend, filename=biblio_filename)
            except BiblioAlreadyApplied as exc:
                return {'skipped': True, 'meta': exc.meta}, None
            PaperBiblio.create(
                paper=paper_id,
                file_hash=file_hash,
                title=pred.get('title', '') or '',
                authors_json=json.dumps(pred.get('authors', []) or [], ensure_ascii=False),
                year=pred.get('year') if isinstance(pred.get('year'), int) else None,
                journal=pred.get('journal', '') or '',
                volume=str(pred.get('volume', '') or ''),
                issue=str(pred.get('issue', '') or ''),
                pages=str(pred.get('pages', '') or ''),
                doi=pred.get('doi', '') or '',
                abstract=pred.get('abstract', '') or '',
                doc_type=pred.get('doc_type', 'unknown') or 'unknown',
                language=pred.get('language', '') or '',
                confidence=pred.get('confidence', '') or '',
                needs_visual_review=bool(pred.get('needs_visual_review', False)),
                notes=pred.get('notes', '') or '',
                source=source,
                model_version=model_version,
            )
            return pred, None

        task = BackgroundTask(_do_extract)
        task.done.connect(lambda result: self._on_biblio_extracted(paper_id, result))
        task.failed.connect(lambda msg: self._on_biblio_failed(paper_id, msg))
        self._biblio_task = task
        task.start()

    # ── References extraction (P11) ──────────────────────────
    # Parses a paper's bibliography into Reference rows via the ocrserver
    # Qwen model. Separate serialized queue from biblio (different backend
    # call + no Zotero apply), but the same progress-window UX.

    def _refs_backend(self) -> str:
        """References parsing always uses the local server (Qwen) when it's
        configured; falls back to claude otherwise."""
        from papermeister.preferences import get_pref
        return 'qwen' if get_pref('ocr_pod_url', '') else 'claude'

    def _refs_targets(self, folder_ids):
        """Processed PDFs (in scope) whose paper hasn't had references checked.

        `Paper.references_checked` is set once extraction has run (even if no
        references section was found), so papers without a bibliography aren't
        re-parsed on every batch. Returns [(paper_id, file_id), ...].
        folder_ids None → whole library.
        """
        from papermeister.models import Paper, PaperFile, PaperFolder

        if folder_ids is None:
            pdfs = (
                PaperFile.select(PaperFile.id, PaperFile.paper)
                .join(Paper)
                .where(
                    PaperFile.status == 'processed',
                    PaperFile.path.endswith('.pdf'),
                    Paper.references_checked == False,  # noqa: E712 (peewee)
                )
                .order_by(PaperFile.paper.desc())
            )
        else:
            pdfs = (
                PaperFile.select(PaperFile.id, PaperFile.paper)
                .join(Paper).join(PaperFolder, on=(PaperFolder.paper == Paper.id))
                .where(
                    PaperFolder.folder << folder_ids,
                    PaperFile.status == 'processed',
                    PaperFile.path.endswith('.pdf'),
                    Paper.references_checked == False,  # noqa: E712 (peewee)
                )
                .order_by(Paper.id.desc())
            )

        queued = {pid for pid, _ in self._refs_queue}
        targets, seen = [], set()
        for pf in pdfs:
            pid = pf.paper_id
            if pid in seen or pid in queued:
                continue
            seen.add(pid)
            targets.append((pid, pf.id))
        return targets

    def _run_references_extraction(self, paper_id: int, file_id: int):
        """Single-paper references extraction (right-click on a paper)."""
        from papermeister.models import PaperFile
        pf = PaperFile.get_or_none(PaperFile.id == file_id) if file_id else None
        if not pf or not pf.hash:
            self.status_bar.set_task('No file hash — cannot extract references')
            return

        engine = 'Qwen3 (local server)' if self._refs_backend() == 'qwen' \
            else 'Claude Sonnet 4.6 (Max plan quota)'
        resp = QMessageBox.question(
            self, 'Extract References',
            f'Parse this paper\'s references section using {engine}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        self._ensure_refs_window()
        if (paper_id, file_id) not in self._refs_queue:
            self._refs_queue.append((paper_id, file_id))
            self._refs_window.begin(1)
        else:
            self._refs_window.show()
            self._refs_window.raise_()
        self.status_bar.set_task(f'Queued references extraction for paper {paper_id}…')
        self._drain_refs_queue()

    def _run_references_scope(self, folder_ids, scope_label: str):
        """Folder / whole-library references extraction (right-click on a
        folder or 'My Library')."""
        targets = self._refs_targets(folder_ids)
        if not targets:
            self.status_bar.set_task(
                f'Nothing to do — references already extracted ({scope_label})')
            return

        resp = QMessageBox.question(
            self, 'Extract References',
            f'Parse references for {len(targets)} OCR-completed paper(s) in '
            f'{scope_label}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Honour the on-screen sort order for the visible papers.
        rank = {pid: i for i, pid in enumerate(self.paper_list.visible_paper_ids())}
        targets.sort(key=lambda t: rank.get(t[0], len(rank)))

        self._ensure_refs_window()
        self._refs_window.begin(len(targets))
        self._refs_queue.extend(targets)
        self.status_bar.set_task(f'References: {len(targets)} paper(s)…')
        self._drain_refs_queue()

    def _ensure_refs_window(self):
        """Lazily create the references progress window and wire its Cancel."""
        if self._refs_window is None:
            from desktop.windows.references_window import ReferencesWindow
            self._refs_window = ReferencesWindow(self)
            self._refs_window.cancel_requested.connect(self._cancel_refs)
        return self._refs_window

    def _cancel_refs(self):
        """Cancel the references batch: drop everything still queued and let the
        paper already in flight finish (its LLM call can't be safely killed)."""
        dropped = len(self._refs_queue)
        self._refs_queue.clear()
        self._refs_guard.cancel()       # in case we were paused waiting on the server
        if self._refs_window:
            self._refs_window.mark_cancelling(dropped)
        running = bool(self._refs_task and self._refs_task.isRunning())
        self.status_bar.set_task(
            f'References cancelled — dropped {dropped} queued'
            + (', finishing current paper…' if running else '.'))
        if not running:
            # Nothing in flight → finalize immediately.
            self._refs_index = None
            self._refs_work_index = None
            if self._refs_window and self._refs_window.isVisible():
                self._refs_window.finish()

    def _drain_refs_queue(self):
        """Start references extraction for the next queued item, if idle."""
        if self._refs_guard.paused():   # waiting for the LLM server to recover
            return
        if self._refs_task and self._refs_task.isRunning():
            return
        if not self._refs_queue:
            return
        paper_id, file_id = self._refs_queue.pop(0)
        self._run_references_extraction_silent(paper_id, file_id)

    def _run_references_extraction_silent(self, paper_id: int, file_id: int):
        """Parse references in the background and save Reference rows."""
        from desktop.workers.background import BackgroundTask
        from papermeister.models import PaperFile

        pf = PaperFile.get_or_none(PaperFile.id == file_id) if file_id else None
        if not pf or not pf.hash:
            self._drain_refs_queue()
            return

        backend = self._refs_backend()
        file_hash = pf.hash
        self.status_bar.set_task(f'Parsing references for paper {paper_id}…')
        if self._refs_window and self._refs_window.isVisible():
            self._refs_window.set_current(f'Parsing: {self._biblio_title(paper_id)}')

        def _do_extract():
            from papermeister import references as refs_mod
            from papermeister.biblio import extract_references_llm
            entries, source, model_version, complete, skipped = extract_references_llm(
                file_hash, backend=backend,
                on_progress=task.progress.emit,
                on_notice=task.notice.emit)
            n = refs_mod.save_references(paper_id, entries, source, model_version)
            # Auto-resolve the freshly-saved references against held papers so
            # the 'in library' badge is populated without a separate step, and
            # canonicalize externals into CitedWork nodes (Phase 2 pass-1 exact
            # dedup) so the Cited Works browser / co-citation badges populate.
            # Both indexes are built once per batch and reused (refs run
            # serialized, so no race), invalidated when the queue drains.
            resolved = 0
            if n:
                if self._refs_index is None:
                    self._refs_index = refs_mod.build_resolution_index()
                if self._refs_work_index is None:
                    self._refs_work_index = refs_mod.build_work_index()
                counts = refs_mod.resolve_paper_references(
                    paper_id, index=self._refs_index,
                    work_index=self._refs_work_index)
                resolved = counts.get('doi', 0) + counts.get('title', 0)
            return n, resolved, complete, skipped

        task = BackgroundTask(_do_extract)
        task.progress.connect(self._on_refs_item_progress)
        task.notice.connect(self._on_refs_notice)
        task.done.connect(lambda result: self._on_refs_extracted(paper_id, result))
        task.failed.connect(lambda msg: self._on_refs_failed(paper_id, msg))
        self._refs_task = task
        task.start()

    def _on_refs_item_progress(self, done: int, total: int):
        """Parsing progress within the current paper (queued from the worker)."""
        if self._refs_window and self._refs_window.isVisible():
            self._refs_window.set_item_progress(done, total)

    def _on_refs_notice(self, kind: str, msg: str):
        """Something happened inside the paper being parsed that the user should
        see — today, the LLM gateway answering 5xx and the worker waiting for the
        container to restart. That wait runs for minutes with the queue intact,
        so without this the window sits on 'Parsing: …' and looks stuck."""
        self.status_bar.set_task(f'References — {msg}')
        win = self._refs_window if (self._refs_window and self._refs_window.isVisible()) else None
        if not win:
            return
        if kind == 'server_down':
            win.mark_server_wait(msg)
        else:
            win.mark_server_back(msg, recovered=(kind == 'server_up'))

    def _on_refs_extracted(self, paper_id: int, result):
        win = self._refs_window if (self._refs_window and self._refs_window.isVisible()) else None
        try:
            n, resolved, complete, skipped = result
            # Only stamp checked when parsing completed. A partial result
            # (complete=False: the LLM server timed out / died and batches were
            # skipped) is saved but left UNCHECKED so a later run re-parses and
            # replaces it — mirrors extract_references.py. Otherwise a server
            # outage would silently mark papers done with missing references.
            from papermeister.models import Paper
            if complete:
                self._refs_guard.record_ok()
                Paper.update(references_checked=True).where(
                    Paper.id == paper_id).execute()
            title = self._biblio_title(paper_id)
            if not complete:
                self.status_bar.set_task(
                    f'References incomplete for paper {paper_id} '
                    f'(server?) — will retry')
                if win:
                    from papermeister.biblio import describe_skips
                    why = describe_skips(skipped) or 'server?'
                    win.record(
                        f'{title} — {n} refs PARTIAL ({why}), left to retry',
                        'error', refs=n)
            elif n > 0:
                self.status_bar.set_task(
                    f'Parsed {n} references for paper {paper_id} '
                    f'({resolved} in library)')
                if win:
                    win.record(f'{title} — {n} references, {resolved} in library',
                               'ok', refs=n)
            else:
                self.status_bar.set_task(f'No references found for paper {paper_id}')
                if win:
                    win.record(f'{title} — no references section', 'empty')
            if not complete:
                self._refs_guard.record_fail()
        except Exception as e:
            self.status_bar.set_task(f'References error for paper {paper_id}: {e}')
            if win:
                win.record(f'{self._biblio_title(paper_id)} — error: {e}', 'error')
        finally:
            self._after_refs(paper_id)

    def _on_refs_failed(self, paper_id: int, msg: str):
        self.status_bar.set_task(f'References failed for paper {paper_id}: {msg}')
        win = self._refs_window if (self._refs_window and self._refs_window.isVisible()) else None
        if win:
            win.record(f'{self._biblio_title(paper_id)} — failed: {msg}', 'error')
        self._refs_guard.record_fail()
        self._after_refs(paper_id)

    def _make_refs_guard(self):
        """ServerGuard for the references batch: pause on repeated LLM-server
        failure, poll, auto-resume."""
        from desktop.workers.server_guard import ServerGuard
        from papermeister.biblio import references_server_alive

        def on_pause(remaining):
            if self._refs_window:
                self._refs_window.mark_paused(
                    remaining, 'References parses kept failing and the LLM '
                    'server did not answer a health check.')
            self.status_bar.set_task(
                'References paused — waiting for the LLM server to recover…')

        def on_resume(remaining):
            if self._refs_window:
                self._refs_window.mark_resumed(remaining)
            self.status_bar.set_task('References server back — resuming…')

        return ServerGuard(
            health_check=references_server_alive,
            on_pause=on_pause, on_resume=on_resume,
            on_drain=self._drain_refs_queue,
            remaining=lambda: len(self._refs_queue), parent=self)

    def _after_refs(self, paper_id: int):
        """Shared tail: refresh detail if showing this paper, drain queue,
        finish window + drop the resolution index when the batch is idle."""
        if self.detail_panel._current_paper_id == paper_id:
            self.detail_panel.show_paper(paper_id)  # repopulate References tab
        self._drain_refs_queue()
        if not self._refs_queue and not (self._refs_task and self._refs_task.isRunning()):
            self._refs_index = None  # rebuild fresh next batch (paper set may change)
            self._refs_work_index = None
            win = self._refs_window
            if win and win.isVisible():
                win.finish()

    def _open_preferences(self):
        """Open the frozen PreferencesDialog for RunPod / Zotero credentials."""
        from papermeister.ui.preferences_dialog import PreferencesDialog

        dlg = PreferencesDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._sync_zotero()  # re-sync after credential changes

    def _on_nav_selection(self, kind: str, value):
        self._current_selection = (kind, value)
        # Clicking nav implicitly cancels any active search. Clear the box
        # without re-triggering textChanged → _restore_library_view, which
        # would double-load the same view.
        self.search_bar.blockSignals(True)
        self.search_bar.clear()
        self.search_bar.blockSignals(False)
        self.detail_panel._empty_state()
        self._apply_current_selection()

    def _apply_current_selection(self):
        """Load paper_list according to `_current_selection`, defaulting to All Files."""
        # Leaving search → drop OCR-tab highlight terms.
        self.detail_panel.set_search_terms([])
        kind, value = self._current_selection or ('library', 'all')
        if kind == 'library':
            self.paper_list.load_library(str(value))
        elif kind == 'source':
            self.paper_list.load_source(int(value))
        elif kind == 'folder':
            self.paper_list.load_folder(int(value))

    # ── Search handlers ──────────────────────────────────────

    def _on_search_submitted(self):
        query = self.search_bar.text().strip()
        if not query:
            self._apply_current_selection()
            self.status_bar.set_task('Idle')
            return
        self.paper_list.load_search(query)
        from desktop.services import search_service
        self.detail_panel.set_search_terms(search_service.query_terms(query))
        self.status_bar.set_task(f'Search: "{query}"')

    def _on_search_text_changed(self, text: str):
        # Clearing the box (via X button or backspace) restores the last
        # nav selection so the list doesn't stay stuck on stale results.
        if text == '':
            self._apply_current_selection()
            self.status_bar.set_task('Idle')

    def _on_apply_completed(self, paper_id: int, changed: bool, action: str):
        # Refresh counts and the library tree (needs_review bucket may change).
        try:
            total, pending, review = library_svc.corpus_counts()
            self.status_bar.set_counts(total, pending, review)
        except Exception:
            pass
        self.source_nav.refresh()
        if changed:
            self.paper_list.refresh_row(paper_id)
        self.status_bar.set_task(
            f'Applied paper #{paper_id} ({action})' if changed else f'No changes for paper #{paper_id}'
        )

    def _on_reference_navigate(self, paper_id: int):
        """A 'in library' reference badge was clicked → open that cited paper.
        Select it in the list if it's on screen; always show it in the detail."""
        from papermeister.models import Paper
        if Paper.get_or_none(Paper.id == paper_id) is None:
            self.status_bar.set_task(f'Paper #{paper_id} is no longer in the library')
            return
        if not self.paper_list.select_paper(paper_id):
            # Not in the current list view — just show it in the detail panel.
            self.detail_panel.show_paper(paper_id)
        self.status_bar.set_task(f'Opened cited paper #{paper_id}')

    def _load_initial(self):
        try:
            total, pending, review = library_svc.corpus_counts()
        except Exception:
            total = pending = review = 0
        self.status_bar.set_counts(total, pending, review)
        self.status_bar.set_task('Idle')
        # Default: show All Files
        self.paper_list.load_library('all')
