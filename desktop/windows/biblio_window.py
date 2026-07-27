"""Non-modal progress window for batch biblio extraction.

Mirrors the OCR ProcessWindow but is driven entirely by the main window's
existing serialized biblio queue (no worker of its own): the main window calls
`begin()` once, `set_current()` per paper as extraction starts, `record()` when
each finishes, and `finish()` when the queue drains.
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

# kind → colour for the log line
_KIND_COLOR = {
    'applied': '#4ade80',   # green
    'review':  '#fbbf24',   # amber
    'skip':    '#9aa0aa',   # gray
    'error':   '#f87171',   # red
    'info':    '#3a8ee6',   # blue
}


class BiblioWindow(QWidget):
    """Shows per-paper biblio extraction results + overall progress."""

    # Emitted when the user clicks Cancel; the main window drops the pending
    # queue and lets the in-flight paper finish.
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Biblio Extraction')
        self.setMinimumSize(720, 460)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._total = 0
        self._done = 0
        self._cancelled = False
        self._stop_label = 'Cancelled'   # label shown on finish() when stopped
        self._active = False             # a batch is in progress (drives begin() extend)
        self._counts = {'applied': 0, 'review': 0, 'skip': 0, 'error': 0}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.current_label = QLabel('Idle')
        self.current_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        layout.addWidget(self.current_label)

        prog_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_count = QLabel('')
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.progress_count)
        layout.addLayout(prog_layout)

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
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        bottom.addWidget(self.cancel_btn)
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        bottom.addWidget(self.close_btn)
        layout.addLayout(bottom)

    def _on_cancel_clicked(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_requested.emit()

    # ── Driven by main window ────────────────────────────────────

    def begin(self, total: int):
        """Start (or extend) a batch. If one is still in progress, add to the
        total; otherwise start fresh."""
        if self.isVisible() and self._active:
            self._total += total
            self._log(f'+ Added {total} paper(s) to queue (total {self._total}).', 'info')
        else:
            self._total = total
            self._done = 0
            self._counts = {'applied': 0, 'review': 0, 'skip': 0, 'error': 0}
            self.log.clear()
            self._log(f'=== Biblio extraction: {total} paper(s) ===')
        self._active = True
        self._cancelled = False
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(self._done)
        self.progress_count.setText(f'{self._done} / {self._total}')
        self.summary_label.setText('')
        self.cancel_btn.setEnabled(True)
        self.show()
        self.raise_()

    def mark_cancelling(self, dropped: int):
        """User cancelled: pending queue dropped; the in-flight paper finishes."""
        self._cancelled = True
        self._stop_label = 'Cancelled'
        self.cancel_btn.setEnabled(False)
        self.current_label.setText('Cancelling — finishing current paper…')
        self._log(f'Cancelled — dropped {dropped} queued paper(s); '
                  f'finishing the one in progress.', 'info')

    def mark_paused(self, remaining: int, detail: str):
        """Paused because the LLM server looks down: the queue is KEPT and the
        main window polls for recovery to auto-resume. Cancel still available."""
        self.current_label.setText('Paused — waiting for LLM server to recover…')
        self._log(f'Server unreachable: {detail} Paused with {remaining} '
                  f'paper(s) left — polling for recovery…', 'error')

    def mark_resumed(self, remaining: int):
        """Server came back — the main window is resuming the queue."""
        self.current_label.setText('Resuming…')
        self._log(f'Server back — resuming ({remaining} paper(s) left).', 'info')

    def add_total(self, n: int):
        """Grow the batch total (e.g. post-OCR auto-biblio items joining)."""
        self._total += n
        self.progress_bar.setRange(0, self._total)
        self.progress_count.setText(f'{self._done} / {self._total}')

    def set_current(self, text: str):
        self.current_label.setText(text)

    def record(self, summary: str, kind: str = 'info'):
        """Log one finished paper and advance the progress bar."""
        if kind in self._counts:
            self._counts[kind] += 1
        self._done += 1
        n = f'[{self._done}/{self._total}]'
        self._log(f'{n} {summary}', kind)
        self.progress_bar.setValue(min(self._done, self._total))
        self.progress_count.setText(f'{self._done} / {self._total}')

    def finish(self):
        self._active = False
        self.current_label.setText(self._stop_label if self._cancelled else 'Done')
        self.cancel_btn.setEnabled(False)
        c = self._counts
        prefix = f'{self._stop_label.lower()} · ' if self._cancelled else ''
        self.summary_label.setText(
            f"{prefix}applied {c['applied']} · review {c['review']} · "
            f"skip {c['skip']} · error {c['error']}"
        )

    def _log(self, msg: str, kind: str | None = None):
        # Full date: these batches routinely run past midnight for days, so a
        # bare clock time makes a pasted log ambiguous about which day it is.
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        color = _KIND_COLOR.get(kind or '')
        if color:
            self.log.append(f'<span style="color:{color}">[{ts}] {msg}</span>')
        else:
            self.log.append(f'[{ts}] {msg}')
