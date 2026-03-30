from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Preferences')
        self.setMinimumWidth(450)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # RunPod section
        runpod_label = QLabel('RunPod OCR')
        runpod_label.setStyleSheet('font-weight: bold; font-size: 14px;')
        layout.addWidget(runpod_label)

        runpod_form = QFormLayout()
        self.runpod_endpoint_edit = QLineEdit()
        self.runpod_endpoint_edit.setPlaceholderText('Serverless endpoint ID')
        runpod_form.addRow('Endpoint ID:', self.runpod_endpoint_edit)

        self.runpod_api_key_edit = QLineEdit()
        self.runpod_api_key_edit.setPlaceholderText('RunPod API key')
        self.runpod_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        runpod_form.addRow('API Key:', self.runpod_api_key_edit)
        layout.addLayout(runpod_form)

        layout.addSpacing(16)

        # Zotero section
        zotero_label = QLabel('Zotero API')
        zotero_label.setStyleSheet('font-weight: bold; font-size: 14px;')
        layout.addWidget(zotero_label)

        zotero_form = QFormLayout()
        self.user_id_edit = QLineEdit()
        self.user_id_edit.setPlaceholderText('Numeric user ID from zotero.org/settings/keys')
        zotero_form.addRow('User ID:', self.user_id_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText('API key from zotero.org/settings/keys')
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        zotero_form.addRow('API Key:', self.api_key_edit)
        layout.addLayout(zotero_form)

        # Test connection button
        test_btn = QPushButton('Test Zotero Connection')
        test_btn.clicked.connect(self._test_connection)
        layout.addWidget(test_btn)

        self.status_label = QLabel('')
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton('Save')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _load_values(self):
        from ..preferences import get_pref
        self.runpod_endpoint_edit.setText(get_pref('runpod_endpoint_id', ''))
        self.runpod_api_key_edit.setText(get_pref('runpod_api_key', ''))
        self.user_id_edit.setText(get_pref('zotero_user_id', ''))
        self.api_key_edit.setText(get_pref('zotero_api_key', ''))

    def _test_connection(self):
        user_id = self.user_id_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        if not user_id or not api_key:
            self.status_label.setText('Please enter both User ID and API Key.')
            self.status_label.setStyleSheet('color: red;')
            return

        self.status_label.setText('Testing...')
        self.status_label.setStyleSheet('color: gray;')
        self.status_label.repaint()

        try:
            from ..zotero_client import ZoteroClient
            client = ZoteroClient(user_id, api_key)
            if client.test_connection():
                self.status_label.setText('Connection successful!')
                self.status_label.setStyleSheet('color: green;')
            else:
                self.status_label.setText('Connection failed. Check your credentials.')
                self.status_label.setStyleSheet('color: red;')
        except Exception as e:
            self.status_label.setText(f'Error: {e}')
            self.status_label.setStyleSheet('color: red;')

    def _save(self):
        from ..preferences import set_pref
        set_pref('runpod_endpoint_id', self.runpod_endpoint_edit.text().strip())
        set_pref('runpod_api_key', self.runpod_api_key_edit.text().strip())
        set_pref('zotero_user_id', self.user_id_edit.text().strip())
        set_pref('zotero_api_key', self.api_key_edit.text().strip())
        self.accept()
