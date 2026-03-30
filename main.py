import os
import sys

from PyQt6.QtWidgets import QApplication

from papermeister.database import init_db
from papermeister.ui.main_window import MainWindow


def _migrate_env_to_prefs():
    """One-time migration: move .env RunPod keys to preferences.json."""
    from papermeister.preferences import get_pref, set_pref
    if get_pref('runpod_endpoint_id'):
        return  # already migrated
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, _, value = line.partition('=')
                key, value = key.strip(), value.strip()
                if key == 'RUNPOD_ENDPOINT_ID':
                    set_pref('runpod_endpoint_id', value)
                elif key == 'RUNPOD_API_KEY':
                    set_pref('runpod_api_key', value)


def main():
    init_db()
    _migrate_env_to_prefs()
    app = QApplication(sys.argv)
    app.setApplicationName('PaperMeister')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
