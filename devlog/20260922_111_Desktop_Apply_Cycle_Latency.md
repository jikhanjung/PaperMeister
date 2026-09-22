# 111 — The select → Metadata → Apply → next cycle felt slow

**Date:** 2026-09-22
**Scope:** `desktop/services/paper_service.py` (`_RowContext`), `desktop/services/library.py`
(counts), `papermeister/database.py` (two indexes), `desktop/windows/main_window.py`
(`_recount_library`), `desktop/views/source_nav.py` (`refresh(folders)`), tests

## Measured (live library: 9,901 papers, 20,017 files, 9,388 biblio rows)

| step | before | after |
|---|---|---|
| `DetailPanel.show_paper` (Metadata tab) | ~10 ms | ~10 ms |
| `list_by_library('all')`, 500 rows | 457 ms | 71 ms |
| `list_by_library('needs_review')` | 655 ms | 177 ms |
| `list_by_folder` | — | 5 ms |
| `corpus_counts()` | 114 ms | 42 ms |
| `load_library_folders()` (7 counts) | 190 ms | ~80 ms |
| `SourceNav.refresh()` | 213 ms | 16 ms + counts |
| UI-thread work after one Apply | **~330 ms** | **~20 ms** |

Selecting a paper was never the problem. Two things were:

1. **Every list row asked the DB three or four times** — its files, its
   biblio statuses, its authors, a stub check — so a 500-row folder was
   ~1,500 queries. `_RowContext` fetches all three in three queries over
   the list's paper ids; `_row_from_paper(paper, source, ctx)` then touches
   nothing. The single-row path (`row_for_paper`, used to refresh one row
   after Apply) is unchanged and a test holds the two equal.
2. **After every Apply the UI thread counted the whole library twice** —
   `corpus_counts()` for the status bar and `load_library_folders()` for
   the STATUS panel inside `SourceNav.refresh()` — with table scans:
   `paperfile.status` and `paperbiblio.status` had no index, the
   needs-review count walked its rows in Python, and the processed count
   JOIN+DISTINCTed 18k file rows. Now: indexes on both status columns
   (`_migrate`, `CREATE INDEX IF NOT EXISTS`), `COUNT(DISTINCT)` in SQL,
   `EXISTS` instead of JOIN+DISTINCT — and the counting runs in a
   `BackgroundTask` after Apply, the widgets updating when it returns
   (`SourceNav.refresh(folders)` takes counts already made).

The Apply itself still waits on the Zotero write-back (network) in its
worker thread; that part shows as "Applying…" and is not UI latency.

Tests: `test_list_rows_batched.py` (batched rows equal the single-row
path across done / review / stub / plain / failed; counts agree with the
lists). **558 passed**.
