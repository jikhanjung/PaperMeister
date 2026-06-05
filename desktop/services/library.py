"""Library folder queries — operational views across all sources.

These return counts/IDs only; the view layer turns them into widgets.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from papermeister.models import Paper, PaperBiblio, PaperFile


def needs_review_paper_ids() -> list[int]:
    """Paper ids whose best biblio is flagged `needs_review` (P08 §5).

    Single source of truth for both the count in the Library tree and the
    list shown by `paper_service.list_by_library('needs_review')` — sharing
    this helper makes it structurally impossible for the two to diverge.

    Trashed papers are excluded (the row may still exist locally because we
    only mirror the Zotero trash flag, not the deletion itself).
    """
    seen: list[int] = []
    in_set: set[int] = set()
    # Iterate rather than SQL DISTINCT: dedupe in Python so the count and
    # list paths share the exact same result set, regardless of how peewee
    # renders `.distinct()` across versions.
    for b in (
        PaperBiblio
        .select(PaperBiblio.paper)
        .join(Paper, on=(PaperBiblio.paper == Paper.id))
        .where(
            (PaperBiblio.status == 'needs_review')
            & (Paper.trashed_at.is_null())
        )
    ):
        pid = b.paper_id
        if pid not in in_set:
            in_set.add(pid)
            seen.append(pid)
    return seen


@dataclass(frozen=True)
class LibraryFolder:
    key: str
    title: str
    count: int


LIBRARY_KEYS = [
    ('all',          'All Papers'),
    ('pending',      'Pending OCR'),
    ('processed',    'Processed'),
    ('failed',       'Failed'),
    ('needs_review', 'Needs Review'),
    ('recent',       'Recently Added'),
    ('trash',        'Trash'),
]


# All counts/filters below exclude trashed papers by default; the dedicated
# 'trash' key flips the predicate to include only trashed papers.


def _count_all() -> int:
    return Paper.select().where(Paper.trashed_at.is_null()).count()


def _count_status(status: str) -> int:
    """Count distinct non-trashed papers that have at least one PaperFile with this status."""
    return (
        Paper.select()
        .join(PaperFile, on=(PaperFile.paper == Paper.id))
        .where((PaperFile.status == status) & (Paper.trashed_at.is_null()))
        .distinct()
        .count()
    )


def _count_needs_review() -> int:
    """Papers whose best biblio is flagged needs_review (P08 §5)."""
    return len(needs_review_paper_ids())


def _count_recent() -> int:
    cutoff = datetime.now() - timedelta(days=30)
    return (
        Paper.select()
        .where((Paper.created_at >= cutoff) & (Paper.trashed_at.is_null()))
        .count()
    )


def _count_trash() -> int:
    return Paper.select().where(Paper.trashed_at.is_null(False)).count()


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
        elif key == 'trash':
            count = _count_trash()
        else:
            count = 0
        folders.append(LibraryFolder(key=key, title=title, count=count))
    return folders


def corpus_counts() -> tuple[int, int, int]:
    """(total, pending, needs_review) — used by the status bar."""
    return _count_all(), _count_status('pending'), _count_needs_review()
