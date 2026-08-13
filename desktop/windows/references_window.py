"""Non-modal progress window for batch references extraction (P11).

Mirrors BiblioWindow: driven entirely by the main window's serialized
references queue (no worker of its own). The main window calls `begin()`
once, `set_current()` per paper as parsing starts, `record()` when each
finishes, and `finish()` when the queue drains.
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
    'ok':    '#4ade80',   # green — references parsed
    'empty': '#9aa0aa',   # gray  — no references section found
    'error': '#f87171',   # red
    'info':  '#3a8ee6',   # blue
}


class ReferencesWindow(QWidget):
    """Shows per-paper references parsing results + overall progress."""

    # Emitted when the user clicks Cancel; the main window drains the pending
    # queue and lets the in-flight paper finish (an LLM call can't be safely
    # interrupted mid-request).
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('References Extraction')
        self.setMinimumSize(720, 460)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._total = 0
        self._done = 0
        self._refs = 0
        self._cancelled = False
        self._stop_label = 'Cancelled'   # label shown on finish() when stopped
        self._current_text = 'Idle'      # restored after a mid-paper server wait
        self._active = False   # a batch is in progress (drives begin() extend)
        self._counts = {'ok': 0, 'empty': 0, 'error': 0}
        self._item_rows = {}   # paper_id -> (row widget, bar, count label)
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

        # One bar per paper in flight. Entry counts differ by orders of
        # magnitude — a nomenclator runs to 2,000 entries where an article has
        # 30 — so the batch bar alone cannot distinguish a long paper from a
        # stalled one. With several papers parsing at once a single shared bar
        # is worse than none: it would jump between unrelated papers' counts,
        # so each gets its own row and they come and go as papers do.
        self.items_box = QWidget()
        self.items_layout = QVBoxLayout(self.items_box)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(2)
        layout.addWidget(self.items_box)
        self.items_box.setVisible(False)

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

    # ── Per-paper progress rows ──────────────────────────────────

    def start_item(self, paper_id: int, title: str):
        """Add a row for a paper that just started parsing.

        Created up front rather than on the first progress callback, so a paper
        still finding its references section (which can take a while on a long
        PDF) is visibly present rather than missing.
        """
        if paper_id in self._item_rows:
            return
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)

        name = QLabel()
        name.setStyleSheet('font-size: 11px; color: #aaa;')
        name.setFixedWidth(260)
        # Elide rather than let Qt clip: a title cut mid-word looks like a
        # different paper, and these rows are how you tell them apart.
        name.setText(name.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, name.width()))
        name.setToolTip(title)
        bar = QProgressBar()
        bar.setMaximumHeight(10)
        bar.setTextVisible(False)
        bar.setRange(0, 0)          # busy until the entry count is known
        count = QLabel('starting…')
        count.setStyleSheet('font-size: 11px; color: #888;')
        count.setMinimumWidth(150)

        hbox.addWidget(name)
        hbox.addWidget(bar)
        hbox.addWidget(count)
        self.items_layout.addWidget(row)
        self._item_rows[paper_id] = (row, bar, count)
        self.items_box.setVisible(True)

    def set_item_progress(self, paper_id: int, done: int, total: int):
        """Progress within one paper being parsed."""
        entry = self._item_rows.get(paper_id)
        if not entry:
            return
        _row, bar, count = entry
        if total <= 0:
            bar.setRange(0, 0)
            count.setText('scanning…')
            return
        bar.setRange(0, total)
        bar.setValue(done)
        count.setText(f'{done} / {total} refs  ({done * 100 // total}%)')

    def end_item(self, paper_id: int):
        """Drop a finished paper's row."""
        entry = self._item_rows.pop(paper_id, None)
        if not entry:
            return
        row = entry[0]
        self.items_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        if not self._item_rows:
            self.items_box.setVisible(False)

    def _clear_items(self):
        for paper_id in list(self._item_rows):
            self.end_item(paper_id)

    def _on_cancel_clicked(self):
        # Disable immediately so it can't be double-fired; the main window will
        # relabel us via mark_cancelling().
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
            self._refs = 0
            self._counts = {'ok': 0, 'empty': 0, 'error': 0}
            self.log.clear()
            self._log(f'=== References extraction: {total} paper(s) ===')
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
        """User asked to cancel: the pending queue was dropped; only the paper
        already in flight will finish."""
        self._cancelled = True
        self._stop_label = 'Cancelled'
        self.cancel_btn.setEnabled(False)
        self.current_label.setText('Cancelling — finishing current paper…')
        self._log(f'Cancelled — dropped {dropped} queued paper(s); '
                  f'finishing the one in progress.', 'info')

    def mark_paused(self, remaining: int, detail: str):
        """Paused because the LLM server looks down: the queue is KEPT and the
        main window polls for recovery to auto-resume. Not terminal — Cancel is
        still available."""
        self.current_label.setText('Paused — waiting for LLM server to recover…')
        self._log(f'Server unreachable: {detail} Paused with {remaining} '
                  f'paper(s) left — polling for recovery…', 'error')

    def mark_resumed(self, remaining: int):
        """Server came back — the main window is resuming the queue."""
        self.current_label.setText('Resuming…')
        self._log(f'Server back — resuming ({remaining} paper(s) left).', 'info')

    def mark_server_wait(self, detail: str):
        """A gateway 5xx hit the paper being parsed: the model container is
        restarting and the worker is waiting it out.

        Not the same thing as `mark_paused` — the batch is not paused and the
        queue is untouched; the wait happens inside the current paper and the
        same batch resumes afterwards. Shown because it lasts minutes, during
        which "Parsing: <title>" alone is indistinguishable from a hang."""
        self.current_label.setText('LLM server down — waiting for it to come back…')
        self._log(detail, 'error')

    def mark_server_back(self, detail: str, recovered: bool = True):
        """The mid-paper wait ended — either the server answered again (parsing
        resumes) or the wait ran out (the paper will fail and be retried
        later). Either way the label goes back to whatever we were parsing."""
        self.current_label.setText(self._current_text)
        self._log(detail, 'info' if recovered else 'error')

    def add_total(self, n: int):
        self._total += n
        self.progress_bar.setRange(0, self._total)
        self.progress_count.setText(f'{self._done} / {self._total}')

    def set_current(self, text: str):
        # Rows are owned by start_item/end_item now — this only relabels the
        # headline, so a mid-paper server notice can't wipe the live bars.
        self._current_text = text
        self.current_label.setText(text)

    def record(self, summary: str, kind: str = 'info', refs: int = 0):
        """Log one finished paper and advance the progress bar."""
        if kind in self._counts:
            self._counts[kind] += 1
        self._refs += refs
        self._done += 1
        n = f'[{self._done}/{self._total}]'
        self._log(f'{n} {summary}', kind)
        self.progress_bar.setValue(min(self._done, self._total))
        self.progress_count.setText(f'{self._done} / {self._total}')

    def finish(self):
        self._active = False
        self._clear_items()   # nothing is in flight any more
        self.current_label.setText(self._stop_label if self._cancelled else 'Done')
        self.cancel_btn.setEnabled(False)
        c = self._counts
        prefix = f'{self._stop_label.lower()} · ' if self._cancelled else ''
        self.summary_label.setText(
            f"{prefix}parsed {c['ok']} · empty {c['empty']} · error {c['error']} "
            f"· {self._refs} references"
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
