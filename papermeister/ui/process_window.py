import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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

    def _next_index(self):
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def _process_one(self, pf_id):
        """Process a single PaperFile. Runs in a thread pool thread."""
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
                if future.result():
                    processed += 1
                else:
                    failed += 1

        self.finished.emit(processed, failed)


class ProcessWindow(QWidget):
    """Non-modal window showing OCR processing progress with a log."""
    processing_updated = pyqtSignal()  # emitted when a file finishes (for main window refresh)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('OCR Processing')
        self.setMinimumSize(700, 450)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._worker = None
        self._setup_ui()

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

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

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

        self.processing_updated.emit()

    def _on_finished(self, processed, failed):
        QApplication.restoreOverrideCursor()
        self._worker = None
        self.current_label.setText('Finished')
        self._log_message(f'=== Complete: {processed} processed, {failed} failed ===')
        self.processing_updated.emit()

    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def closeEvent(self, event):
        if self.is_running():
            # Don't close while processing, just hide
            event.ignore()
            self.hide()
        else:
            event.accept()
