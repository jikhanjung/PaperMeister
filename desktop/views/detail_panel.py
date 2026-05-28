"""Right detail panel: tabbed view of a selected paper.

Tabs
----
- Metadata   — Paper metadata + File card + Biblio comparison (if extracted)
- PDF        — Rendered PDF pages via PyMuPDF
- Text       — Rendered markdown from ~/.papermeister/ocr_json/{hash}.json
               via QTextBrowser.setMarkdown (empty state if not processed)

Stub banner sits above the tab bar so it is visible regardless of tab.
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
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


class _LazyPdfView(QScrollArea):
    """Scroll area that renders PDF pages on demand as they enter the viewport.

    Page placeholders are sized upfront from `page.rect` (cheap — no decode),
    so the scrollbar reflects total document height immediately. Pages are
    decoded to QPixmap only when they overlap the viewport plus a lookahead.
    """

    _ZOOM = 1.5
    _LOOKAHEAD_PX = 800

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        import fitz
        self._doc = doc
        self._matrix = fitz.Matrix(self._ZOOM, self._ZOOM)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING['sm'])

        self._page_labels: list[QLabel] = []
        self._rendered: list[bool] = []

        for i in range(len(doc)):
            page = doc[i]
            w = int(page.rect.width * self._ZOOM)
            h = int(page.rect.height * self._ZOOM)
            lbl = QLabel()
            lbl.setFixedSize(w, h)
            lbl.setStyleSheet('background: #1a1a1a;')
            layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._page_labels.append(lbl)
            self._rendered.append(False)

        layout.addStretch(1)
        self.setWidget(container)

        self.verticalScrollBar().valueChanged.connect(self._render_visible)
        # Defer first render so label .y() is populated by the layout pass.
        QTimer.singleShot(0, self._render_visible)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_visible()

    def _render_visible(self):
        if self._doc is None:
            return
        vp_top = self.verticalScrollBar().value()
        vp_bottom = vp_top + self.viewport().height()
        for i, lbl in enumerate(self._page_labels):
            if self._rendered[i]:
                continue
            y_top = lbl.y()
            y_bottom = y_top + lbl.height()
            if y_bottom < vp_top - self._LOOKAHEAD_PX:
                continue
            if y_top > vp_bottom + self._LOOKAHEAD_PX:
                continue
            self._render_page(i)

    def _render_page(self, idx: int):
        if self._rendered[idx] or self._doc is None:
            return
        from PyQt6.QtGui import QImage, QPixmap
        page = self._doc[idx]
        pix = page.get_pixmap(matrix=self._matrix)
        fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        self._page_labels[idx].setPixmap(QPixmap.fromImage(qimg))
        self._rendered[idx] = True


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
        self._current_detail = None
        self._pdf_built = False
        self._text_built = False
        self._pdf_wrapper: QWidget | None = None
        self._text_wrapper: QWidget | None = None
        self._apply_task: BackgroundTask | None = None
        self._apply_btn: QPushButton | None = None
        self._biblio_id: int | None = None
        # field_key → (QButtonGroup, 'paper'|'biblio' default)
        self._field_groups: dict[str, QButtonGroup] = {}

        self._empty_state()

    # ── Top-level state ──────────────────────────────────────

    def _empty_state(self):
        self._banner.hide()
        self._current_detail = None
        self._current_paper_id = None
        try:
            self._tabs.currentChanged.disconnect(self._on_tab_changed)
        except (TypeError, RuntimeError):
            pass
        self._tabs.clear()
        placeholder = _empty_label('Select a paper to see details')
        self._tabs.addTab(placeholder, 'Details')

    def show_paper(self, paper_id: int):
        detail = paper_service.load_detail(paper_id)
        if detail is None:
            self._empty_state()
            return

        self._current_paper_id = paper_id
        self._current_detail = detail
        self._apply_btn = None

        # Stub banner
        if detail.is_stub:
            self._banner.setText('Stub metadata. Run biblio extraction to fill.')
            self._banner.show()
        else:
            self._banner.hide()

        current_idx = self._tabs.currentIndex() if self._tabs.count() > 0 else 0

        # Drop the prior connection before clear(); clear() doesn't detach signals.
        try:
            self._tabs.currentChanged.disconnect(self._on_tab_changed)
        except (TypeError, RuntimeError):
            pass

        self._tabs.clear()
        self._pdf_built = False
        self._text_built = False

        # Metadata is cheap — build now. PDF/Text wrappers stay empty until
        # the user activates the tab; that's where the OCR-JSON read and
        # PDF page renders happen.
        self._tabs.addTab(self._build_metadata_tab(detail), 'Metadata')
        self._pdf_wrapper = self._make_lazy_wrapper()
        self._tabs.addTab(self._pdf_wrapper, 'PDF')
        self._text_wrapper = self._make_lazy_wrapper()
        self._tabs.addTab(self._text_wrapper, 'Text')

        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Restore previously-selected tab when switching papers so the user
        # doesn't get snapped back to Metadata every click.
        if 0 <= current_idx < self._tabs.count():
            self._tabs.setCurrentIndex(current_idx)

        # setCurrentIndex doesn't fire currentChanged if the index is unchanged,
        # so force a build check for the active tab.
        self._on_tab_changed(self._tabs.currentIndex())

    @staticmethod
    def _make_lazy_wrapper() -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return w

    def _on_tab_changed(self, idx: int):
        if self._current_detail is None:
            return
        if idx == 1 and not self._pdf_built and self._pdf_wrapper is not None:
            self._pdf_built = True
            self._pdf_wrapper.layout().addWidget(
                self._build_pdf_tab(self._current_detail)
            )
        elif idx == 2 and not self._text_built and self._text_wrapper is not None:
            self._text_built = True
            self._text_wrapper.layout().addWidget(
                self._build_ocr_tab(self._current_detail)
            )

    # ── Metadata tab ─────────────────────────────────────────

    def _build_metadata_tab(self, d) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.setSpacing(SPACING['md'])

        layout.addWidget(self._build_metadata_card(d))
        layout.addWidget(self._build_file_card(d))

        # Biblio comparison section (merged from former Biblio tab)
        if d.latest_biblio:
            preview = biblio_service.preview_apply(d.paper_id)
            self._biblio_id = preview.biblio_id
            self._field_groups = {}
            self._field_edits: dict[str, QLineEdit | QPlainTextEdit] = {}
            layout.addWidget(self._build_comparison_card(preview))
        else:
            self._biblio_id = None
            self._field_groups = {}

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
        next_row = 6
        if d.paper_zotero_key:
            add_row(next_row, 'Zotero Key', d.paper_zotero_key)
            next_row += 1
        if d.collections:
            paths = '\n'.join(path for _, path in d.collections)
            add_row(next_row, 'Collection', paths)
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

    # ── PDF view tab ─────────────────────────────────────────

    def _build_pdf_tab(self, d) -> QWidget:
        """Render PDF pages as images using PyMuPDF."""
        if not d.file_path and not d.file_hash:
            return self._ocr_empty_panel('No PDF file associated with this paper.')
        if d.file_status not in ('processed', 'pending', 'failed'):
            return self._ocr_empty_panel('No PDF file associated with this paper.')

        import os

        pdf_path = d.file_path
        if not pdf_path or not os.path.isfile(pdf_path):
            # Check pdf_cache
            if d.file_zotero_key and d.file_path:
                cached = os.path.join(
                    os.path.expanduser('~'), '.papermeister', 'pdf_cache',
                    d.file_zotero_key, d.file_path,
                )
                if os.path.isfile(cached):
                    pdf_path = cached
            if not pdf_path or not os.path.isfile(pdf_path):
                if d.file_zotero_key:
                    return self._build_pdf_download_panel(d)
                return self._ocr_empty_panel(
                    'PDF file not found locally.\n'
                    f'Path: {d.file_path or "(none)"}'
                )

        return self._render_pdf(pdf_path)

    def _render_pdf(self, pdf_path: str) -> QWidget:
        """Open the PDF and hand it to the lazy-render scroll view."""
        import fitz
        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            return self._ocr_empty_panel(f'Failed to open PDF: {exc}')
        return _LazyPdfView(doc)

    def _build_pdf_download_panel(self, d) -> QWidget:
        """Show a download button for Zotero-hosted PDFs."""
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(SPACING['lg'], SPACING['lg'], SPACING['lg'], SPACING['lg'])
        layout.addStretch(1)

        msg = _empty_label(
            'PDF file not available locally.\n'
            'Click below to download from Zotero.'
        )
        layout.addWidget(msg)

        btn = QPushButton('Download PDF')
        btn.setProperty('class', 'Primary')
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedWidth(160)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._download_status = _empty_label('')
        layout.addWidget(self._download_status)
        layout.addStretch(2)

        zotero_key = d.file_zotero_key
        filename = d.file_path or f'{zotero_key}.pdf'
        paper_id = d.paper_id

        def _on_download():
            btn.setEnabled(False)
            btn.setText('Downloading…')
            self._download_status.setText('')

            task = BackgroundTask(self._download_zotero_pdf, zotero_key, filename)
            task.done.connect(lambda path: _on_downloaded(path))
            task.failed.connect(lambda msg: _on_download_failed(msg))
            self._pdf_download_task = task
            task.start()

        def _on_downloaded(path):
            btn.setText('Downloaded')
            self._download_status.setText('')
            # Swap the download panel out for the rendered view inside the
            # same wrapper — removing the tab would break the lazy-tab indices.
            wrapper = self._pdf_wrapper
            if wrapper is None:
                return
            try:
                lay = wrapper.layout()
                while lay.count():
                    item = lay.takeAt(0)
                    w = item.widget()
                    if w:
                        w.deleteLater()
                lay.addWidget(self._render_pdf(path))
            except RuntimeError:
                pass  # wrapper destroyed (user switched papers mid-download)

        def _on_download_failed(msg):
            btn.setEnabled(True)
            btn.setText('Download PDF')
            self._download_status.setText(f'Failed: {msg}')

        btn.clicked.connect(_on_download)
        return host

    @staticmethod
    def _download_zotero_pdf(zotero_key: str, filename: str) -> str:
        """Download PDF from Zotero to cache. Returns local path."""
        import os
        from papermeister.zotero_client import ZoteroClient
        from papermeister.preferences import get_pref

        cache_dir = os.path.join(
            os.path.expanduser('~'), '.papermeister', 'pdf_cache', zotero_key,
        )
        cached = os.path.join(cache_dir, filename)
        if os.path.isfile(cached):
            return cached

        client = ZoteroClient(get_pref('zotero_user_id'), get_pref('zotero_api_key'))
        content = client.download_file_content(zotero_key)

        os.makedirs(cache_dir, exist_ok=True)
        with open(cached, 'wb') as f:
            f.write(content)
        return cached

    # ── Comparison card internals ────────────────────────────

    def _build_comparison_card(self, preview) -> QFrame:
        frame, layout = _card('BIBLIO COMPARISON')

        # Source metadata line
        if preview.source_line:
            meta = QLabel(preview.source_line)
            meta.setProperty('class', 'FieldLabel')
            layout.addWidget(meta)

        # Decision line
        decision_label = QLabel(self._decision_line(preview))
        decision_label.setProperty('class', 'FieldLabel')
        decision_label.setWordWrap(True)
        layout.addWidget(decision_label)

        has_selectable = any(
            diff.kind in ('conflict', 'fill') for diff in preview.diffs
        )
        interactive = has_selectable and preview.button_enabled

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACING['lg'])
        grid.setVerticalSpacing(SPACING['md'])
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Header
        hdr_paper = QLabel('Current (Zotero)')
        hdr_paper.setProperty('class', 'FieldLabel')
        grid.addWidget(hdr_paper, 0, 1)
        hdr_biblio = QLabel('Extracted (Biblio)')
        hdr_biblio.setProperty('class', 'FieldLabel')
        grid.addWidget(hdr_biblio, 0, 2)

        for row, diff in enumerate(preview.diffs, start=1):
            grid.addWidget(
                _field_label(diff.label), row, 0, Qt.AlignmentFlag.AlignTop,
            )

            if diff.kind == 'match':
                val = QLabel(diff.paper_value or '—')
                val.setWordWrap(True)
                val.setProperty('class', 'FieldValue')
                grid.addWidget(val, row, 1, 1, 2)
            elif interactive:
                group = QButtonGroup(frame)
                self._field_groups[diff.field_key] = group

                paper_cell = self._build_radio_cell(
                    diff.field_key, diff.paper_value, group,
                    radio_id=0, editable=False,
                    css_class='FieldValueStub' if diff.kind == 'fill' else 'FieldValue',
                )
                biblio_cell = self._build_radio_cell(
                    diff.field_key, diff.biblio_value, group,
                    radio_id=1, editable=True,
                    css_class='ConflictValue' if diff.kind == 'conflict' else 'FillValue',
                )
                # Default: keep paper for conflicts, take biblio for fills
                if diff.kind == 'fill':
                    group.button(1).setChecked(True)
                else:
                    group.button(0).setChecked(True)

                grid.addWidget(paper_cell, row, 1)
                grid.addWidget(biblio_cell, row, 2)
            else:
                # Read-only diff (already applied / skip).
                # Dim the side that was NOT used in the final result.
                applied = preview.biblio_status in ('applied', 'auto_committed')
                # If applied and paper now matches biblio, biblio was adopted → dim paper side
                if applied and diff.paper_value == diff.biblio_value:
                    # After apply both sides are identical (biblio was adopted);
                    # dim paper side to show biblio was the source
                    paper_dim, biblio_dim = True, False
                elif applied:
                    # Values still differ → paper value was kept, biblio unused
                    paper_dim, biblio_dim = False, True
                else:
                    paper_dim, biblio_dim = False, False

                dim_style = 'color: #555;'

                paper_lbl = QLabel(diff.paper_value or '(empty)')
                paper_lbl.setWordWrap(True)
                paper_lbl.setProperty(
                    'class',
                    'FieldValueStub' if diff.kind == 'fill' else 'FieldValue',
                )
                if paper_dim:
                    paper_lbl.setStyleSheet(dim_style)

                biblio_lbl = QLabel(diff.biblio_value or '(empty)')
                biblio_lbl.setWordWrap(True)
                biblio_lbl.setProperty(
                    'class',
                    'ConflictValue' if diff.kind == 'conflict' else 'FillValue',
                )
                if biblio_dim:
                    biblio_lbl.setStyleSheet(dim_style)

                grid.addWidget(paper_lbl, row, 1)
                grid.addWidget(biblio_lbl, row, 2)

        layout.addLayout(grid)

        # Apply button
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

    def _build_radio_cell(
        self,
        field_key: str,
        value: str,
        group: QButtonGroup,
        *,
        radio_id: int,
        editable: bool,
        css_class: str,
    ) -> QWidget:
        """Build one cell: [RadioButton] [value widget] [× clear button].

        Paper side (radio_id=0): read-only QLabel.
        Biblio side (radio_id=1): editable QLineEdit / QPlainTextEdit + × button.
        """
        cell = QWidget()
        _TEXTAREA_FIELDS = {'title', 'authors', 'journal'}
        use_textarea = field_key in _TEXTAREA_FIELDS

        if use_textarea:
            # Vertical: radio + × on top, text area below
            outer = QVBoxLayout(cell)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(SPACING['xs'])

            radio_row = QHBoxLayout()
            radio_row.setContentsMargins(0, 0, 0, 0)
            radio = QRadioButton()
            group.addButton(radio, radio_id)
            radio_row.addWidget(radio)
            radio_row.addStretch(1)

            if editable:
                clear_btn = self._make_clear_button()
                radio_row.addWidget(clear_btn)

            outer.addLayout(radio_row)

            if editable:
                edit = QPlainTextEdit()
                edit.setPlainText(value)
                line_count = max(value.count('\n') + 1, 2)
                edit.setFixedHeight(line_count * 20 + 12)
                edit.setProperty('class', css_class)
                self._field_edits[field_key] = edit
                clear_btn.clicked.connect(lambda: edit.setPlainText(''))
                outer.addWidget(edit)
            else:
                lbl = QLabel(value or '(empty)')
                lbl.setWordWrap(True)
                lbl.setProperty('class', css_class)
                outer.addWidget(lbl)
        else:
            # Single row: [radio] [value] [×]
            row_lay = QHBoxLayout(cell)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(SPACING['xs'])

            radio = QRadioButton()
            group.addButton(radio, radio_id)
            row_lay.addWidget(radio)

            if editable:
                edit = QLineEdit(value)
                edit.setProperty('class', css_class)
                self._field_edits[field_key] = edit
                row_lay.addWidget(edit, 1)
                clear_btn = self._make_clear_button()
                clear_btn.clicked.connect(lambda: edit.clear())
                row_lay.addWidget(clear_btn)
            else:
                lbl = QLabel(value or '(empty)')
                lbl.setWordWrap(True)
                lbl.setProperty('class', css_class)
                lbl.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
                )
                row_lay.addWidget(lbl, 1)

        return cell

    @staticmethod
    def _make_clear_button() -> QPushButton:
        btn = QPushButton('×')
        btn.setFixedSize(20, 20)
        btn.setProperty('class', 'ClearBtn')
        btn.setToolTip('Clear')
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _decision_line(self, preview) -> str:
        if preview.decision_action == 'auto_commit':
            return 'Decision: auto-commit (all P08 gates passed)'
        if preview.decision_action == 'needs_review':
            return f'Decision: needs review — {preview.decision_reason}'
        return f'Decision: skip — {preview.decision_reason}'

    def _collect_values(self) -> dict[str, str | None]:
        """Collect per-field values from radio + edit widgets.

        Returns {field_key: new_value} for biblio-selected fields,
        or {field_key: None} for paper-selected fields (keep current).
        """
        result: dict[str, str | None] = {}
        for field_key, group in self._field_groups.items():
            if group.checkedId() == 1:  # biblio selected
                edit = self._field_edits.get(field_key)
                if edit is None:
                    result[field_key] = None
                elif isinstance(edit, QPlainTextEdit):
                    result[field_key] = edit.toPlainText()
                else:
                    result[field_key] = edit.text()
            else:
                result[field_key] = None  # keep paper value
        return result

    def _on_apply_clicked(self):
        if self._current_paper_id is None or self._apply_btn is None:
            return
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText('Applying…')

        if self._field_groups and self._biblio_id is not None:
            values = self._collect_values()
            task = BackgroundTask(
                biblio_service.apply_merged,
                self._current_paper_id,
                self._biblio_id,
                values,
            )
        else:
            task = BackgroundTask(
                biblio_service.apply_paper, self._current_paper_id,
            )
        task.done.connect(self._on_apply_done)
        task.failed.connect(self._on_apply_failed)
        self._apply_task = task
        task.start()

    def _on_apply_done(self, result):
        pid = self._current_paper_id
        if isinstance(result, tuple) and len(result) == 3:
            _, changed, _ = result
        else:
            changed = result[0] if isinstance(result, tuple) else False

        if self._apply_btn is not None:
            self._apply_btn.setText('Applied' if changed else 'No change')
            self._apply_btn.setEnabled(False)
        if pid is not None:
            action = 'applied' if changed else 'noop'
            self.apply_completed.emit(pid, changed, action)
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
