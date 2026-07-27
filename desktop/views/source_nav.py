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
from PyQt6.QtWidgets import (
    QLabel,
    QMenu,
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
    folder_action = pyqtSignal(str, int)  # action, folder_id
    source_action = pyqtSignal(str, int)  # action, source_id (tab-level)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SourceNav')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('SourceTabs')
        self.tabs.setDocumentMode(True)
        # Right-click a tab → source-level actions (e.g. remove a local folder).
        bar = self.tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._on_tab_context_menu)
        layout.addWidget(self.tabs, 1)

        # STATUS panel — always visible, pinned below the tab content.
        self._status_panel = _StatusPanel()
        self._status_panel.item_clicked.connect(
            lambda kind, val: self.selection_changed.emit(kind, val)
        )
        layout.addWidget(self._status_panel, 0)

        # Map (tab index -> QTreeWidget) for reveal_folder lookups.
        self._trees: dict[int, QTreeWidget] = {}
        # Map (tab index -> (source_id, source_type)) for tab context menu.
        self._tab_sources: dict[int, tuple[int, str]] = {}

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
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(
            lambda pos, tree=t: self._on_tree_context_menu(tree, pos)
        )
        return t

    # ── Refresh ──────────────────────────────────────────────

    def refresh(self):
        """Rebuild all tabs from scratch. Cheap — runs on startup and on
        `apply_completed` (counts may have shifted).

        Keeps the user on the tab they were looking at. This matters most on
        startup: the Zotero sync finishes seconds later and refreshes, and
        without this the tab bar would snap back to the first tab under someone
        who had already navigated elsewhere.

        Matched on source identity rather than tab index, because the whole
        reason to rebuild is that the set of sources may have changed — a sync
        can add one, and a local folder can be removed. Restoring index 3 could
        land on a different source. If the source is gone, or the previous tab
        was the sourceless placeholder, the default first tab stands.
        """
        keep = self._tab_sources.get(self.tabs.currentIndex())

        self.tabs.blockSignals(True)
        self.tabs.clear()
        self._trees.clear()
        self._tab_sources.clear()

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
            self._tab_sources[idx] = (src.id, src.source_type)

        if keep is not None:
            for idx, key in self._tab_sources.items():
                if key == keep:
                    self.tabs.setCurrentIndex(idx)
                    break

        self.tabs.blockSignals(False)
        self._status_panel.populate()

    # ── Tab context menu ─────────────────────────────────────

    def _on_tab_context_menu(self, pos):
        """Right-click on a tab. Local-folder sources can be removed; the
        Zotero 'My Library' tab is managed by sync, so it offers nothing."""
        idx = self.tabs.tabBar().tabAt(pos)
        if idx < 0:
            return
        src = self._tab_sources.get(idx)
        if not src:
            return
        source_id, source_type = src
        if source_type != 'directory':
            return  # don't let users delete the Zotero library here
        label = self.tabs.tabText(idx)
        menu = QMenu(self)
        menu.addAction(
            'Re-scan folder (pick up new files)',
            lambda: self.source_action.emit('rescan_source', source_id),
        )
        menu.addSeparator()
        menu.addAction(
            f'Remove "{label}" (local folder)',
            lambda: self.source_action.emit('remove_source', source_id),
        )
        menu.exec(self.tabs.tabBar().mapToGlobal(pos))

    def _populate_collections(self, tree: QTreeWidget, src):
        """Source root + hierarchical collections.

        Zotero: a 'My Library' source node holding the collection tree.
        Directory: the import already creates a root Folder named after the
        imported directory, so adding a source node of the same name would show
        the folder name twice ("1990-" → "1990-" → subdirs). Use the root
        folder(s) directly as the top node instead, and select via the folder's
        PaperFolder membership (list_by_folder, M2M) so linked-from-Zotero PDFs
        show too — unlike list_by_source, which only sees the legacy 1:1 FK.
        """
        if src.source_type == 'directory':
            root = tree.invisibleRootItem()
            for folder in src.roots:
                self._attach_folder(root, folder)
            for i in range(tree.topLevelItemCount()):
                tree.topLevelItem(i).setExpanded(True)
            return

        src_item = QTreeWidgetItem(['My Library'])
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

    def _on_tree_context_menu(self, tree: QTreeWidget, pos):
        item = tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, value = data
        if kind not in ('folder', 'source'):
            return

        menu = QMenu(tree)
        if kind == 'source':
            # 'My Library' root → process the whole library (every remaining PDF
            # in any collection, plus uncollected).
            menu.addAction('Process All (OCR → Biblio)',
                            lambda: self.folder_action.emit('process_source', value))
            menu.addAction('Extract References (all)',
                            lambda: self.folder_action.emit('extract_references_source', value))
        else:
            menu.addAction('Process Folder (OCR → Biblio)',
                            lambda: self.folder_action.emit('process_folder', value))
            menu.addAction('Extract References (folder)',
                            lambda: self.folder_action.emit('extract_references_folder', value))
            # "Upload OCR JSON to Zotero" only makes sense for Zotero-backed
            # folders — local-directory PDFs have no Zotero attachment.
            if self._source_type_for_tree(tree) == 'zotero':
                menu.addAction('Upload OCR JSON to Zotero',
                                lambda: self.folder_action.emit('upload_ocr_json', value))
        menu.exec(tree.viewport().mapToGlobal(pos))

    def _source_type_for_tree(self, tree: QTreeWidget):
        """'zotero' | 'directory' | None for the source a tree belongs to."""
        for idx, t in self._trees.items():
            if t is tree:
                src = self._tab_sources.get(idx)
                return src[1] if src else None
        return None

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, value = data
        self.selection_changed.emit(kind, value)
