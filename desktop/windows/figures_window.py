"""Non-modal progress window for "Process Figures" (P16 Phase 4).

Driven by the main window's serialized figure queue: `begin()` once,
`set_current()` as a paper starts, `note()` for what the pipeline reports
while a paper runs (stage names, jobs submitted, the server worker's state —
including a paused worker, which must read as waiting and not as a hang),
`record()` when a paper finishes and `finish()` when the queue drains.
"""
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_KIND_COLOR = {
    'ok': '#4ade80',
    'info': '#9aa0aa',
    'wait': '#f6c744',
    'warn': '#f6c744',
    'error': '#f87171',
}


class FiguresWindow(QWidget):
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Process Figures')
        self.setMinimumSize(720, 440)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._total = 0
        self._done = 0
        self._cancelled = False
        self._counts = {'ok': 0, 'error': 0}
        self._current = 'Idle'
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.current_label = QLabel('Idle')
        self.current_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        layout.addWidget(self.current_label)
        self.stage_label = QLabel('')
        self.stage_label.setStyleSheet('font-size: 12px; color: #9aa0aa;')
        layout.addWidget(self.stage_label)

        prog = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_count = QLabel('')
        prog.addWidget(self.progress_bar)
        prog.addWidget(self.progress_count)
        layout.addLayout(prog)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet('font-family: monospace; font-size: 12px;')
        layout.addWidget(self.log)

        bottom = QHBoxLayout()
        self.summary_label = QLabel('')
        self.summary_label.setStyleSheet('font-size: 12px; color: #888;')
        bottom.addWidget(self.summary_label)
        bottom.addStretch()
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self._on_cancel)
        bottom.addWidget(self.cancel_btn)
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        bottom.addWidget(self.close_btn)
        layout.addLayout(bottom)

    # ── driven by the main window ────────────────────────────────

    def begin(self, total: int):
        if self._total and self._done < self._total and not self._cancelled:
            self._total += total          # a second request extends the batch
        else:
            self._total, self._done, self._cancelled = total, 0, False
            self._counts = {'ok': 0, 'error': 0}
            self.log.clear()
            self._log('info', f'{datetime.now():%H:%M:%S}  Process Figures: {total} paper(s)')
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(self._done)
        self.progress_count.setText(f'{self._done} / {self._total}')
        self.cancel_btn.setEnabled(True)
        self.show()
        self.raise_()

    def set_current(self, title: str):
        self._current = title
        self.current_label.setText(f'Processing: {title}')
        self.stage_label.setText('')

    def note(self, kind: str, message: str):
        """What the pipeline says while a paper runs."""
        if kind == 'wait':
            self.current_label.setText(f'Waiting: {self._current}')
        else:
            self.current_label.setText(f'Processing: {self._current}')
        self.stage_label.setText(message)
        if kind != 'info' or message.endswith('…') or 'submitted' in message:
            self._log(kind, message)

    def record(self, title: str, ok: bool, detail: str):
        self._done += 1
        self._counts['ok' if ok else 'error'] += 1
        self.progress_bar.setValue(self._done)
        self.progress_count.setText(f'{self._done} / {self._total}')
        self._log('ok' if ok else 'error', f'{title}: {detail}')
        self.summary_label.setText(f"{self._counts['ok']} done, {self._counts['error']} failed")

    def mark_cancelling(self, dropped: int):
        self._cancelled = True
        self.cancel_btn.setEnabled(False)
        self._log('warn', f'Cancelled — {dropped} paper(s) dropped from the queue; the one in flight stops '
                          'at its next step (a job already on the server finishes there).')

    def finish(self):
        self.current_label.setText('Cancelled' if self._cancelled else 'Done')
        self.stage_label.setText('')
        self.cancel_btn.setEnabled(False)
        self._log('info', f'{datetime.now():%H:%M:%S}  {"cancelled" if self._cancelled else "finished"}: '
                          f"{self._counts['ok']} ok, {self._counts['error']} failed")

    def _on_cancel(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_requested.emit()

    def _log(self, kind: str, text: str):
        colour = _KIND_COLOR.get(kind, '#ddd')
        self.log.append(f'<span style="color:{colour}">{text}</span>')
