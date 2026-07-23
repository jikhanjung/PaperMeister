"""Non-modal progress window for local-folder import (scan + hash dedup).

Driven by ScanWorker signals from the main window: `begin()` when the scan
starts, `set_total()` once the pre-walk has counted the PDFs (bar goes
determinate), `on_progress()` per PDF, then `finish()` / `fail()`. The final
summary makes the common "nothing imported because it's all already in the DB"
case explicit.
"""
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ScanWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import Local Folder')
        self.setMinimumSize(640, 420)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._found = 0
        self._total = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.current_label = QLabel('Idle')
        self.current_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        layout.addWidget(self.current_label)

        prog = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_count = QLabel('')
        prog.addWidget(self.progress_bar)
        prog.addWidget(self.progress_count)
        layout.addLayout(prog)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet('font-family: monospace; font-size: 12px;')
        self.log.document().setMaximumBlockCount(3000)  # cap memory on big folders
        layout.addWidget(self.log)

        bottom = QHBoxLayout()
        self.summary_label = QLabel('')
        self.summary_label.setStyleSheet('font-size: 12px; color: #888;')
        bottom.addWidget(self.summary_label)
        bottom.addStretch()
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        bottom.addWidget(self.close_btn)
        layout.addLayout(bottom)

    # ── Driven by main window / ScanWorker ───────────────────────

    def begin(self, dir_path: str):
        self._found = 0
        self._total = 0
        self.log.clear()
        self.current_label.setText(f'Counting PDFs in  {dir_path} …')
        self.progress_bar.setRange(0, 0)   # busy until the pre-walk reports a total
        self.progress_count.setText('')
        self.summary_label.setText('')
        self.close_btn.setEnabled(False)
        self._log(f'=== Importing {dir_path} ===')
        self.show()
        self.raise_()

    def set_total(self, total: int):
        """Pre-walk finished — switch to a determinate X / N bar."""
        self._total = total
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_count.setText(f'0 / {total}')
        self.current_label.setText(f'Scanning {total} PDF(s) …')
        self._log(f'Found {total} PDF(s) on disk; scanning…')

    def on_progress(self, msg: str):
        self._found += 1
        if self._total:
            self.progress_bar.setValue(min(self._found, self._total))
            self.progress_count.setText(f'{self._found} / {self._total}')
        else:
            self.progress_count.setText(f'{self._found} found')
        self.current_label.setText(msg)
        self._log(msg)

    def finish(self, source_name: str, new_count: int):
        already = max(self._found - new_count, 0)
        self.progress_bar.setRange(0, max(self._total, 1))
        self.progress_bar.setValue(max(self._total, 1))
        self.current_label.setText('Done')
        self.progress_count.setText(f'{self._found} / {self._total or self._found}')
        self.summary_label.setText(
            f'new {new_count} · linked from existing {already} · total {self._found}'
        )
        self._log(
            f'=== Done: "{source_name}" — {new_count} new, '
            f'{already} linked from existing (matched by content hash) ==='
        )
        if self._found and new_count == 0:
            self._log(
                'All PDFs here already existed in the DB (e.g. the same files '
                'are in Zotero). No duplicates were created — they were linked '
                'into this folder, so they now appear under this tab too.'
            )
        self.close_btn.setEnabled(True)

    def fail(self, message: str):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.current_label.setText('Failed')
        self._log(f'ERROR: {message}')
        self.close_btn.setEnabled(True)

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log.append(f'[{ts}] {msg}')
