"""Left navigation panel.

Structure (v4):
- Top: QTabWidget with one tab per Source ("My Library" for Zotero).
- Inside each tab: two vertically stacked sections:
    1) Collections tree (scrollable, takes remaining space)
    2) STATUS panel — collapsible header + flat list of library filters
       (All / Pending / Processed / etc.).  Always visible at the bottom;
       clicking the header toggles the list.

Selection emits `selection_changed(kind, id_or_key)` with kind one of:
    'library' — library filter key (str)
    'source'  — source id (int)
    'folder'  — folder id (int)
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QLabel,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.services import library as library_svc
from desktop.services import source_service
from desktop.theme.tokens import COLORS_DARK


class _StatusPanel(QWidget):
    """Collapsible STATUS section pinned to the bottom of the nav.

    Click the header to toggle the list.  Collapsed state shows only the
    one-line header; expanded shows header + tree of filter items.
    """

    item_clicked = pyqtSignal(str, object)  # kind, value — forwarded to SourceNav

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel('  \u25bc  STATUS')
        self._header.setFixedHeight(24)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(
            f'QLabel {{'
            f'  color: {COLORS_DARK["text.muted"]};'
            f'  font-size: 11px;'
            f'  font-weight: 500;'
            f'  background: {COLORS_DARK["bg.panel"]};'
            f'  border-top: 1px solid {COLORS_DARK["border.subtle"]};'
            f'  padding-left: 4px;'
            f'}}'
        )
        self._header.mousePressEvent = self._toggle
        layout.addWidget(self._header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(0)
        self._tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self._tree.setAnimated(False)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

        self._expanded = True

    def populate(self):
        self._tree.clear()
        try:
            folders = library_svc.load_library_folders()
        except Exception:
            folders = []
        for folder in folders:
            item = QTreeWidgetItem([f'  {folder.title}    {folder.count:,}'])
            item.setData(0, Qt.ItemDataRole.UserRole, ('library', folder.key))
            self._tree.addTopLevelItem(item)

    def _toggle(self, _event=None):
        self._expanded = not self._expanded
        self._tree.setVisible(self._expanded)
        arrow = '\u25bc' if self._expanded else '\u25b6'
        self._header.setText(f'  {arrow}  STATUS')

    def _on_item_clicked(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.item_clicked.emit(*data)


class SourceNav(QWidget):
    selection_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SourceNav')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('SourceTabs')
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        # STATUS panel — always visible, pinned below the tab content.
        self._status_panel = _StatusPanel()
        self._status_panel.item_clicked.connect(
            lambda kind, val: self.selection_changed.emit(kind, val)
        )
        layout.addWidget(self._status_panel, 0)

        # Map (tab index -> QTreeWidget) for reveal_folder lookups.
        self._trees: dict[int, QTreeWidget] = {}

        self.refresh()

    # ── Build ────────────────────────────────────────────────

    def _new_tree(self) -> QTreeWidget:
        t = QTreeWidget()
        t.setHeaderHidden(True)
        t.setRootIsDecorated(True)
        t.setIndentation(14)
        t.setAnimated(False)
        t.setFrameShape(QTreeWidget.Shape.NoFrame)
        t.itemClicked.connect(self._on_item_clicked)
        return t

    # ── Refresh ──────────────────────────────────────────────

    def refresh(self):
        """Rebuild all tabs from scratch. Cheap — runs on startup and on
        `apply_completed` (counts may have shifted)."""
        self.tabs.blockSignals(True)
        self.tabs.clear()
        self._trees.clear()

        sources = []
        try:
            sources = source_service.load_source_tree()
        except Exception:
            sources = []

        if not sources:
            tree = self._new_tree()
            idx = self.tabs.addTab(tree, 'Library')
            self._trees[idx] = tree
            self.tabs.blockSignals(False)
            self._status_panel.populate()
            return

        for src in sources:
            tree = self._new_tree()
            self._populate_collections(tree, src)
            tab_label = 'My Library' if src.source_type == 'zotero' else src.name
            idx = self.tabs.addTab(tree, tab_label)
            self._trees[idx] = tree

        self.tabs.blockSignals(False)
        self._status_panel.populate()

    def _populate_collections(self, tree: QTreeWidget, src):
        """Source root + hierarchical collections."""
        root_label = 'My Library' if src.source_type == 'zotero' else src.name
        src_item = QTreeWidgetItem([root_label])
        src_item.setData(0, Qt.ItemDataRole.UserRole, ('source', src.id))
        tree.addTopLevelItem(src_item)

        for folder in src.roots:
            self._attach_folder(src_item, folder)
        src_item.setExpanded(True)

    def _attach_folder(self, parent: QTreeWidgetItem, folder):
        item = QTreeWidgetItem([folder.name])
        item.setData(0, Qt.ItemDataRole.UserRole, ('folder', folder.id))
        parent.addChild(item)
        for child in folder.children:
            self._attach_folder(item, child)

    # ── Reveal ───────────────────────────────────────────────

    def reveal_folder(self, folder_id: int):
        """Highlight a folder in the tree without emitting selection_changed.

        Switches to the correct tab, expands ancestor nodes, scrolls to the
        item and selects it visually — like Zotero's "Show in Library".
        The paper list stays untouched because we don't fire selection_changed.
        """
        for tab_idx, tree in self._trees.items():
            item = self._find_folder_item(tree.invisibleRootItem(), folder_id)
            if item is not None:
                self.tabs.setCurrentIndex(tab_idx)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                tree.scrollToItem(item)
                tree.blockSignals(True)
                tree.setCurrentItem(item)
                tree.blockSignals(False)
                return

    def _find_folder_item(self, root: QTreeWidgetItem, folder_id: int):
        """Recursive DFS to find the tree item for a given folder_id."""
        for i in range(root.childCount()):
            child = root.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data == ('folder', folder_id):
                return child
            found = self._find_folder_item(child, folder_id)
            if found is not None:
                return found
        return None

    # ── Events ───────────────────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, value = data
        self.selection_changed.emit(kind, value)
