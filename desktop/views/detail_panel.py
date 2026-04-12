"""Right detail panel: tabbed view of a selected paper.

Tabs
----
- Metadata   — Paper metadata + File card (always populated)
- Biblio     — Latest PaperBiblio + Apply button (empty state if missing)
- OCR        — Rendered markdown from ~/.papermeister/ocr_json/{hash}.json
               via QTextBrowser.setMarkdown (empty state if not processed)

Stub banner sits above the tab bar so it is visible regardless of tab.
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
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from desktop.services import biblio_service, paper_service
from desktop.theme.tokens import FONT, SPACING
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


def _scroll_wrap(inner: QWidget) -> QScrollArea:
    """Wrap a widget in a borderless scroll area for tab content."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.Shape.NoFrame)
    sa.setWidget(inner)
    return sa


def _empty_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setProperty('class', 'FieldLabel')
    lbl.setWordWrap(True)
    return lbl


class DetailPanel(QWidget):
    apply_completed = pyqtSignal(int, bool, str)  # paper_id, changed, action

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('DetailPanel')

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Stub banner sits above the tabs so it persists across tab switches.
        self._banner = QLabel('')
        self._banner.setProperty('class', 'StubBanner')
        self._banner.setWordWrap(True)
        self._banner.setContentsMargins(
            SPACING['lg'], SPACING['md'], SPACING['lg'], SPACING['md']
        )
        self._banner.hide()
        root.addWidget(self._banner)

        self._tabs = QTabWidget()
        self._tabs.setObjectName('DetailTabs')
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)

        # Lazy-refilled per paper.
        self._metadata_host: QWidget | None = None
        self._biblio_host: QWidget | None = None
        self._ocr_browser: QTextBrowser | None = None

        self._current_paper_id: int | None = None
        self._apply_task: BackgroundTask | None = None
        self._apply_btn: QPushButton | None = None

        self._empty_state()

    # ── Top-level state ──────────────────────────────────────

    def _empty_state(self):
        self._banner.hide()
        self._tabs.clear()
        placeholder = _empty_label('Select a paper to see details')
        self._tabs.addTab(placeholder, 'Details')

    def show_paper(self, paper_id: int):
        detail = paper_service.load_detail(paper_id)
        if detail is None:
            self._empty_state()
            return

        self._current_paper_id = paper_id
        self._apply_btn = None

        # Stub banner
        if detail.is_stub:
            self._banner.setText('Stub metadata. Run biblio extraction to fill.')
            self._banner.show()
        else:
            self._banner.hide()

        # Rebuild all three tabs from scratch — simpler than patching in place,
        # and the tree is small enough that this is imperceptible.
        current_idx = self._tabs.currentIndex() if self._tabs.count() > 0 else 0
        self._tabs.clear()

        self._tabs.addTab(self._build_metadata_tab(detail), 'Metadata')
        self._tabs.addTab(self._build_biblio_tab(detail), 'Biblio')
        self._tabs.addTab(self._build_ocr_tab(detail), 'OCR')

        # Restore previously-selected tab when switching papers so the user
        # doesn't get snapped back to Metadata every click.
        if 0 <= current_idx < self._tabs.count():
            self._tabs.setCurrentIndex(current_idx)

    # ── Metadata tab ─────────────────────────────────────────

    def _build_metadata_tab(self, d) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['md'])

        layout.addWidget(self._build_metadata_card(d))
        layout.addWidget(self._build_file_card(d))
        layout.addStretch(1)
        return _scroll_wrap(host)

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
        add_row(5, 'Source',  d.source_name or '—')
        if d.collections:
            paths = '\n'.join(path for _, path in d.collections)
            add_row(6, 'Collection', paths)
        layout.addLayout(grid)
        return frame

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

    # ── Biblio tab ───────────────────────────────────────────

    def _build_biblio_tab(self, d) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['md'])

        if not d.latest_biblio:
            layout.addWidget(_empty_label(
                'No biblio extracted yet.\n'
                'Run scripts/extract_biblio.py for this paper to populate.'
            ))
            layout.addStretch(1)
            return _scroll_wrap(host)

        preview = biblio_service.preview_apply(d.paper_id)
        layout.addWidget(self._build_biblio_card(d, preview))
        layout.addStretch(1)
        return _scroll_wrap(host)

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

    # ── OCR tab ──────────────────────────────────────────────

    def _build_ocr_tab(self, d) -> QWidget:
        """Render OCR markdown for processed papers.

        Uses `papermeister.biblio.load_ocr_pages()` which reads the raw
        JSON cache at ~/.papermeister/ocr_json/{hash}.json. Pages are
        joined with horizontal rules + page markers so QTextBrowser's
        markdown renderer shows a continuous document.
        """
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not d.file_hash:
            return self._ocr_empty_panel(
                'No file hash on this paper. OCR cache is keyed by file hash.'
            )
        if d.file_status != 'processed':
            return self._ocr_empty_panel(
                f'This paper has not been OCR-processed yet (status: {d.file_status}).\n'
                'Run the Process action to OCR it.'
            )

        from papermeister.biblio import load_ocr_pages

        try:
            pages = load_ocr_pages(d.file_hash)
        except Exception as exc:
            return self._ocr_empty_panel(f'Failed to read OCR cache: {exc}')

        if not pages:
            return self._ocr_empty_panel(
                'OCR cache file missing or empty.\n'
                f'Expected: ~/.papermeister/ocr_json/{d.file_hash[:16]}….json'
            )

        browser = QTextBrowser()
        browser.setObjectName('OcrBrowser')
        browser.setOpenExternalLinks(True)
        browser.setReadOnly(True)
        # Make text selectable + comfortable to read.
        browser.setStyleSheet(
            f"QTextBrowser#OcrBrowser {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  padding: {SPACING['lg']}px;"
            f"  font-size: {FONT['size.md']}px;"
            f"}}"
        )
        markdown_text = self._join_pages_as_markdown(pages)
        browser.setMarkdown(markdown_text)
        self._ocr_browser = browser

        layout.addWidget(browser, 1)
        return host

    def _ocr_empty_panel(self, message: str) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.addStretch(1)
        layout.addWidget(_empty_label(message))
        layout.addStretch(2)
        return host

    @staticmethod
    def _sanitize_ocr_markdown(text: str) -> str:
        """Neutralize markdown patterns that cause spurious indentation.

        Chandra2 OCR output isn't structured markdown — it's paper text
        with OCR artifacts. Feeding it to `QTextDocument.setMarkdown()`
        raw triggers two problems that look like "text keeps moving right":

        1. Numbered lines like `1. foo` / `2. bar` (plate captions,
           reference lists, numbered abstract points) get parsed as
           `<ol><li>` blocks, each with a left indent. Academic papers
           have hundreds of these per document.
        2. Lines starting with 4+ spaces become indented code blocks,
           which adds further indent + monospace font. OCR of tables,
           equations, and column gutters routinely emits these.

        We strip leading whitespace from every line, escape ordered-list
        markers at line start with a backslash (`1. ` → `1\\. `), and
        collapse runs of 3+ blank lines down to two for readability.
        Bold/italic/headings/links are preserved as-is.
        """
        import re
        lines = text.splitlines()
        out: list[str] = []
        # Match any line that begins with `digits.` — catches both
        # `1. foo` (list-looking) and bare `88.` (volume numbers on
        # their own line in reference sections). The latter caused the
        # real damage: Qt's markdown parser treats `88.\n\n9.\n\n22.`
        # as a sequence of ordered-list starts and then *nests* them,
        # producing cumulative `-qt-list-indent: 1, 2, 3, 4` in the
        # generated HTML, which is what the user sees as "text keeps
        # moving to the right".
        ol_re = re.compile(r'^(\d+)\.')
        for line in lines:
            stripped = line.lstrip()
            # Bullets (`- `, `* `) are left alone — Chandra2 rarely
            # emits bullet-looking lines and the false-positive rate
            # would be high if we touched them.
            stripped = ol_re.sub(lambda m: f'{m.group(1)}\\.', stripped)
            out.append(stripped)
        joined = '\n'.join(out)
        # Collapse runs of 3+ blank lines to max 2 (one paragraph break).
        joined = re.sub(r'\n{3,}', '\n\n', joined)
        return joined.strip()

    @classmethod
    def _join_pages_as_markdown(cls, pages: list[str]) -> str:
        """Concatenate sanitized page markdowns into one document.

        Separators use a horizontal rule + an italic page marker so the
        boundary is visible in rendered output without fighting real
        headings that may live inside each page.
        """
        parts: list[str] = []
        for idx, page_md in enumerate(pages, start=1):
            clean = cls._sanitize_ocr_markdown(page_md or '')
            if not clean:
                continue
            parts.append(f'*— page {idx} —*\n\n{clean}')
        return '\n\n---\n\n'.join(parts) if parts else ''
