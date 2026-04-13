import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor
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

    def __init__(self, paper_file_ids):
        super().__init__()
        self.paper_file_ids = paper_file_ids
        self._counter = 0
        self._counter_lock = None
        self._cancelled = False

    def _next_index(self):
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def cancel(self):
        self._cancelled = True

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
            )
            self.file_done.emit(pf_id, 'processed')
            return True
        except Exception as e:
            pf.status = 'failed'
            pf.save()
            self.progress.emit(f'{prefix}   FAILED: {e}')
            self.file_done.emit(pf_id, 'failed')
            return False

    def run(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from ..ocr import ensure_workers_ready, get_worker_status

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

        processed = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {
                pool.submit(self._process_one, pf_id): pf_id
                for pf_id in self.paper_file_ids
            }
            for future in as_completed(futures):
                if self._cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                result = future.result()
                if result is True:
                    processed += 1
                elif result is False:
                    failed += 1

        self.finished.emit(processed, failed)


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
        self._setup_ui()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_server_status)
        self._status_timer.start(5000)
        self._poll_server_status()

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

    def start(self, paper_file_ids):
        """Start processing the given PaperFile IDs."""
        if self._worker and self._worker.isRunning():
            self._log_message('Already processing — please wait.', color='orange')
            return

        self._total = len(paper_file_ids)
        self._done = 0
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.progress_count.setText(f'0 / {self._total}')
        self.current_label.setText('Starting...')

        self._log_message(f'=== Starting: {self._total} files ===')

        self.cancel_btn.setEnabled(True)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        self._worker = ProcessWorker(paper_file_ids)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
        self.show()
        self.raise_()

    def _log_message(self, msg, color=None):
        ts = datetime.now().strftime('%H:%M:%S')
        if color:
            self.log.append(f'<span style="color:{color}">[{ts}] {msg}</span>')
        else:
            self.log.append(f'[{ts}] {msg}')

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
            def run(self_inner):
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
