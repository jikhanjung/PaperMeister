"""Center paper list — flat table with status badges."""
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QHeaderView,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from desktop.services import paper_service
from desktop.theme.tokens import FONT, RADIUS

COLUMNS = ['Status', 'Authors', 'Year', 'Title']
#: Column indexes, so a column added in the middle does not silently shift
#: every literal below.
COL_STATUS, COL_AUTHORS, COL_YEAR, COL_TITLE = range(4)
#: Item data roles on column 0.
ROLE_PAPER_ID = Qt.ItemDataRole.UserRole
ROLE_FOLDER_ID = Qt.ItemDataRole.UserRole + 1
ROLE_FILE_ID = Qt.ItemDataRole.UserRole + 2
ROLE_STANDALONE = Qt.ItemDataRole.UserRole + 3
ROLE_STAGES = Qt.ItemDataRole.UserRole + 4      # a paper_service.Stages
ROLE_FILE_STATUS = Qt.ItemDataRole.UserRole + 5  # PaperFile.status, for the OCR actions


#: The pipeline after the PDF: OCR → info (bibliography) → references → figures.
#: The Status cell shows one badge — the first stage not finished — in its
#: state's colour: what the paper is waiting on, or what to run next.
_STAGE_BADGES = (
    ('ocr', 'OCR'), ('biblio', 'INFO'), ('refs', 'REF'), ('figs', 'FIG'),
)
_STAGE_FINISHED = {'done', 'split'}
#: Per state: colour and the word after the stage label ('' = nothing).
_STAGE_LOOK: dict[str, tuple[QColor, str]] = {
    'done':      (QColor(74, 222, 128), ''),        # green: finished
    'split':     (QColor(74, 222, 128), ''),
    'linked':    (QColor(96, 165, 250), 'cap'),     # blue: well along
    'assembled': (QColor(96, 165, 250), 'asm'),
    'extracted': (QColor(96, 165, 250), 'ext'),
    'review':    (QColor(251, 191, 36), 'rev'),     # amber: a person's turn
    'partial':   (QColor(251, 191, 36), 'part'),
    'pending':   (QColor(160, 165, 180), 'wait'),   # grey: waiting
    'failed':    (QColor(248, 113, 113), 'err'),    # red
    'none':      (QColor(120, 125, 140), ''),       # muted: to run next
}
_ALL_DONE = QColor(74, 222, 128)


def current_stage(stages) -> tuple[str, str] | None:
    """(stage key, state) of the first stage not finished, or None when
    every stage is."""
    if stages is None:
        return None
    for key, _label in _STAGE_BADGES:
        state = stages.state(key)
        if state not in _STAGE_FINISHED:
            return key, state
    return None


def badge_text(stages) -> str:
    """What the Status cell says: 'INFO rev', 'REF', 'OCR err', or 'done'."""
    cur = current_stage(stages)
    if cur is None:
        return 'done' if stages is not None else '—'
    key, state = cur
    label = dict(_STAGE_BADGES)[key]
    word = _STAGE_LOOK.get(state, _STAGE_LOOK['none'])[1]
    return f'{label} {word}' if word else label




#: How far along each state is, for sorting the Stages column.
_STAGE_RANK = {'none': 0, 'pending': 1, 'failed': 1, 'partial': 2, 'assembled': 2, 'extracted': 2,
               'review': 3, 'linked': 3, 'done': 4, 'split': 4}


def _stages_sort_key(stages) -> str:
    """The cell's text: invisible (the delegate paints), but what a header
    click sorts by — furthest-along papers together."""
    if stages is None:
        return '0000'
    return ''.join(str(_STAGE_RANK.get(stages.state(k), 0)) for k, _ in _STAGE_BADGES)


def stages_tooltip_html(stages) -> str:
    """All four badges, each in its state's colour with what it produced —
    what hovering the one badge in the cell shows."""
    rows = []
    for key, label in _STAGE_BADGES:
        state = stages.state(key)
        colour = (_ALL_DONE if state in _STAGE_FINISHED else _STAGE_LOOK.get(state, _STAGE_LOOK['none'])[0]).name()
        mark = '✓' if state in _STAGE_FINISHED else ('✗' if state == 'failed' else '·')
        detail = stages.detail.get(key) or state
        rows.append(
            f'<tr><td style="padding:2px 8px 2px 0"><span style="color:{colour};font-weight:600">'
            f'{mark} {label}</span></td><td style="padding:2px 0">{detail}</td></tr>')
    return '<table>' + ''.join(rows) + '</table>'


def _set_stages(item, stages, file_status: str) -> None:
    item.setData(0, ROLE_STAGES, stages)
    item.setData(0, ROLE_FILE_STATUS, file_status)
    item.setToolTip(COL_STATUS, stages_tooltip_html(stages) if stages is not None else file_status)


class StagesDelegate(QStyledItemDelegate):
    """One badge — the stage the paper is on or must run next — coloured
    by that stage's state; 'done' when every stage is finished. The cell's
    tooltip walks all four stages."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        widget = opt.widget
        from PyQt6.QtWidgets import QApplication, QStyle
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        stages = index.data(ROLE_STAGES)
        if stages is None:
            # A row built without stages (a search hit, an old caller): the
            # file status word, muted.
            text, colour = (index.data(ROLE_FILE_STATUS) or '—'), _STAGE_LOOK['none'][0]
        else:
            cur = current_stage(stages)
            text = badge_text(stages)
            colour = _ALL_DONE if cur is None else _STAGE_LOOK.get(cur[1], _STAGE_LOOK['none'])[0]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(painter.font())
        font.setPointSize(FONT['size.xs'])
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        rect = option.rect
        w = metrics.horizontalAdvance(text) + 12
        h = metrics.height() + 4
        badge = QRectF(rect.x() + 6, rect.y() + (rect.height() - h) // 2, w, h)
        bg = QColor(colour)
        bg.setAlpha(40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(badge, RADIUS['sm'], RADIUS['sm'])
        painter.setPen(QPen(colour))
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(max(hint.width(), 72), max(hint.height(), 26))


class PaperListView(QTreeWidget):
    """Shows PaperRow list. `paper_selected` fires on selection changes.

    Ctrl+click on a row emits `folder_reveal_requested(folder_id)` so the
    left SourceNav can highlight the paper's collection (Zotero-style).
    """

    paper_selected = pyqtSignal(int)
    folder_reveal_requested = pyqtSignal(int)  # folder_id
    context_action = pyqtSignal(str, int, int)  # action, paper_id, file_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PaperList')
        self.setRootIsDecorated(False)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(COLUMNS)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setIndentation(0)

        # All columns user-resizable (Interactive); Title stretches to fill.
        header = self.header()
        for col in (COL_STATUS, COL_AUTHORS, COL_YEAR):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)      # Title (fills)
        header.setStretchLastSection(False)
        self.setColumnWidth(COL_STATUS, 78)    # one stage badge
        self.setColumnWidth(COL_AUTHORS, 140)  # Authors (citation style, compact)
        self.setColumnWidth(COL_YEAR, 68)      # Year

        self.setSortingEnabled(True)
        self.sortByColumn(COL_TITLE, Qt.SortOrder.AscendingOrder)  # default: Title A-Z

        self._stages_delegate = StagesDelegate(self)
        self.setItemDelegateForColumn(COL_STATUS, self._stages_delegate)

        self.currentItemChanged.connect(self._on_selection_changed)
        self.itemPressed.connect(self._on_item_pressed)

    # ── Loading ──────────────────────────────────────────────

    def load_library(self, key: str):
        try:
            rows = paper_service.list_by_library(key)
        except Exception as exc:
            rows = []
            self._show_error(f'Query failed: {exc}')
        self._populate(rows)

    def load_folder(self, folder_id: int):
        rows = paper_service.list_by_folder(folder_id)
        self._populate(rows)

    def load_source(self, source_id: int):
        rows = paper_service.list_by_source(source_id)
        self._populate(rows)

    def load_search(self, query: str):
        """Populate with FTS5 search results in BM25 rank order."""
        from desktop.services.search_service import search_papers
        try:
            rows = search_papers(query)
        except Exception as exc:
            self._show_error(f'Search failed: {exc}')
            return
        if not rows:
            self.clear()
            item = QTreeWidgetItem(['', '', '', f'No results for "{query}"'])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addTopLevelItem(item)
            return
        self._populate(rows)

    def update_status(self, paper_id: int, new_status: str):
        """Update the status pill for a single paper without reloading the list.

        Also re-evaluates the row's `is_standalone` flag from DB, since OCR
        completion may have triggered an auto-promote (Paper.zotero_key changes
        to the new parent key, so the row is no longer standalone).
        """
        from papermeister.models import Paper, PaperFile
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == paper_id:
                item.setText(0, new_status)
                paper = Paper.get_or_none(Paper.id == paper_id)
                if paper is not None and paper.zotero_key:
                    pfile = (
                        PaperFile.select(PaperFile.zotero_key)
                        .where(
                            (PaperFile.paper == paper)
                            & (~PaperFile.path.endswith('.json'))
                        )
                        .first()
                    )
                    is_standalone = bool(
                        pfile and pfile.zotero_key == paper.zotero_key
                    )
                else:
                    is_standalone = False
                item.setData(0, Qt.ItemDataRole.UserRole + 3, is_standalone)
                break

    def select_paper(self, paper_id: int) -> bool:
        """Select the row for paper_id if it's in the current view (scrolling to
        it + firing the normal selection → detail flow). Returns False if the
        paper isn't currently listed."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == paper_id:
                self.setCurrentItem(item)
                self.scrollToItem(item)
                return True
        return False

    def refresh_row(self, paper_id: int):
        """Re-fetch a single paper's row and update all columns in place
        (status / authors / year / title), e.g. after a biblio apply changed
        the metadata. Falls back silently if the row isn't currently shown."""
        row = paper_service.row_for_paper(paper_id)
        if row is None:
            return
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == paper_id:
                item.setText(COL_STATUS, _stages_sort_key(row.stages))
                _set_stages(item, row.stages, row.status)
                item.setText(COL_AUTHORS, row.authors or '—')
                item.setText(COL_YEAR, str(row.year) if row.year is not None else '—')
                item.setText(COL_TITLE, row.title)
                if row.file_id is not None:
                    item.setData(0, Qt.ItemDataRole.UserRole + 2, row.file_id)
                item.setData(0, Qt.ItemDataRole.UserRole + 3, row.is_standalone)
                font = item.font(COL_TITLE)
                font.setItalic(bool(row.is_stub))
                item.setFont(COL_TITLE, font)
                break

    def visible_paper_ids(self) -> list[int]:
        """Paper ids in current top-to-bottom display order (reflects any
        header-click sort the user applied)."""
        ids: list[int] = []
        for i in range(self.topLevelItemCount()):
            pid = self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            if isinstance(pid, int):
                ids.append(pid)
        return ids

    def clear_rows(self):
        self.clear()

    def _populate(self, rows):
        self.clear()
        for row in rows:
            year = str(row.year) if row.year is not None else '—'
            # Stub papers are conveyed via italic; no text prefix (it looked like
            # an empty-field placeholder next to real em-dash blanks).
            title = row.title
            item = QTreeWidgetItem([
                _stages_sort_key(row.stages),       # painted by the delegate; sorted by progress
                row.authors or '—',
                year,
                title,
            ])
            item.setData(0, ROLE_PAPER_ID, row.paper_id)
            if row.folder_id is not None:
                item.setData(0, ROLE_FOLDER_ID, row.folder_id)
            if row.file_id is not None:
                item.setData(0, ROLE_FILE_ID, row.file_id)
            item.setData(0, ROLE_STANDALONE, row.is_standalone)
            _set_stages(item, row.stages, row.status)
            if row.is_stub:
                font = item.font(COL_TITLE)
                font.setItalic(True)
                item.setFont(COL_TITLE, font)
            # Search results carry the matching passage — show it on hover.
            snippet = getattr(row, 'snippet', '')
            if snippet:
                for col in range(len(COLUMNS)):
                    item.setToolTip(col, snippet)
            self.addTopLevelItem(item)

    def _show_error(self, msg: str):
        item = QTreeWidgetItem(['', '', '', msg])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.clear()
        self.addTopLevelItem(item)

    # ── Events ───────────────────────────────────────────────

    def _on_item_pressed(self, item, _col):
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            folder_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if isinstance(folder_id, int):
                self.folder_reveal_requested.emit(folder_id)

    def contextMenuEvent(self, event):
        """The menu follows the paper's place in the pipeline.

        Each stage offers what moves it on — or nothing, when it is done and
        the next stage is the one to run. OCR first: everything after it
        reads the OCR'd text, so a pending or failed PDF only offers OCR.
        """
        item = self.itemAt(event.pos())
        if item is None:
            return
        paper_id = item.data(0, ROLE_PAPER_ID)
        file_id = item.data(0, ROLE_FILE_ID)
        is_standalone = bool(item.data(0, ROLE_STANDALONE))
        status = item.data(0, ROLE_FILE_STATUS) or item.text(COL_STATUS)  # pending/processed/failed/…
        stages = item.data(0, ROLE_STAGES)
        ocr = stages.ocr if stages else {'processed': 'done', 'review': 'done', 'done': 'done'}.get(status, status)
        biblio = stages.biblio if stages else {'review': 'review', 'done': 'done'}.get(status, 'none')
        refs = stages.refs if stages else 'none'
        figs = stages.figs if stages else 'none'

        from papermeister.preferences import get_pref
        manual_biblio_enabled = bool(get_pref('manual_biblio_extract', True))

        def emit(action):
            return lambda: self.context_action.emit(action, paper_id, file_id or 0)

        menu = QMenu(self)

        # ── 1. OCR ──
        if ocr == 'pending':
            menu.addAction('Process OCR', emit('process'))
        elif ocr == 'failed':
            menu.addAction('Retry OCR', emit('retry'))
        elif ocr == 'done' and is_standalone and file_id:
            # Re-run from the cache: the auto-promote hook creates the parent item.
            menu.addAction('Process OCR (re-run + create parent item)', emit('process'))
        if ocr != 'done':
            self._add_common(menu, emit)
            if not menu.isEmpty():
                menu.exec(event.globalPos())
            return

        # ── 2. Info (bibliography) ──
        if biblio == 'none':
            act = menu.addAction('Extract Info', emit('extract_biblio'))
            if not manual_biblio_enabled:
                act.setEnabled(False)
                act.setToolTip('Disabled: turn on "Enable manual info extraction" in Preferences → Info')
        elif biblio in ('review', 'extracted'):
            menu.addAction('Review Info (Metadata tab)', emit('review_biblio'))
        else:
            menu.addAction('Re-extract Info', emit('extract_biblio')).setEnabled(manual_biblio_enabled)

        # ── 3. References ──
        if refs == 'none':
            menu.addAction('Extract References', emit('extract_references'))
        elif refs in ('partial', 'failed'):
            menu.addAction('Retry References', emit('extract_references'))
        else:
            menu.addAction('Re-extract References', emit('extract_references'))

        # ── 4. Figures (P16): assemble → re-judge → captions → panels on the
        # wrapper server; the pipeline skips what is done, so one action
        # serves every state and its label says what is next.
        if file_id:
            from papermeister.figure_pipeline import server_hint
            label = {'none': 'Process Figures (assemble → captions → panels)',
                     'assembled': 'Process Figures (captions → panels)',
                     'linked': 'Process Figures (panels)',
                     'split': 'Process Figures (re-check)'}[figs]
            fig_act = menu.addAction(label, emit('process_figures'))
            hint = server_hint()
            if hint:
                fig_act.setEnabled(False)
                fig_act.setToolTip(hint)

        menu.addSeparator()
        menu.addAction('Open PDF', emit('open_pdf'))
        self._add_common(menu, emit)

        if not menu.isEmpty():
            menu.exec(event.globalPos())

    @staticmethod
    def _add_common(menu: QMenu, emit) -> None:
        """What every paper offers, whatever its stage."""
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction('Show in citation network', emit('network'))

    def _on_selection_changed(self, current, _prev):
        if current is None:
            return
        paper_id = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(paper_id, int):
            self.paper_selected.emit(paper_id)
