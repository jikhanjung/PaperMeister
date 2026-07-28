"""Application bootstrap for the new desktop app."""
import logging
import sys

logger = logging.getLogger("papermeister")

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

from desktop.theme.qss import build_stylesheet
from desktop.theme.tokens import COLORS_DARK, FONT
from desktop.windows.main_window import MainWindow
from papermeister.database import init_db


def _install_excepthook():
    """Backstop for exceptions that escape a slot: log + show a non-fatal dialog
    instead of letting the event loop abort the window silently. This sits behind
    the per-task BackgroundTask.failed handlers and ServerGuard, not in place of
    them."""
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None, "PaperMeister — unexpected error",
                    f"{exc_type.__name__}: {exc}\n\n"
                    "The app is still running and this was logged. "
                    "If it keeps happening, please report it.")
        except Exception:
            pass  # never let the error handler itself crash the app
    sys.excepthook = _hook


def _self_test_requested() -> bool:
    """True when launched as `--self-test`.

    Parsed by hand rather than with argparse: this is the app's only flag, and
    argparse would take over `-h`/`--help` and error out on anything Qt passes
    through (`-platform`, `-style`, ...).
    """
    return '--self-test' in sys.argv[1:]


def _arm_self_test(app) -> None:
    """Boot normally, then quit with 0 once the window is up.

    CI runs this against the *frozen* build, where it is the only thing that
    exercises the bundle end to end — every heavy import, the Qt platform
    plugin, the SQLite driver, the theme's SVG resources, the main window. A
    missing --add-data entry or an unbundled native library produces a working
    source tree and an executable that dies on launch; that is precisely how the
    conda-DLL packaging failure presented (devlog 061), and no source-tree test
    can see it.

    The timer lets the event loop spin first so deferred startup work runs. Top
    level windows are closed before quitting so a stray modal's nested loop
    cannot outlive quit() and hang the runner.
    """
    from PyQt6.QtCore import QTimer

    def _exit():
        logger.info('Self-test: main window reached; exiting cleanly')
        for w in QApplication.topLevelWidgets():
            w.close()
        app.quit()

    QTimer.singleShot(3000, _exit)


def main() -> int:
    _install_excepthook()
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

    if _self_test_requested():
        _arm_self_test(app)

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
