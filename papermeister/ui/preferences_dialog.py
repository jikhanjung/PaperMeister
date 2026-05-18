from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Preferences')
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        outer = QVBoxLayout(self)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName('PrefsTabs')
        self._tabs.addTab(self._build_ocr_tab(), 'OCR')
        self._tabs.addTab(self._build_biblio_tab(), 'Biblio')
        self._tabs.addTab(self._build_zotero_tab(), 'Zotero')
        self._tabs.addTab(self._build_about_tab(), 'About')
        outer.addWidget(self._tabs)

        # Bottom buttons (shared across tabs)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton('Save')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        outer.addLayout(btn_layout)

    # ── Tab: OCR ────────────────────────────────────────────────

    def _build_ocr_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

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

        runpod_form = QFormLayout()
        self.runpod_endpoint_edit = QLineEdit()
        self.runpod_endpoint_edit.setPlaceholderText('Serverless endpoint ID')
        runpod_form.addRow('Endpoint ID:', self.runpod_endpoint_edit)
        self.runpod_api_key_edit = QLineEdit()
        self.runpod_api_key_edit.setPlaceholderText('RunPod API key')
        self.runpod_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        runpod_form.addRow('API Key:', self.runpod_api_key_edit)
        layout.addLayout(runpod_form)

        pod_form = QFormLayout()
        self.ocr_pod_url_edit = QLineEdit()
        self.ocr_pod_url_edit.setPlaceholderText('http://172.16.112.150:8080')
        pod_form.addRow('URL:', self.ocr_pod_url_edit)
        layout.addLayout(pod_form)

        self._ocr_group.buttonClicked.connect(self._on_ocr_backend_changed)

        layout.addStretch()
        return page

    # ── Tab: Biblio ─────────────────────────────────────────────

    def _build_biblio_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.auto_biblio_checkbox = QCheckBox('Auto-extract biblio after OCR completes')
        self.auto_biblio_checkbox.setToolTip(
            'When off, the pipeline stops at OCR done — no biblio extraction is queued.'
        )
        layout.addWidget(self.auto_biblio_checkbox)

        self.manual_biblio_checkbox = QCheckBox('Enable manual biblio extraction (right-click → Extract Biblio)')
        self.manual_biblio_checkbox.setToolTip(
            'When off, the right-click "Extract Biblio" item is greyed out.'
        )
        layout.addWidget(self.manual_biblio_checkbox)

        self._biblio_claude_radio = QRadioButton('Claude Sonnet (claude -p, Max plan)')
        self._biblio_qwen_radio = QRadioButton('Qwen3-14B (local server, uses OCR URL)')
        self._biblio_group = QButtonGroup(self)
        self._biblio_group.addButton(self._biblio_claude_radio)
        self._biblio_group.addButton(self._biblio_qwen_radio)
        layout.addWidget(self._biblio_claude_radio)
        layout.addWidget(self._biblio_qwen_radio)

        # Radios enabled if either auto OR manual is on (= biblio extraction
        # happens via at least one path, so the engine choice is meaningful).
        self.auto_biblio_checkbox.toggled.connect(self._refresh_biblio_radio_state)
        self.manual_biblio_checkbox.toggled.connect(self._refresh_biblio_radio_state)

        layout.addStretch()
        return page

    def _refresh_biblio_radio_state(self):
        any_on = (
            self.auto_biblio_checkbox.isChecked()
            or self.manual_biblio_checkbox.isChecked()
        )
        self._biblio_claude_radio.setEnabled(any_on)
        self._biblio_qwen_radio.setEnabled(any_on)

    # ── Tab: Zotero ─────────────────────────────────────────────

    def _build_zotero_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.user_id_edit = QLineEdit()
        self.user_id_edit.setPlaceholderText('Numeric user ID from zotero.org/settings/keys')
        form.addRow('User ID:', self.user_id_edit)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText('API key from zotero.org/settings/keys')
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('API Key:', self.api_key_edit)
        layout.addLayout(form)

        self.writeback_checkbox = QCheckBox('Enable Zotero write-back (Apply Biblio updates Zotero items)')
        self.writeback_checkbox.setToolTip(
            'When off, Apply Biblio updates only the local mirror. '
            'Requires an API key with write access on zotero.org/settings/keys.'
        )
        layout.addWidget(self.writeback_checkbox)

        self.upload_json_checkbox = QCheckBox('Upload OCR JSON as Zotero sibling attachment after OCR')
        self.upload_json_checkbox.setToolTip(
            'Uploads the raw OCR JSON cache to the same Zotero item as the PDF after OCR completes. '
            'Runs once per paper (skips if a sibling JSON already exists). Requires write access.'
        )
        layout.addWidget(self.upload_json_checkbox)

        test_btn = QPushButton('Test Zotero Connection')
        test_btn.clicked.connect(self._test_connection)
        layout.addWidget(test_btn)

        self.status_label = QLabel('')
        layout.addWidget(self.status_label)

        layout.addStretch()
        return page

    # ── Tab: About ──────────────────────────────────────────────

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        from ..preferences import get_client_id

        intro = QLabel('PaperMeister desktop')
        intro.setStyleSheet('font-weight: bold; font-size: 14px;')
        layout.addWidget(intro)

        form = QFormLayout()
        cid_value = QLineEdit(get_client_id())
        cid_value.setReadOnly(True)
        cid_value.setToolTip(
            'Per-install identifier sent to the OCR wrapper. '
            'Used for server-side dedup and to distinguish your jobs from '
            "other clients' jobs when the server is busy."
        )
        form.addRow('Client ID:', cid_value)
        layout.addLayout(form)

        hint = QLabel(
            'Client ID is generated lazily on first OCR submission and '
            'persisted to ~/.papermeister/preferences.json.'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #888;')
        layout.addWidget(hint)

        layout.addStretch()
        return page

    # ── Helpers ─────────────────────────────────────────────────

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
        self.auto_biblio_checkbox.setChecked(bool(get_pref('auto_biblio_extract', True)))
        self.manual_biblio_checkbox.setChecked(bool(get_pref('manual_biblio_extract', True)))
        self._refresh_biblio_radio_state()
        self.user_id_edit.setText(get_pref('zotero_user_id', ''))
        self.api_key_edit.setText(get_pref('zotero_api_key', ''))
        self.writeback_checkbox.setChecked(bool(get_pref('zotero_writeback_enabled', False)))
        self.upload_json_checkbox.setChecked(bool(get_pref('zotero_upload_ocr_json', False)))

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
        set_pref('auto_biblio_extract', self.auto_biblio_checkbox.isChecked())
        set_pref('manual_biblio_extract', self.manual_biblio_checkbox.isChecked())
        set_pref('zotero_user_id', self.user_id_edit.text().strip())
        set_pref('zotero_api_key', self.api_key_edit.text().strip())
        set_pref('zotero_writeback_enabled', self.writeback_checkbox.isChecked())
        set_pref('zotero_upload_ocr_json', self.upload_json_checkbox.isChecked())
        reset_ocr_config()
        self.accept()
