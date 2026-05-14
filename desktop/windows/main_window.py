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
        self._sync_worker = None  # ZoteroSyncWorker
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
        self.paper_list.paper_selected.connect(self.detail_panel.show_paper)
        self.paper_list.folder_reveal_requested.connect(self.source_nav.reveal_folder)
        self.paper_list.context_action.connect(self._on_context_action)
        self.detail_panel.apply_completed.connect(self._on_apply_completed)
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
        """One-shot action (sync | process | settings). Does not change persistent mode."""
        if action == 'sync':
            self._sync_zotero()
        elif action == 'process':
            self._open_process()
        elif action == 'settings':
            self._open_preferences()

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
        then auto-run biblio extraction if OCR succeeded."""
        from papermeister.models import PaperFile
        pf = PaperFile.get_or_none(PaperFile.id == paper_file_id)
        if not pf:
            return
        self.paper_list.update_status(pf.paper_id, status)
        if status == 'processed' and pf.hash:
            self._auto_biblio_queue.append((pf.paper_id, pf.id))
            self._drain_biblio_queue()

    def _on_context_action(self, action: str, paper_id: int, file_id: int):
        from papermeister.models import PaperFile
        if action in ('process', 'retry'):
            if not file_id:
                return
            if action == 'retry':
                PaperFile.update(status='pending').where(PaperFile.id == file_id).execute()
            if self._process_window is None:
                from papermeister.ui.process_window import ProcessWindow
                self._process_window = ProcessWindow(self)
                self._process_window.processing_updated.connect(self._on_processing_updated)
                self._process_window.file_processed.connect(self._on_file_processed)
            self._process_window.start([file_id])
            self.status_bar.set_task('Processing 1 file…')
        elif action == 'open_pdf':
            self.detail_panel.show_paper(paper_id)
            self.detail_panel._tabs.setCurrentIndex(1)  # PDF tab
        elif action == 'extract_biblio':
            self._run_biblio_extraction(paper_id, file_id)
        elif action == 'review_biblio':
            self.detail_panel.show_paper(paper_id)
            self.detail_panel._tabs.setCurrentIndex(0)  # Metadata tab (includes biblio)

    def _on_folder_action(self, action: str, folder_id: int):
        if action == 'process_folder':
            self._process_folder(folder_id)
        elif action == 'upload_ocr_json':
            self._upload_ocr_json(folder_id)

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
        """Process all pending files in a folder and its subfolders."""
        from papermeister.models import Paper, PaperFile, PaperFolder

        all_folder_ids = self._collect_folder_ids(folder_id)

        # Collect pending PDF file IDs for this folder tree
        file_ids = [
            pf.id for pf in (
                PaperFile.select(PaperFile.id)
                .join(Paper)
                .join(PaperFolder, on=(PaperFolder.paper == Paper.id))
                .where(
                    PaperFolder.folder << all_folder_ids,
                    PaperFile.status == 'pending',
                    PaperFile.path.endswith('.pdf'),
                )
            )
        ]

        if not file_ids:
            self.status_bar.set_task('No pending PDF files in this folder')
            return

        resp = QMessageBox.question(
            self,
            'Process Folder',
            f'Process {len(file_ids)} pending PDF(s)?\n'
            f'OCR will run, then biblio extraction for completed files.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        if self._process_window is None:
            from papermeister.ui.process_window import ProcessWindow
            self._process_window = ProcessWindow(self)
            self._process_window.processing_updated.connect(self._on_processing_updated)
            self._process_window.file_processed.connect(self._on_file_processed)
        self._process_window.start(file_ids)
        self.status_bar.set_task(f'Processing {len(file_ids)} files…')

    def _upload_ocr_json(self, folder_id: int):
        """Upload OCR JSON files to Zotero for processed papers in a folder."""
        import os
        from papermeister.models import Paper, PaperFile, PaperFolder
        from papermeister.text_extract import OCR_JSON_DIR
        from desktop.workers.background import BackgroundTask

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

        # Filter: has OCR JSON on disk AND no JSON sibling yet
        paper_ids_with_json = set(
            pf.paper_id for pf in
            PaperFile.select(PaperFile.paper)
            .where(PaperFile.path.endswith('.json'))
        )
        todo = [
            pf for pf in pdf_files
            if pf.paper_id not in paper_ids_with_json
            and os.path.exists(os.path.join(OCR_JSON_DIR, f'{pf.hash}.json'))
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
            from papermeister.preferences import get_pref
            from papermeister.zotero_client import ZoteroClient
            from papermeister.ingestion import hash_file
            import time

            user_id = get_pref('zotero_user_id', '')
            api_key = get_pref('zotero_api_key', '')
            if not user_id or not api_key:
                return 0, 0, 'Zotero credentials not configured'

            client = ZoteroClient(user_id, api_key)
            success = 0
            failed = 0
            for pf in todo:
                json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
                try:
                    new_key = client.upload_sibling_attachment(pf.zotero_key, json_path)
                    if new_key:
                        PaperFile.create(
                            paper=pf.paper,
                            path=os.path.basename(json_path),
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
        import json
        from papermeister.models import PaperFile, PaperBiblio
        from papermeister.preferences import get_pref
        from desktop.workers.background import BackgroundTask

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

        file_hash = pf.hash
        self.status_bar.set_task(f'Extracting biblio for paper {paper_id}…')

        def _do_extract():
            from papermeister.biblio import extract_biblio_llm, BiblioAlreadyApplied
            try:
                pred, source, model_version = extract_biblio_llm(file_hash, backend=biblio_backend)
            except BiblioAlreadyApplied as exc:
                return {'skipped': True, 'meta': exc.meta}, None
            PaperBiblio.create(
                paper=paper_id,
                file_hash=file_hash,
                title=pred.get('title', '') or '',
                authors_json=json.dumps(pred.get('authors', []) or [], ensure_ascii=False),
                year=pred.get('year') if isinstance(pred.get('year'), int) else None,
                journal=pred.get('journal', '') or '',
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
        task.failed.connect(lambda msg: self.status_bar.set_task(f'Biblio extraction failed: {msg}'))
        self._biblio_task = task
        task.start()

    def _on_biblio_extracted(self, paper_id: int, result):
        pred, err = result
        if err:
            self.status_bar.set_task(f'Biblio extraction failed: {err}')
            return

        # LLM call was skipped because the OCR JSON already carries an applied
        # papermeister_meta from another machine. Just update UI + drain queue.
        if isinstance(pred, dict) and pred.get('skipped'):
            meta = pred.get('meta') or {}
            state = meta.get('biblio_state', '?')
            source = meta.get('biblio_source', '?')
            self.status_bar.set_task(
                f'Biblio already {state} on Zotero ({source}) — skipped LLM for paper {paper_id}'
            )
            self.paper_list.update_status(paper_id, 'done')
            if self.detail_panel._current_paper_id == paper_id:
                self.detail_panel.show_paper(paper_id)
            self._drain_biblio_queue()
            return

        # Try auto-apply if biblio matches Zotero data
        from papermeister import biblio_reflect
        from papermeister.models import Paper
        from papermeister.zotero_writeback import ZoteroWriteAccessDenied
        paper = Paper.get_or_none(Paper.id == paper_id)
        biblio = biblio_reflect.select_best_biblio(paper) if paper else None
        if biblio:
            decision = biblio_reflect.evaluate(biblio, paper)
            if decision.action == 'auto_commit':
                try:
                    biblio_reflect.apply_single(paper_id)
                except ZoteroWriteAccessDenied as e:
                    self.status_bar.set_task(f'Biblio auto-apply blocked: {e}')
                else:
                    self.status_bar.set_task(f'Biblio extracted & auto-applied for paper {paper_id}')
                    self.paper_list.update_status(paper_id, 'done')
            else:
                self.status_bar.set_task(
                    f'Biblio extracted for paper {paper_id} (needs review: {decision.reason})')
        else:
            self.status_bar.set_task(f'Biblio extracted for paper {paper_id}')

        if self.detail_panel._current_paper_id == paper_id:
            self.detail_panel.show_paper(paper_id)

        # Process next item in auto-biblio queue
        self._drain_biblio_queue()

    def _drain_biblio_queue(self):
        """Start biblio extraction for the next queued item, if idle."""
        if self._biblio_task and self._biblio_task.isRunning():
            return  # already running, will drain again when it finishes
        if not self._auto_biblio_queue:
            return
        paper_id, file_id = self._auto_biblio_queue.pop(0)
        self._run_biblio_extraction_silent(paper_id, file_id)

    def _run_biblio_extraction_silent(self, paper_id: int, file_id: int):
        """Run biblio extraction without confirmation dialog (for auto pipeline)."""
        import json
        from papermeister.models import PaperFile, PaperBiblio
        from papermeister.preferences import get_pref
        from desktop.workers.background import BackgroundTask

        pf = PaperFile.get_or_none(PaperFile.id == file_id) if file_id else None
        if not pf or not pf.hash:
            self._drain_biblio_queue()
            return

        biblio_backend = get_pref('biblio_backend', 'claude')
        file_hash = pf.hash
        self.status_bar.set_task(f'Extracting biblio for paper {paper_id}…')

        def _do_extract():
            from papermeister.biblio import extract_biblio_llm, BiblioAlreadyApplied
            try:
                pred, source, model_version = extract_biblio_llm(file_hash, backend=biblio_backend)
            except BiblioAlreadyApplied as exc:
                return {'skipped': True, 'meta': exc.meta}, None
            PaperBiblio.create(
                paper=paper_id,
                file_hash=file_hash,
                title=pred.get('title', '') or '',
                authors_json=json.dumps(pred.get('authors', []) or [], ensure_ascii=False),
                year=pred.get('year') if isinstance(pred.get('year'), int) else None,
                journal=pred.get('journal', '') or '',
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
        task.failed.connect(lambda msg: (
            self.status_bar.set_task(f'Biblio failed for paper {paper_id}: {msg}'),
            self._drain_biblio_queue(),
        ))
        self._biblio_task = task
        task.start()

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
            self.paper_list.update_status(paper_id, 'done')
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
