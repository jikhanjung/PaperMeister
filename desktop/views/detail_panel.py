"""Right detail panel: metadata card + biblio diff card + OCR preview card.

This is the minimum useful detail surface for Phase 3. Phase 4 wires in
`biblio_reflect.evaluate()` and enables the Apply button.
"""
import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop.services import biblio_service, paper_service
from desktop.theme.tokens import SPACING
from desktop.workers.background import BackgroundTask


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty('class', 'FieldLabel')
    return lbl


def _field_value(text: str, stub: bool = False) -> QLabel:
    lbl = QLabel(text if text else '—')
    lbl.setWordWrap(True)
    lbl.setProperty('class', 'FieldValueStub' if stub else 'FieldValue')
    return lbl


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty('class', 'Card')
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(SPACING['lg'], SPACING['md'], SPACING['lg'], SPACING['md'])
    layout.setSpacing(SPACING['sm'])

    title_lbl = QLabel(title)
    title_lbl.setProperty('class', 'CardTitle')
    layout.addWidget(title_lbl)
    return frame, layout


class DetailPanel(QScrollArea):
    apply_completed = pyqtSignal(int, bool, str)  # paper_id, changed, action

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('DetailPanel')
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self.setWidget(self._container)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        self._layout.setSpacing(SPACING['md'])

        self._current_paper_id: int | None = None
        self._apply_task: BackgroundTask | None = None
        self._apply_btn: QPushButton | None = None

        self._empty_state()

    # ── State ────────────────────────────────────────────────

    def clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _empty_state(self):
        self.clear()
        msg = QLabel('Select a paper to see details')
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setProperty('class', 'FieldLabel')
        self._layout.addStretch(1)
        self._layout.addWidget(msg)
        self._layout.addStretch(2)

    def show_paper(self, paper_id: int):
        detail = paper_service.load_detail(paper_id)
        if detail is None:
            self._empty_state()
            return
        self.clear()
        self._apply_btn = None
        self._current_paper_id = paper_id

        if detail.is_stub:
            banner = QLabel('Stub metadata. Run biblio extraction to fill.')
            banner.setProperty('class', 'StubBanner')
            banner.setWordWrap(True)
            self._layout.addWidget(banner)

        self._layout.addWidget(self._build_metadata_card(detail))
        if detail.latest_biblio:
            preview = biblio_service.preview_apply(paper_id)
            self._layout.addWidget(self._build_biblio_card(detail, preview))
        self._layout.addWidget(self._build_file_card(detail))
        self._layout.addStretch(1)

    # ── Cards ────────────────────────────────────────────────

    def _build_metadata_card(self, d) -> QFrame:
        frame, layout = _card('METADATA')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(SPACING['lg'])
        grid.setVerticalSpacing(SPACING['sm'])
        grid.setColumnStretch(1, 1)

        def add_row(r, label, value, stub=False):
            grid.addWidget(_field_label(label), r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_field_value(value, stub=stub), r, 1)

        title_text = d.title if d.title else 'Untitled — ' + (d.file_path.split('/')[-1] if d.file_path else '')
        add_row(0, 'Title',   title_text, stub=d.is_stub and not d.title)
        add_row(1, 'Authors', d.authors, stub=not d.authors)
        add_row(2, 'Year',    str(d.year) if d.year is not None else '—', stub=d.year is None)
        add_row(3, 'Journal', d.journal, stub=not d.journal)
        add_row(4, 'DOI',     d.doi, stub=not d.doi)
        add_row(5, 'Source',  f'{d.source_name} / {d.folder_name}' if d.folder_name else d.source_name)
        layout.addLayout(grid)
        return frame

    def _build_biblio_card(self, d, preview) -> QFrame:
        frame, layout = _card('EXTRACTED BIBLIO')
        b = d.latest_biblio
        meta = QLabel(
            f"{b.get('source', '')}  ·  confidence: {b.get('confidence', '—')}  ·  "
            f"doc_type: {b.get('doc_type', '—')}  ·  status: {preview.biblio_status}"
        )
        meta.setProperty('class', 'FieldLabel')
        layout.addWidget(meta)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACING['lg'])
        grid.setVerticalSpacing(SPACING['sm'])
        grid.setColumnStretch(1, 1)

        try:
            authors_list = json.loads(b.get('authors_json') or '[]')
        except Exception:
            authors_list = []
        authors_str = ', '.join(a.get('name', '') if isinstance(a, dict) else str(a)
                                 for a in authors_list)

        def add_row(r, label, value):
            grid.addWidget(_field_label(label), r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_field_value(value or '—'), r, 1)

        add_row(0, 'Title',   b.get('title') or '')
        add_row(1, 'Authors', authors_str)
        add_row(2, 'Year',    str(b.get('year')) if b.get('year') else '')
        add_row(3, 'Journal', b.get('journal') or '')
        add_row(4, 'DOI',     b.get('doi') or '')
        layout.addLayout(grid)

        # Decision line
        decision_label = QLabel(self._decision_line(preview))
        decision_label.setProperty('class', 'FieldLabel')
        decision_label.setWordWrap(True)
        layout.addWidget(decision_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        apply_btn = QPushButton(preview.button_label)
        apply_btn.setProperty('class', 'Primary')
        # Re-polish so the Primary class styling kicks in.
        style = apply_btn.style()
        if style is not None:
            style.unpolish(apply_btn)
            style.polish(apply_btn)
        apply_btn.setEnabled(preview.button_enabled)
        apply_btn.setToolTip(preview.tooltip)
        apply_btn.clicked.connect(self._on_apply_clicked)
        self._apply_btn = apply_btn
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)
        return frame

    def _decision_line(self, preview) -> str:
        if preview.decision_action == 'auto_commit':
            return 'Decision: auto-commit (all P08 gates passed)'
        if preview.decision_action == 'needs_review':
            return f'Decision: needs review — {preview.decision_reason}'
        return f'Decision: skip — {preview.decision_reason}'

    def _on_apply_clicked(self):
        if self._current_paper_id is None or self._apply_btn is None:
            return
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText('Applying…')
        task = BackgroundTask(biblio_service.apply_paper, self._current_paper_id)
        task.done.connect(self._on_apply_done)
        task.failed.connect(self._on_apply_failed)
        self._apply_task = task
        task.start()

    def _on_apply_done(self, result):
        action, changed, reason = result
        pid = self._current_paper_id
        if self._apply_btn is not None:
            if changed:
                self._apply_btn.setText('Applied')
            else:
                self._apply_btn.setText('No change')
            self._apply_btn.setEnabled(False)
        if pid is not None:
            self.apply_completed.emit(pid, changed, action)
            # Refresh the panel to show updated Paper values.
            self.show_paper(pid)

    def _on_apply_failed(self, message: str):
        if self._apply_btn is not None:
            self._apply_btn.setText('Failed')
            self._apply_btn.setToolTip(message)
            self._apply_btn.setEnabled(True)

    def _build_file_card(self, d) -> QFrame:
        frame, layout = _card('FILE')
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACING['lg'])
        grid.setVerticalSpacing(SPACING['sm'])
        grid.setColumnStretch(1, 1)

        def add_row(r, label, value):
            grid.addWidget(_field_label(label), r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_field_value(value), r, 1)

        add_row(0, 'Path',   d.file_path or '—')
        add_row(1, 'Status', d.file_status)
        add_row(2, 'Hash',   d.file_hash[:16] + '…' if len(d.file_hash) > 16 else (d.file_hash or '—'))
        layout.addLayout(grid)
        return frame
