from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
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

        # OCR Engine section
        ocr_label = QLabel('OCR Engine')
        ocr_label.setStyleSheet('font-weight: bold; font-size: 14px;')
        layout.addWidget(ocr_label)

        # Backend radio buttons
        self._ocr_runpod_radio = QRadioButton('RunPod Serverless')
        self._ocr_pod_radio = QRadioButton('Direct vLLM')
        self._ocr_wrapper_radio = QRadioButton('Wrapper API')
        self._ocr_group = QButtonGroup(self)
        self._ocr_group.addButton(self._ocr_runpod_radio)
        self._ocr_group.addButton(self._ocr_pod_radio)
        self._ocr_group.addButton(self._ocr_wrapper_radio)
        layout.addWidget(self._ocr_runpod_radio)
        layout.addWidget(self._ocr_pod_radio)
        layout.addWidget(self._ocr_wrapper_radio)

        # RunPod fields
        self._runpod_form = QFormLayout()
        self.runpod_endpoint_edit = QLineEdit()
        self.runpod_endpoint_edit.setPlaceholderText('Serverless endpoint ID')
        self._runpod_form.addRow('Endpoint ID:', self.runpod_endpoint_edit)

        self.runpod_api_key_edit = QLineEdit()
        self.runpod_api_key_edit.setPlaceholderText('RunPod API key')
        self.runpod_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._runpod_form.addRow('API Key:', self.runpod_api_key_edit)
        layout.addLayout(self._runpod_form)

        # Pod / Wrapper URL field (shared — both use ocr_pod_url)
        self._pod_form = QFormLayout()
        self.ocr_pod_url_edit = QLineEdit()
        self.ocr_pod_url_edit.setPlaceholderText('http://172.16.112.150:8080')
        self._pod_form.addRow('URL:', self.ocr_pod_url_edit)
        layout.addLayout(self._pod_form)

        self._ocr_group.buttonClicked.connect(self._on_ocr_backend_changed)

        layout.addSpacing(16)

        # Biblio extraction section
        biblio_label = QLabel('Biblio Extraction')
        biblio_label.setStyleSheet('font-weight: bold; font-size: 14px;')
        layout.addWidget(biblio_label)

        self._biblio_claude_radio = QRadioButton('Claude Sonnet (claude -p, Max plan)')
        self._biblio_qwen_radio = QRadioButton('Qwen3-14B (local server, uses OCR URL)')
        self._biblio_group = QButtonGroup(self)
        self._biblio_group.addButton(self._biblio_claude_radio)
        self._biblio_group.addButton(self._biblio_qwen_radio)
        layout.addWidget(self._biblio_claude_radio)
        layout.addWidget(self._biblio_qwen_radio)

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

    def _on_ocr_backend_changed(self):
        is_runpod = self._ocr_runpod_radio.isChecked()
        needs_url = self._ocr_pod_radio.isChecked() or self._ocr_wrapper_radio.isChecked()
        self.runpod_endpoint_edit.setEnabled(is_runpod)
        self.runpod_api_key_edit.setEnabled(is_runpod)
        self.ocr_pod_url_edit.setEnabled(needs_url)

    def _load_values(self):
        from ..preferences import get_pref
        backend = get_pref('ocr_backend', 'serverless')
        if backend == 'wrapper':
            self._ocr_wrapper_radio.setChecked(True)
        elif backend == 'pod':
            self._ocr_pod_radio.setChecked(True)
        else:
            self._ocr_runpod_radio.setChecked(True)
        self.runpod_endpoint_edit.setText(get_pref('runpod_endpoint_id', ''))
        self.runpod_api_key_edit.setText(get_pref('runpod_api_key', ''))
        self.ocr_pod_url_edit.setText(get_pref('ocr_pod_url', ''))
        self._on_ocr_backend_changed()
        biblio_backend = get_pref('biblio_backend', 'claude')
        if biblio_backend == 'qwen':
            self._biblio_qwen_radio.setChecked(True)
        else:
            self._biblio_claude_radio.setChecked(True)
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
        from ..ocr import reset_config as reset_ocr_config
        if self._ocr_wrapper_radio.isChecked():
            backend = 'wrapper'
        elif self._ocr_pod_radio.isChecked():
            backend = 'pod'
        else:
            backend = 'serverless'
        set_pref('ocr_backend', backend)
        set_pref('runpod_endpoint_id', self.runpod_endpoint_edit.text().strip())
        set_pref('runpod_api_key', self.runpod_api_key_edit.text().strip())
        set_pref('ocr_pod_url', self.ocr_pod_url_edit.text().strip())
        set_pref('biblio_backend', 'qwen' if self._biblio_qwen_radio.isChecked() else 'claude')
        set_pref('zotero_user_id', self.user_id_edit.text().strip())
        set_pref('zotero_api_key', self.api_key_edit.text().strip())
        reset_ocr_config()
        self.accept()
