"""Application bootstrap for the new desktop app."""
import sys

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
