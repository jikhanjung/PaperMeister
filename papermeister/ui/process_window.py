import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ProcessWorker(QThread):
    """OCR-processes PaperFiles with parallel execution based on RunPod worker availability."""
    progress = pyqtSignal(str)
    file_done = pyqtSignal(int, str)  # paper_file.id, status ('processed'/'failed')
    finished = pyqtSignal(int, int)  # processed, failed

    def __init__(self, paper_file_ids, force_ids=None):
        super().__init__()
        import threading
        self.paper_file_ids = list(paper_file_ids)
        # PaperFile ids to re-OCR with force=true (ignore cache + tell server to
        # ignore its existing JSON). Used when retrying failed PDFs.
        self.force_ids = set(force_ids or [])
        self._counter = 0
        self._counter_lock = None
        self._cancelled = False
        self._fail_streak = 0   # consecutive failures (server-down pause guard)
        self._id_lock = threading.Lock()

    def _next_index(self):
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def cancel(self):
        self._cancelled = True

    # Consecutive failures before we probe the server, then recovery poll cadence.
    _FAIL_STOP = 3
    _POLL_SECONDS = 30

    def _note_ok(self):
        self._fail_streak = 0

    def _note_fail(self):
        self._fail_streak += 1

    def _pause_if_server_down(self):
        """After repeated failures, if the OCR server is unreachable, block here
        polling is_ready() until it recovers (or the user cancels) instead of
        burning through the queue marking every file failed. Runs on the worker
        thread, so blocking is fine — the UI stays responsive."""
        if self._fail_streak < self._FAIL_STOP or self._cancelled:
            return
        import time

        from ..ocr import is_ready
        try:
            if is_ready():
                self._fail_streak = 0   # transient blip — server answers
                return
        except Exception:
            pass
        self.progress.emit(
            f'OCR server unreachable ({self._fail_streak} failures in a row) — '
            f'pausing; polling every {self._POLL_SECONDS}s for recovery…')
        while not self._cancelled:
            time.sleep(self._POLL_SECONDS)
            if self._cancelled:
                return
            try:
                if is_ready():
                    self.progress.emit('OCR server back — resuming.')
                    self._fail_streak = 0
                    return
            except Exception:
                pass

    def enqueue(self, new_ids):
        """Append more PaperFile IDs to the active processing queue.
        Dedupes against the full list (already-submitted + still-pending)
        so re-triggers (e.g. Rail Process re-click) don't double-process
        in-flight files. The running loop picks new IDs up on its next
        iteration."""
        if not new_ids:
            return 0
        with self._id_lock:
            existing = set(self.paper_file_ids)
            added = [pf_id for pf_id in new_ids if pf_id not in existing]
            self.paper_file_ids.extend(added)
            return len(added)

    def _process_one(self, pf_id):
        """Process a single PaperFile. Runs in a thread pool thread."""
        if self._cancelled:
            return None  # skipped
        from ..models import PaperFile
        from ..text_extract import process_paper_file

        pf = PaperFile.get_by_id(pf_id)
        name = os.path.basename(pf.path)
        idx = self._next_index()
        total = len(self.paper_file_ids)
        prefix = f'[{idx}/{total}]'

        self.progress.emit(f'{prefix} {name}')
        try:
            process_paper_file(
                pf,
                ocr_progress_callback=lambda c, t, msg: self.progress.emit(f'{prefix}   {msg}'),
                status_callback=lambda msg: self.progress.emit(f'{prefix}   {msg}'),
                force=(pf_id in self.force_ids),
            )
            # process_paper_file may park a non-PDF as 'skipped' instead of
            # OCRing — emit the real status, not a hard-coded 'processed'.
            self.file_done.emit(pf_id, pf.status)
            return pf.status != 'failed'
        except Exception as e:
            pf.status = 'failed'
            # Record a short, diagnosable reason (corrupt/locked PDF, network,
            # …) instead of a bare 'failed'.
            pf.failure_reason = f'{type(e).__name__}: {str(e)[:140]}'
            pf.save()
            self.progress.emit(f'{prefix}   FAILED: {e}')
            self.file_done.emit(pf_id, 'failed')
            return False

    def run(self):
        import threading

        from ..ocr import ensure_workers_ready, get_worker_status, is_wrapper_mode

        self._counter = 0
        self._counter_lock = threading.Lock()

        # Ensure at least one worker is up
        try:
            ensure_workers_ready()
        except Exception as e:
            self.progress.emit(f'RunPod not ready: {e}')
            self.finished.emit(0, len(self.paper_file_ids))
            return

        # Determine concurrency from health check
        status = get_worker_status()
        idle = status['idle']
        running = status['running']
        max_concurrent = max(1, min(idle, 10))

        self.progress.emit(
            f'RunPod workers: {idle} idle, {running} running '
            f'→ parallel: {max_concurrent}'
        )

        if is_wrapper_mode():
            from ..ocr import wrapper_get_stats
            from ..preferences import get_pref
            # Resolve queue depth target. Explicit pref wins (user override);
            # otherwise follow the server's mode-aware recommendation.
            configured = get_pref('ocr_min_queued_pages', None)
            if configured is not None:
                min_queued = max(1, int(configured))
                self.progress.emit(
                    f'Queue depth target: {min_queued} pages (pref override)'
                )
            else:
                stats = wrapper_get_stats()
                rec = int(stats.get('recommended_concurrency') or 0)
                if rec > 0:
                    min_queued = rec
                    mode = stats.get('mode', '?')
                    alive = stats.get('ocr_backends_alive', '?')
                    total = stats.get('ocr_backends_total', '?')
                    self.progress.emit(
                        f'Queue depth target: {min_queued} pages '
                        f'(mode={mode}, OCR backends {alive}/{total})'
                    )
                else:
                    min_queued = 6
                    self.progress.emit(
                        f'Queue depth target: {min_queued} pages (stats unavailable, default)'
                    )
            processed, failed = self._run_wrapper_pipeline(min_queued_pages=min_queued)
        else:
            processed, failed = self._run_parallel(max_concurrent)

        self.finished.emit(processed, failed)

    def _run_parallel(self, max_concurrent: int):
        """Parallel mode for serverless/pod backends.

        Polling pattern (rather than `as_completed` over a snapshot) so
        ``enqueue()`` calls during the run get picked up — new IDs
        appended to ``self.paper_file_ids`` are submitted as soon as a
        pool slot frees.
        """
        import time
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        processed = 0
        failed = 0
        submit_idx = 0
        futures: dict = {}

        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            while True:
                if self._cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                self._pause_if_server_down()   # wait out an OCR-server outage
                if self._cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                while len(futures) < max_concurrent and submit_idx < len(self.paper_file_ids):
                    pf_id = self.paper_file_ids[submit_idx]
                    submit_idx += 1
                    futures[pool.submit(self._process_one, pf_id)] = pf_id

                if not futures:
                    if submit_idx >= len(self.paper_file_ids):
                        break
                    time.sleep(0.5)
                    continue

                done, _ = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
                for fut in done:
                    result = fut.result()
                    del futures[fut]
                    if result is True:
                        processed += 1
                        self._note_ok()
                    elif result is False:
                        failed += 1
                        self._note_fail()
        return processed, failed

    def _run_wrapper_pipeline(self, min_queued_pages: int = 6):
        """Pipelined wrapper mode: keep ≥ min_queued_pages on the server.

        Submits PDFs ahead of time so the server always has enough pages
        to fill its concurrency slots (default 6).
        """
        import time

        from ..file_utils import has_non_pdf_extension
        from ..ingestion import hash_file
        from ..models import PaperFile
        from ..ocr import wrapper_collect, wrapper_list_jobs, wrapper_poll, wrapper_submit
        from ..preferences import get_client_id, get_pref
        from ..text_extract import (
            _load_ocr_json,
            _resolve_filepath,
            _save_ocr_json,
            _try_fetch_sibling_json,
            process_paper_file,
        )

        processed = 0
        failed = 0
        # NOTE: total is read dynamically as len(self.paper_file_ids) below —
        # enqueue() can append to the list mid-run.

        # ── Helpers ──────────────────────────────────────────
        def _prepare_file(pf_id):
            """Download PDF if needed, fill hash, check cache.
            Returns (pf, filepath, has_cache) or None on error.
            """
            pf = PaperFile.get_by_id(pf_id)
            is_zotero = bool(pf.zotero_key)
            filepath = None
            force = pf_id in self.force_ids

            if is_zotero and not pf.hash:
                filepath, _ = _resolve_filepath(pf)
                pf.hash = hash_file(filepath)
                pf.save()

            # force: ignore every cache source so the OCR actually re-runs.
            cached = None if force else _load_ocr_json(pf)
            if cached:
                return pf, filepath, True

            # Cache miss — try pulling a sibling `{hash}.json` from Zotero
            # before paying for OCR. Best-effort; falls through on any failure.
            if is_zotero and not force:
                fetched = _try_fetch_sibling_json(
                    pf, status_callback=lambda msg: self.progress.emit(msg),
                )
                if fetched:
                    return pf, filepath, True

            if filepath is None:
                filepath, _ = _resolve_filepath(pf)

            return pf, filepath, False

        def _finalize(pf, raw_result):
            """Save OCR result and run the post-OCR pipeline (passages, FTS)."""
            # Use process_paper_file which handles cache check internally.
            # Since we already saved the OCR JSON, it will load from cache.
            _save_ocr_json(pf, raw_result)
            process_paper_file(pf)

        # ── State tracking ───────────────────────────────────
        # Each in-flight job: {job_id, pf_id, pf, total_pages, name}
        in_flight = []       # jobs submitted, waiting for completion
        submit_idx = 0       # next index into paper_file_ids to submit
        counter = 0

        def _queued_pages():
            """Pages not yet completed across all in-flight jobs."""
            return sum(j['total_pages'] - j.get('done_pages', 0) for j in in_flight)

        # ── Submit helper ─────────────────────────────────────
        def _submit_next():
            """Try to submit the next file. Returns True if something was submitted/handled."""
            nonlocal submit_idx, counter, processed, failed
            if submit_idx >= len(self.paper_file_ids):
                return False

            pf_id = self.paper_file_ids[submit_idx]
            submit_idx += 1
            counter += 1
            prefix = f'[{counter}/{len(self.paper_file_ids)}]'

            try:
                pf, filepath, has_cache = _prepare_file(pf_id)
            except Exception as e:
                self.progress.emit(f'{prefix} FAILED (prepare): {e}')
                pf = PaperFile.get_by_id(pf_id)
                pf.status = 'failed'
                pf.save()
                self.file_done.emit(pf_id, 'failed')
                failed += 1
                self._note_fail()
                return True

            name = os.path.basename(pf.path)

            # Extension gate — never submit a known non-PDF to the OCR server.
            # (has_non_pdf_extension, not is_pdf, so a bare-key PDF still runs.)
            if has_non_pdf_extension(pf.path):
                pf.status = 'skipped'
                pf.save()
                self.progress.emit(f'{prefix} {name} → skipped (not a PDF)')
                self.file_done.emit(pf_id, 'skipped')
                return True

            if has_cache:
                self.progress.emit(f'{prefix} {name} (cached)')
                try:
                    process_paper_file(pf)
                    self.file_done.emit(pf_id, pf.status)
                    processed += 1
                    self._note_ok()
                except Exception as e:
                    self.progress.emit(f'{prefix}   FAILED: {e}')
                    pf.status = 'failed'
                    pf.save()
                    self.file_done.emit(pf_id, 'failed')
                    failed += 1
                    self._note_fail()
                return True

            # Submit to wrapper
            try:
                self.progress.emit(f'{prefix} {name} → submitting…')
                job_id, tp, in_progress = wrapper_submit(filepath, force=(pf_id in self.force_ids))
                in_flight.append({
                    'job_id': job_id, 'pf_id': pf_id, 'pf': pf,
                    'total_pages': tp or 1, 'done_pages': 0,
                    'name': name, 'prefix': prefix,
                })
                if in_progress:
                    # Server matched a still-running job for this hash — we'll
                    # poll it instead of starting a duplicate.
                    self.progress.emit(
                        f'{prefix} {name} → resumed in-flight job {job_id[:8]} ({tp} pages)'
                    )
                else:
                    self.progress.emit(f'{prefix} {name} → queued ({tp} pages)')
            except Exception as e:
                self.progress.emit(f'{prefix} {name} FAILED (submit): {e}')
                pf.status = 'failed'
                pf.save()
                self.file_done.emit(pf_id, 'failed')
                failed += 1
                self._note_fail()
            return True

        # ── Pre-flight: wait for the server to clear other clients' jobs ─
        # Filter by client_id so we only wait on OTHER clients (e.g. another
        # papermeister install, or a different tool sharing this server).
        # Our own previous-session jobs that are still active don't count —
        # there's no point in waiting on ourselves.
        if get_pref('ocr_wait_for_others', True):
            ACTIVE = {'queued', 'processing'}
            my_cid = get_client_id()
            wait_seconds = 0
            while not self._cancelled:
                jobs = wrapper_list_jobs()
                others = [
                    j for j in jobs
                    if j.get('status') in ACTIVE and j.get('client_id') != my_cid
                ]
                if not others:
                    if wait_seconds:
                        self.progress.emit(
                            f'Server is now idle (waited {wait_seconds}s). Starting submissions.'
                        )
                    break
                pages_ahead = sum(
                    max(0, (j.get('total_pages') or 0) - (j.get('done_pages') or 0))
                    for j in others
                )
                self.progress.emit(
                    f'Waiting for server: {len(others)} external job(s) active, '
                    f'~{pages_ahead} pages ahead. Re-checking in 15s…'
                )
                time.sleep(15)
                wait_seconds += 15

        # ── Main loop ────────────────────────────────────────
        # Seed: submit enough files to fill the queue. Each refill loop in
        # this run respects _cancelled so a Cancel click stops further
        # submissions immediately — without the check, the next file gets
        # queued *after* the cancel signal because the top-of-loop check
        # fires too late.
        while (
            submit_idx < len(self.paper_file_ids)
            and _queued_pages() < min_queued_pages
            and not self._cancelled
        ):
            _submit_next()

        while True:
            if self._cancelled:
                break

            self._pause_if_server_down()   # wait out an OCR-server outage
            if self._cancelled:
                break

            # Exit condition: nothing in flight AND no more to submit.
            # enqueue() may have appended after the queue drained, so we
            # check len(self.paper_file_ids) here rather than a captured total.
            if not in_flight:
                if submit_idx >= len(self.paper_file_ids):
                    break
                # New IDs arrived; try to seed again before sleeping.
                while (
                    submit_idx < len(self.paper_file_ids)
                    and _queued_pages() < min_queued_pages
                    and not self._cancelled
                ):
                    _submit_next()
                if not in_flight:
                    # All newly added files were cache hits (or all errored).
                    # Loop back to recheck without sleeping.
                    continue

            time.sleep(5)

            # Poll all in-flight jobs
            still_flying = []
            for job_info in in_flight:
                if self._cancelled:
                    break
                try:
                    job = wrapper_poll(job_info['job_id'])
                except Exception:
                    still_flying.append(job_info)
                    continue

                status = job['status']
                dp = job.get('done_pages', 0)
                tp = job.get('total_pages', job_info['total_pages'])
                job_info['total_pages'] = tp
                job_info['done_pages'] = dp

                if status in ('done', 'done_with_errors'):
                    pf = job_info['pf']
                    prefix = job_info['prefix']
                    try:
                        raw_pages, total_pages = wrapper_collect(job)
                        from datetime import datetime
                        raw_result = {
                            'pdf': job_info['name'],
                            'processed_at': datetime.now().isoformat(),
                            'total_pages': total_pages,
                            'done_pages': len(raw_pages),
                            'pages': sorted(raw_pages.values(), key=lambda p: p['page']),
                        }
                        _finalize(pf, raw_result)
                        self.progress.emit(f'{prefix} {job_info["name"]} done ({tp} pages)')
                        self.file_done.emit(job_info['pf_id'], 'processed')
                        processed += 1
                        self._note_ok()
                    except Exception as e:
                        self.progress.emit(f'{prefix} {job_info["name"]} FAILED: {e}')
                        pf.status = 'failed'
                        pf.save()
                        self.file_done.emit(job_info['pf_id'], 'failed')
                        failed += 1
                        self._note_fail()
                elif status == 'failed':
                    pf = job_info['pf']
                    pf.status = 'failed'
                    pf.save()
                    self.progress.emit(f'{job_info["prefix"]} {job_info["name"]} FAILED (server)')
                    self.file_done.emit(job_info['pf_id'], 'failed')
                    failed += 1
                    self._note_fail()
                else:
                    self.progress.emit(
                        f'{job_info["prefix"]} {job_info["name"]} OCR {dp}/{tp} pages')
                    still_flying.append(job_info)

            in_flight = still_flying

            # Refill: submit more to keep queue ≥ min_queued_pages, unless
            # the user cancelled — otherwise the next file is submitted
            # *after* the cancel signal and the cancel feels ignored.
            while (
                submit_idx < len(self.paper_file_ids)
                and _queued_pages() < min_queued_pages
                and not self._cancelled
            ):
                _submit_next()

        return processed, failed


class ProcessWindow(QWidget):
    """Non-modal window showing OCR processing progress with a log."""
    processing_updated = pyqtSignal()      # emitted when a file finishes (for main window refresh)
    file_processed = pyqtSignal(int, str)  # paper_file_id, status — for per-row pill update

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('OCR Processing')
        self.setMinimumSize(700, 450)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._worker = None
        self._log_path = None
        self._setup_ui()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_server_status)
        self._status_timer.start(5000)
        self._poll_server_status()

    def _get_log_path(self):
        """Return today's log file path, creating ~/.papermeister/logs/ if needed."""
        log_dir = os.path.join(os.path.expanduser('~'), '.papermeister', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        fname = f'ocr_{datetime.now().strftime("%Y%m%d")}.log'
        return os.path.join(log_dir, fname)

    def _write_log_file(self, msg):
        """Append one line to the daily OCR log. Failures are swallowed (UI keeps working)."""
        try:
            path = self._get_log_path()
            if self._log_path != path:
                self._log_path = path
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] {msg}\n')
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Current file label
        self.current_label = QLabel('Idle')
        self.current_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        layout.addWidget(self.current_label)

        # Progress bar
        prog_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_count = QLabel('')
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.progress_count)
        layout.addLayout(prog_layout)

        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet('font-family: monospace; font-size: 12px;')
        layout.addWidget(self.log)

        # Server status + buttons
        bottom_layout = QHBoxLayout()
        self.server_status_label = QLabel('Server: checking...')
        self.server_status_label.setStyleSheet('font-size: 12px; color: #888;')
        bottom_layout.addWidget(self.server_status_label)
        bottom_layout.addStretch()
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        bottom_layout.addWidget(self.cancel_btn)
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(self.close_btn)
        layout.addLayout(bottom_layout)

    def start(self, paper_file_ids, force_ids=None):
        """Start processing the given PaperFile IDs.

        If a run is already active, append the new IDs to the live queue
        instead of refusing — the user can stack collections without
        waiting for the current batch to finish.

        force_ids: PaperFile ids to re-OCR with force=true (ignore cache + tell
        the wrapper server to ignore its existing JSON) — used to retry failed
        PDFs.
        """
        force_ids = set(force_ids or [])
        if self._worker and self._worker.isRunning():
            self._worker.force_ids |= force_ids
            added = self._worker.enqueue(paper_file_ids)
            if added:
                self._total += added
                self.progress_bar.setRange(0, self._total)
                self.progress_count.setText(f'{self._done} / {self._total}')
                self._log_message(
                    f'+ Added {added} file(s) to queue (total now {self._total}).',
                    color='#3a8ee6',
                )
            else:
                self._log_message(
                    f'All {len(paper_file_ids)} requested file(s) already queued.',
                    color='gray',
                )
            self.show()
            self.raise_()
            return

        self._total = len(paper_file_ids)
        self._done = 0
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.progress_count.setText(f'0 / {self._total}')
        self.current_label.setText('Starting...')

        self._log_message(f'=== Starting: {self._total} files ===')
        self._log_message(f'Log file: {self._get_log_path()}', color='gray')

        self.cancel_btn.setEnabled(True)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        self._worker = ProcessWorker(paper_file_ids, force_ids=force_ids)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
        self.show()
        self.raise_()

    def _log_message(self, msg, color=None):
        # Full date: these batches routinely run past midnight for days, so a
        # bare clock time makes a pasted log ambiguous about which day it is.
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if color:
            self.log.append(f'<span style="color:{color}">[{ts}] {msg}</span>')
        else:
            self.log.append(f'[{ts}] {msg}')
        self._write_log_file(msg)

    def _on_progress(self, msg):
        self.current_label.setText(msg)
        self._log_message(msg)

    def _on_file_done(self, paper_file_id, status):
        self._done += 1
        self.progress_bar.setValue(self._done)
        self.progress_count.setText(f'{self._done} / {self._total}')

        from ..models import PaperFile
        pf = PaperFile.get_by_id(paper_file_id)
        name = os.path.basename(pf.path)

        if status == 'processed':
            self._log_message(f'  Done: {name}', color='green')
        else:
            self._log_message(f'  Failed: {name}', color='red')

        self.file_processed.emit(paper_file_id, status)
        self.processing_updated.emit()

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.current_label.setText('Cancelling...')
            self._log_message('Cancelling — waiting for in-progress files to finish...', color='orange')

    def _on_finished(self, processed, failed):
        QApplication.restoreOverrideCursor()
        cancelled = self._worker._cancelled if self._worker else False
        self._worker = None
        self.cancel_btn.setEnabled(False)
        if cancelled:
            self.current_label.setText('Cancelled')
            self._log_message(f'=== Cancelled: {processed} processed, {failed} failed ===', color='orange')
        else:
            self.current_label.setText('Finished')
            self._log_message(f'=== Complete: {processed} processed, {failed} failed ===')
        self.processing_updated.emit()

    def _poll_server_status(self):
        """Poll RunPod worker status in a background thread."""
        class _StatusPoller(QThread):
            result = pyqtSignal(str)
            def run(self_inner):  # noqa: N805 — distinct from the outer method's self
                try:
                    from ..ocr import check_health
                    h = check_health()
                    w = h.get('workers', {})
                    idle = w.get('idle', 0)
                    running = w.get('running', 0)
                    throttled = w.get('throttled', 0)
                    jobs = h.get('jobs', {})
                    in_progress = jobs.get('inProgress', 0)
                    in_queue = jobs.get('inQueue', 0)
                    parts = [f'{idle} idle, {running} running']
                    if throttled:
                        parts.append(f'{throttled} throttled')
                    if in_queue:
                        parts.append(f'{in_queue} queued')
                    if in_progress:
                        parts.append(f'{in_progress} in-progress')
                    self_inner.result.emit(f'Server: {", ".join(parts)}')
                except Exception as e:
                    self_inner.result.emit(f'Server: unavailable ({e})')

        poller = _StatusPoller(self)
        poller.result.connect(self.server_status_label.setText)
        poller.finished.connect(poller.deleteLater)
        poller.start()
        self._status_poller = poller  # prevent GC

    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def closeEvent(self, event):
        if self.is_running():
            # Don't close while processing, just hide
            event.ignore()
            self.hide()
        else:
            event.accept()
