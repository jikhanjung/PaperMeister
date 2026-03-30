from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class CollectionLoader(QThread):
    """Load Zotero collections in background."""
    finished = pyqtSignal(list)  # list of collection dicts
    error = pyqtSignal(str)

    def __init__(self, user_id, api_key):
        super().__init__()
        self.user_id = user_id
        self.api_key = api_key

    def run(self):
        try:
            from ..zotero_client import ZoteroClient
            client = ZoteroClient(self.user_id, self.api_key)
            collections = client.get_collections()  # also saves cache
            self.finished.emit(collections)
        except Exception as e:
            self.error.emit(str(e))


class ZoteroImportDialog(QDialog):
    """Dialog to browse and select Zotero collections for import."""

    def __init__(self, user_id, api_key, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.api_key = api_key
        self.selected_collections = []
        self._collections = []
        self._loader = None
        self.setWindowTitle('Import from Zotero')
        self.setMinimumSize(500, 400)
        self._setup_ui()
        self._try_load_from_cache()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Top bar: status + refresh
        top_layout = QHBoxLayout()
        self.status_label = QLabel('Loading collections...')
        self.status_label.setStyleSheet('font-style: italic; color: gray;')
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()
        self.refresh_btn = QPushButton('Refresh')
        self.refresh_btn.clicked.connect(self._refresh_from_api)
        top_layout.addWidget(self.refresh_btn)
        layout.addLayout(top_layout)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel('Collections')
        layout.addWidget(self.tree)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.import_btn = QPushButton('Import Selected')
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _try_load_from_cache(self):
        from ..zotero_client import load_cached_collections
        cached = load_cached_collections()
        if cached:
            self._on_collections_loaded(cached)
            self.status_label.setText('Loaded from cache')
        else:
            self._refresh_from_api()

    def _refresh_from_api(self):
        if self._loader and self._loader.isRunning():
            return
        self.status_label.setText('Fetching from Zotero...')
        self.status_label.setStyleSheet('font-style: italic; color: gray;')
        self.status_label.show()
        self.refresh_btn.setEnabled(False)
        self._loader = CollectionLoader(self.user_id, self.api_key)
        self._loader.finished.connect(self._on_api_loaded)
        self._loader.error.connect(self._on_load_error)
        self._loader.start()

    def _on_api_loaded(self, collections):
        self._loader = None
        self.refresh_btn.setEnabled(True)
        self._on_collections_loaded(collections)
        self.status_label.setText('Updated from Zotero')

    def _on_collections_loaded(self, collections):
        self._collections = collections
        self._build_tree(collections)
        self.import_btn.setEnabled(True)

    def _on_load_error(self, msg):
        self._loader = None
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f'Error: {msg}')
        self.status_label.setStyleSheet('color: red;')

    def _build_tree(self, collections):
        self.tree.clear()
        items_by_key = {}

        for col in collections:
            item = QTreeWidgetItem([col['name']])
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, col)
            items_by_key[col['key']] = item

        for col in collections:
            item = items_by_key[col['key']]
            parent_key = col['parent_key']
            if parent_key and parent_key in items_by_key:
                items_by_key[parent_key].addChild(item)
            else:
                self.tree.addTopLevelItem(item)

        self.tree.expandAll()

    def _on_import(self):
        self.selected_collections = []
        self._collect_checked(self.tree.invisibleRootItem())
        if not self.selected_collections:
            QMessageBox.information(self, 'No Selection', 'Please select at least one collection.')
            return
        self.accept()

    def _collect_checked(self, parent):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.checkState(0) == Qt.CheckState.Checked:
                col = child.data(0, Qt.ItemDataRole.UserRole)
                if col:
                    self.selected_collections.append(col)
            self._collect_checked(child)
