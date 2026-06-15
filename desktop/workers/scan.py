"""Background worker for local-folder import (filesystem scan + hash dedup).

Wraps `ingestion.import_source_directory` in a QThread and forwards its
per-file progress so the UI can show a live progress window instead of a single
status-bar line. It first does a quick pre-walk to count PDFs (no hashing) so
the progress bar can be determinate (X / N). ORM objects never cross the thread
boundary — only plain data is emitted (peewee connections are thread-local).
"""
import os

from PyQt6.QtCore import QThread, pyqtSignal


class ScanWorker(QThread):
    counted = pyqtSignal(int)    # total PDFs found by the pre-walk
    progress = pyqtSignal(str)   # per-PDF message, e.g. "Found: paper.pdf"
    done = pyqtSignal(object)    # (source_id, source_name, new_count)
    failed = pyqtSignal(str)     # error message

    def __init__(self, dir_path: str, parent=None):
        super().__init__(parent)
        self._dir = dir_path

    def run(self):
        try:
            self.counted.emit(self._count_pdfs(self._dir))
            from papermeister.ingestion import import_source_directory
            source, new_files = import_source_directory(
                self._dir,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            # Read the few scalar fields we need here, in the worker thread.
            self.done.emit((source.id, source.name, len(new_files)))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f'{type(exc).__name__}: {exc}')

    @staticmethod
    def _count_pdfs(root: str) -> int:
        """Count PDFs the same way _scan_dir selects them (dotfiles skipped,
        *.pdf case-insensitive, recurse subdirs, unreadable dirs skipped) so the
        total matches what the import will actually walk."""
        total = 0
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                entries = os.listdir(d)
            except (PermissionError, OSError):
                continue
            for entry in entries:
                if entry.startswith('.'):
                    continue
                full = os.path.join(d, entry)
                if os.path.isfile(full) and entry.lower().endswith('.pdf'):
                    total += 1
                elif os.path.isdir(full):
                    stack.append(full)
        return total
