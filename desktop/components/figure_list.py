"""The Text tab's figure list — P16 Phase 1.

What assembly stored for a paper, one line per figure, so a person can check it
against the page: is this a figure, is the plate one figure, did the pieces of a
cut-up figure end up together. Selecting a line jumps the reader to that page.

A caption found by assembly is only a hint until the linking stage has run, and
the list says so — otherwise the review this list exists for would take a
rule's guess for the printed caption.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

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
    return '  ·  '.join(parts)


def tooltip(row) -> str:
    if row.caption:
        return row.caption
    if row.caption_hint:
        return f'Caption hint (not yet linked):\n{row.caption_hint}'
    return 'No caption block under this figure. The linking stage may find one elsewhere.'


class FigureList(QFrame):
    """A paper's assembled figures. Emits the 0-based page of the chosen one."""

    page_requested = pyqtSignal(int)

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setObjectName('FigureList')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING['lg'], SPACING['sm'], SPACING['lg'], SPACING['sm'])
        layout.setSpacing(SPACING['xs'])

        header = QLabel(f'Figures ({len(rows)})')
        header.setStyleSheet(f"font-weight: {FONT['weight.bold']};")
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.setObjectName('FigureListItems')
        for row in rows:
            item = QListWidgetItem(describe(row))
            item.setData(Qt.ItemDataRole.UserRole, row.page)
            item.setToolTip(tooltip(row))
            self.list.addItem(item)
        self.list.setMaximumHeight(_MAX_LIST_HEIGHT)
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        layout.addWidget(self.list)

    def _chosen(self, item: QListWidgetItem):
        self.page_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))
