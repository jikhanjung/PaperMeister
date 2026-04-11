"""Left navigation panel: Library operational view + Sources provenance tree."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.services import library as library_svc
from desktop.services import source_service


# Qt UserRole payloads so selection emits a structured event.
#   ('library', key)       — Library folder
#   ('source', source_id)  — whole source root
#   ('folder', folder_id)  — source folder


class SourceNav(QWidget):
    """Two stacked trees: Library then Sources.

    Emits `selection_changed(kind, id_or_key)` on click.
    """

    selection_changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SourceNav')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._header('LIBRARY'))
        self.library_tree = self._new_tree()
        layout.addWidget(self.library_tree)

        layout.addWidget(self._header('SOURCES'))
        self.sources_tree = self._new_tree()
        layout.addWidget(self.sources_tree, 1)

        self.library_tree.itemClicked.connect(self._on_library_clicked)
        self.sources_tree.itemClicked.connect(self._on_source_clicked)

        self.refresh()

    # ── Building ─────────────────────────────────────────────

    def _header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty('class', 'SectionHeader')
        # QSS uses object name or dynamic class property; fall back to class
        lbl.setObjectName('SectionHeaderLabel')
        lbl.setStyleSheet('')  # let global QSS handle via property selector
        from desktop.theme.tokens import FONT, SPACING
        lbl.setContentsMargins(SPACING['md'], SPACING['md'], SPACING['md'], SPACING['xs'])
        f = lbl.font()
        f.setPointSize(FONT['size.xs'])
        f.setWeight(500)
        lbl.setFont(f)
        return lbl

    def _new_tree(self) -> QTreeWidget:
        t = QTreeWidget()
        t.setHeaderHidden(True)
        t.setRootIsDecorated(True)
        t.setIndentation(14)
        t.setAnimated(False)
        t.setFrameShape(QTreeWidget.Shape.NoFrame)
        return t

    # ── Refresh ──────────────────────────────────────────────

    def refresh(self):
        self._rebuild_library()
        self._rebuild_sources()

    def _rebuild_library(self):
        self.library_tree.clear()
        try:
            folders = library_svc.load_library_folders()
        except Exception:
            folders = []
        for folder in folders:
            item = QTreeWidgetItem([f'{folder.title}    {folder.count:,}'])
            item.setData(0, Qt.ItemDataRole.UserRole, ('library', folder.key))
            self.library_tree.addTopLevelItem(item)

    def _rebuild_sources(self):
        self.sources_tree.clear()
        try:
            tree = source_service.load_source_tree()
        except Exception:
            tree = []
        if not tree:
            empty = QTreeWidgetItem(['No sources yet'])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.sources_tree.addTopLevelItem(empty)
            return

        # Group: Zotero first, then Local.
        zotero_root = QTreeWidgetItem(['Zotero'])
        zotero_root.setFlags(Qt.ItemFlag.ItemIsEnabled)
        local_root = QTreeWidgetItem(['Local'])
        local_root.setFlags(Qt.ItemFlag.ItemIsEnabled)

        has_z = False
        has_l = False
        for src in tree:
            src_item = QTreeWidgetItem([src.name])
            src_item.setData(0, Qt.ItemDataRole.UserRole, ('source', src.id))
            for folder in src.roots:
                self._attach_folder(src_item, folder)
            if src.source_type == 'zotero':
                zotero_root.addChild(src_item)
                has_z = True
            else:
                local_root.addChild(src_item)
                has_l = True

        if has_z:
            self.sources_tree.addTopLevelItem(zotero_root)
            zotero_root.setExpanded(True)
        if has_l:
            self.sources_tree.addTopLevelItem(local_root)
            local_root.setExpanded(True)

    def _attach_folder(self, parent: QTreeWidgetItem, folder):
        item = QTreeWidgetItem([folder.name])
        item.setData(0, Qt.ItemDataRole.UserRole, ('folder', folder.id))
        parent.addChild(item)
        for child in folder.children:
            self._attach_folder(item, child)

    # ── Events ───────────────────────────────────────────────

    def _on_library_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        self.sources_tree.clearSelection()
        kind, value = data
        self.selection_changed.emit(kind, value)

    def _on_source_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        self.library_tree.clearSelection()
        kind, value = data
        self.selection_changed.emit(kind, value)
