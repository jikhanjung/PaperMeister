"""Library folder queries — operational views across all sources.

These return counts/IDs only; the view layer turns them into widgets.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from papermeister.models import Paper, PaperBiblio, PaperFile


@dataclass(frozen=True)
class LibraryFolder:
    key: str
    title: str
    count: int


LIBRARY_KEYS = [
    ('all',          'All Files'),
    ('pending',      'Pending OCR'),
    ('processed',    'Processed'),
    ('failed',       'Failed'),
    ('needs_review', 'Needs Review'),
    ('recent',       'Recently Added'),
]


def _count_all() -> int:
    return PaperFile.select().count()


def _count_status(status: str) -> int:
    return PaperFile.select().where(PaperFile.status == status).count()


def _count_needs_review() -> int:
    # Phase 2 adds PaperBiblio.status; until then, approximate with
    # "Paper is a stub AND has a PaperBiblio extraction".
    # Stub Paper ≈ year is null and no author rows (derived judgment, cheap query).
    query = (
        PaperBiblio
        .select(PaperBiblio.paper)
        .distinct()
        .join(Paper, on=(PaperBiblio.paper == Paper.id))
        .where(Paper.year.is_null(True))
    )
    return query.count()


def _count_recent() -> int:
    cutoff = datetime.now() - timedelta(days=30)
    return Paper.select().where(Paper.created_at >= cutoff).count()


def load_library_folders() -> list[LibraryFolder]:
    folders: list[LibraryFolder] = []
    for key, title in LIBRARY_KEYS:
        if key == 'all':
            count = _count_all()
        elif key == 'pending':
            count = _count_status('pending')
        elif key == 'processed':
            count = _count_status('processed')
        elif key == 'failed':
            count = _count_status('failed')
        elif key == 'needs_review':
            count = _count_needs_review()
        elif key == 'recent':
            count = _count_recent()
        else:
            count = 0
        folders.append(LibraryFolder(key=key, title=title, count=count))
    return folders


def corpus_counts() -> tuple[int, int, int]:
    """(total, pending, needs_review) — used by the status bar."""
    return _count_all(), _count_status('pending'), _count_needs_review()
