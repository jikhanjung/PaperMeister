"""Application bootstrap for the new desktop app."""
import sys

# Institutional networks with custom CAs cause SSL errors with pyzotero.
# pyzotero calls requests.get/post directly (no Session), so we patch the
# default verify parameter at the module level.
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_original_request = requests.api.request
def _no_verify_request(method, url, **kwargs):
    kwargs.setdefault('verify', False)
    return _original_request(method, url, **kwargs)
requests.api.request = _no_verify_request

from PyQt6.QtWidgets import QApplication

from papermeister.database import init_db
from desktop.theme.qss import build_stylesheet
from desktop.theme.tokens import COLORS_DARK, FONT
from desktop.windows.main_window import MainWindow


def main() -> int:
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName('PaperMeister')
    app.setApplicationDisplayName('PaperMeister')

    # Global font — falls back gracefully if Inter is not installed.
    from PyQt6.QtGui import QFont
    base_font = QFont()
    base_font.setFamilies(['Inter', '-apple-system', 'Segoe UI', 'Noto Sans', 'sans-serif'])
    base_font.setPointSize(FONT['size.md'])
    app.setFont(base_font)

    app.setStyleSheet(build_stylesheet(COLORS_DARK))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
