import sys

from PyQt6.QtWidgets import QApplication

from papermeister.database import init_db
from papermeister.ui.main_window import MainWindow


def main():
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName('PaperMeister')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
