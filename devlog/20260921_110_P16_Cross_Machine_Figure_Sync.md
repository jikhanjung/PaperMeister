# 110 — P16: figures cross machines both ways

**Date:** 2026-09-21
**Scope:** `papermeister/figure_share.py` (`import_from_cache_if_new`),
`desktop/services/paper_service.py` (`_import_shared_figures`),
`papermeister/ingestion.py` (`_refresh_sibling_json`), `papermeister/zotero_client.py`
(attachment `md5`), tests
**Follows:** [105](./20260918_105_P16_Figures_Ride_In_The_OCR_JSON.md)

## The gap

105 put the figure results in the cache JSON and the Zotero sibling, and
landed them on a machine that had **no** rows — a fresh library, or a paper
OCR'd here for the first time. Two cases stayed open, both "this machine
already has the paper":

1. The cache JSON changed (another machine's export arrived) but the app
   only imported when the file had no rows.
2. The Zotero sibling changed but the sibling is downloaded only when the
   local cache is missing — a machine that OCR'd the paper itself never saw
   what the other machine did afterwards.

A library working from local PDFs only never hits either: there is one
cache JSON and one machine.

## 1. Cache JSON → DB, whenever it changed

`figure_share.import_from_cache_if_new(pf, seen)` reads the JSON and
imports when its `figures.exported_at` differs from what this session last
landed for the file. `import_figures` is safe to repeat — newer stage
timestamps only, a person's rows never — so the only question is whether
the JSON changed; `seen` (per session, per file) answers it without a
schema change. The app's `_import_shared_figures` calls it from
`load_figures` (Figures tab, Text tab unions).

## 2. Zotero sibling → cache, at sync time

The incremental sync already returns an attachment whose file was replaced
(new version, new `md5`) — it just did nothing with it beyond a filename
refresh. `_classify_raw_items` now carries the attachment's `md5`, and
`ingestion._refresh_sibling_json` runs for every existing JSON sibling in
the batch (main loop and orphans): if the local cache exists and its md5
differs from Zotero's, download the sibling, write the cache, and land its
`figures` on the PDF row with the matching `file_hash`. Same content (our
own push comes back with our md5), no md5, no cache, or not a JSON → left
alone. Failures are reported to the sync log and never fail the sync.

Tests: `test_figure_share.py` (a changed JSON lands once per export, an
unchanged one not at all; the other machine's panels land on rows here);
`test_sibling_json_refresh.py` (a replaced sibling is refetched and its
caption lands; unchanged / uncached / non-JSON are left alone).
**552 passed**.
