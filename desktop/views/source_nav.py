"""Left navigation panel.

Structure (v2):
- Top: QTabWidget with one tab per Source. Currently only Zotero exists,
  so there is a single "Zotero" tab.
- Inside each tab: a single QTreeWidget that combines
    1) flat library filters (All / Pending / Processed / Failed /
       Needs Review / Recent) at the top, and
    2) hierarchical folders (Zotero collections) below, under a
       "Collections" separator node.

Selection emits `selection_changed(kind, id_or_key)` with kind one of:
    'library' — library filter key (str)
    'source'  — source id (int)
    'folder'  — folder id (int)
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.services import library as library_svc
from desktop.services import source_service
from desktop.theme.tokens import COLORS_DARK


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

        # Map (tab index -> QTreeWidget) so we can rebuild individual tabs.
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
            # Fall back to a single empty tab so the panel isn't blank.
            tree = self._new_tree()
            self._populate_library_section(tree)
            idx = self.tabs.addTab(tree, 'Library')
            self._trees[idx] = tree
            self.tabs.blockSignals(False)
            return

        for src in sources:
            tree = self._new_tree()
            self._populate_library_section(tree)
            self._populate_collections_section(tree, src)
            idx = self.tabs.addTab(tree, src.name)
            self._trees[idx] = tree

        self.tabs.blockSignals(False)

    def _populate_library_section(self, tree: QTreeWidget):
        """Flat library filters at the top of the tree."""
        try:
            folders = library_svc.load_library_folders()
        except Exception:
            folders = []
        for folder in folders:
            item = QTreeWidgetItem([f'{folder.title}    {folder.count:,}'])
            item.setData(0, Qt.ItemDataRole.UserRole, ('library', folder.key))
            tree.addTopLevelItem(item)

    def _populate_collections_section(self, tree: QTreeWidget, src):
        """Hierarchical folder (collection) tree below the library filters."""
        # Separator / section header — non-clickable.
        header = QTreeWidgetItem(['COLLECTIONS'])
        header.setFlags(Qt.ItemFlag.ItemIsEnabled)
        f = QFont(header.font(0))
        f.setPointSize(max(f.pointSize() - 1, 8))
        f.setWeight(QFont.Weight.Medium)
        header.setFont(0, f)
        header.setForeground(0, Qt.GlobalColor.gray)
        tree.addTopLevelItem(header)

        # Source root — clicking loads the whole source.
        src_item = QTreeWidgetItem([src.name])
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

    # ── Events ───────────────────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, value = data
        self.selection_changed.emit(kind, value)
