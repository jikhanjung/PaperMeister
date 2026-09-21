"""The Text tab's figure list — P16 Phase 1.

What assembly stored for a paper, one line per figure, so a person can check it
against the page: is this a figure, is the plate one figure, did the pieces of a
cut-up figure end up together. Selecting a line jumps the reader to that page.

A caption found by assembly is only a hint until the linking stage has run, and
the list says so — otherwise the review this list exists for would take a
rule's guess for the printed caption.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from desktop.theme.tokens import FONT, SPACING

#: Tall enough for about six lines; the reader below keeps the rest of the tab.
_MAX_LIST_HEIGHT = 150


def describe(row) -> str:
    """One line for a figure: name, page, how it was assembled, caption state."""
    parts = [row.name or 'Unnamed figure', f'p. {row.page + 1}']
    if row.assembly == 'plate_page_union':
        parts.append(f'plate, {row.pieces} photos')
    elif row.assembly == 'caption_group_union':
        parts.append(f'{row.pieces} pieces')
    if getattr(row, 'plate_inferred', False):
        parts.append('plate number inferred')
    if row.caption:
        parts.append('caption')
    elif row.caption_hint:
        parts.append('caption hint')
    else:
        parts.append('no caption found')
    parts.extend(_panel_parts(row))
    return '  ·  '.join(parts)


def _panel_parts(row) -> list[str]:
    """What ② and ③ left on the row: entries, panels, and the two things a
    reviewer looks for first — an entry no panel claims, a split that failed."""
    state = getattr(row, 'panel_state', '')
    entries = getattr(row, 'entries', 0)
    panels = getattr(row, 'panels', 0)
    unmatched = getattr(row, 'unmatched', 0)
    if state == 'split':
        parts = [f'{panels} panels / {entries} entries']
        if unmatched:
            parts.append(f'{unmatched} unmatched')
        return parts
    if state == 'single':
        return ['single image' + (f', {entries} entries' if entries else '')]
    if state == 'failed':
        return ['panels failed' + (f', {entries} entries' if entries else '')]
    if entries:
        return [f'{entries} entries']
    return []


def tooltip(row) -> str:
    if row.caption:
        note = _panel_note(row)
        return f'{row.caption}\n\n{note}' if note else row.caption
    if row.caption_hint:
        return f'Caption hint (not yet linked):\n{row.caption_hint}'
    return 'No caption block under this figure. The linking stage may find one elsewhere.'


def _panel_note(row) -> str:
    state = getattr(row, 'panel_state', '')
    if state == 'split':
        note = f'{row.panels} panels matched to {row.entries} caption entries.'
        if row.unmatched:
            note += f' {row.unmatched} entries have no panel — check the plate.'
        return note
    if state == 'single':
        return 'One image, not split into panels.'
    if state == 'failed':
        return 'Panel split failed — the reply did not pass the checks.'
    if getattr(row, 'entries', 0):
        return f'{row.entries} caption entries; panels not split yet.'
    return ''


class FigureList(QFrame):
    """A paper's assembled figures. Emits the 0-based page of the chosen one."""

    page_requested = pyqtSignal(int)
    figure_chosen = pyqtSignal(int)      # the row's Figure id, as the selection moves
    boxes_toggled = pyqtSignal(bool)     # draw the panel boxes over the reader's figures

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setObjectName('FigureList')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], SPACING['sm'], SPACING['lg'], SPACING['sm'])
        layout.setSpacing(SPACING['xs'])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        header = QLabel(f'Figures ({len(rows)})')
        header.setStyleSheet(f"font-weight: {FONT['weight.bold']};")
        head.addWidget(header)
        head.addStretch()
        # Only offered when the split stage has drawn something to show.
        self.boxes = QCheckBox('Panel boxes')
        self.boxes.setChecked(True)
        self.boxes.setToolTip('Draw the split stage\'s panel boxes over the figures in the reader')
        self.boxes.setVisible(any(getattr(r, 'panels', 0) for r in rows))
        self.boxes.toggled.connect(self.boxes_toggled)
        head.addWidget(self.boxes)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setObjectName('FigureListItems')
        for row in rows:
            item = QListWidgetItem(describe(row))
            item.setData(Qt.ItemDataRole.UserRole, row.page)
            item.setData(Qt.ItemDataRole.UserRole + 1, row.id)
            item.setToolTip(tooltip(row))
            self.list.addItem(item)
        self.list.setMaximumHeight(_MAX_LIST_HEIGHT)
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        self.list.currentItemChanged.connect(self._current_changed)
        layout.addWidget(self.list)

    def _chosen(self, item: QListWidgetItem):
        self.page_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _current_changed(self, current, _previous=None):
        if current is not None:
            self.figure_chosen.emit(int(current.data(Qt.ItemDataRole.UserRole + 1)))
