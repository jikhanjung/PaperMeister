# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- **The Windows installer now installs to `%LOCALAPPDATA%\PaleoBytes\PaperMeister`**
  and appears under a PaleoBytes group in the Start menu, alongside the other
  tools. It also carries a publisher name and a stable application id, so future
  versions upgrade in place instead of installing beside each other. Your library
  is untouched by install or uninstall — it lives in
  `%USERPROFILE%\PaleoBytes\PaperMeister`.
- **User data now lives in `~/PaleoBytes/PaperMeister/`**, the layout shared with
  Modan2 and CTHarvester, instead of `~/.papermeister/`. If you still have data
  in the old location, close the app and run
  `python scripts/migrate_data_dir.py --execute` (add `--copy` to leave the
  original in place) — the app will tell you at startup if it finds one.

---

## [0.1.3] - 2026-07-28

Keeps a paper's work when the model server restarts under it.

### Fixed
- **A restarting model server no longer costs a paper's work.** When the
  container behind the LLM dies, extraction now waits for it to come back and
  resumes the same batch, instead of failing the paper and discarding every
  reference already parsed for it. Previously the retry gave up after twenty
  seconds — a container restart takes minutes, so it never once succeeded.

### Added
- **Language switcher in the manual.** Every page links to its counterpart in the
  other language, keeping you on the same page rather than sending you back to
  the index. Already live on the documentation site.

---

## [0.1.2] - 2026-07-28

References extraction that reports what went wrong and recovers from most of it,
plus a documentation site.

### Fixed
- **The Windows installer is attached to releases again.** It was built and
  checksummed but never uploaded — it sat deeper in the artifact tree than the
  release step's file pattern reached, so v0.1.1 shipped the portable zip only.
- **References extraction no longer loses work silently.** A batch that hit a
  truncated model response, a crash-looping OCR/LLM server, or a document with
  no bibliography used to drop the affected references and, in some cases, mark
  the paper permanently done with nothing stored. Each of those now either
  recovers or leaves the paper to be retried:
  - a response cut off at the token limit is retried with more room, then split,
    before anything is given up on
  - a server that restarts mid-request is ridden through with a short retry
  - a paper that genuinely has no bibliography (a letter, plates, front matter)
    is recorded as checked rather than retried forever
  - a paper that *does* have one but returns nothing stays unchecked, so a later
    run tries again
- **Batches no longer stall on an unsplittable request.** A request too large to
  finish was re-sent unchanged until the batch controller bottomed out — roughly
  25 minutes per paper. It is now shortened on the first retry, and the read
  timeout was raised to 480 s so work the server actually completed is not
  discarded nine seconds short.
- **The source tab stays put.** Switching to another source and then having the
  Zotero sync finish (or applying biblio) no longer snaps the tab bar back to
  the first tab, which left the selected tab and the listed papers disagreeing.

### Added
- **Released builds are now launched before being published.** Every platform's
  frozen executable is started headless and has to reach a live main window and
  exit cleanly, or the build fails. This catches the "works from source, dies
  when packaged" class — a missing bundled file or native library — which no
  test against the source tree can see.
- **Documentation site.** A full manual in English and Korean at
  https://jikhanjung.github.io/PaperMeister/ — installation, a quick start
  through the whole pipeline, a user guide, an FAQ, troubleshooting drawn from
  real failures, and a developer guide.
- **Diagnosable extraction.** A partial result now says why it was partial
  (truncated response, no JSON array, timeout) instead of just "server?", and
  `~/.papermeister/logs/biblio_YYYYMMDD.log` records the per-batch detail
  including the offending response. Progress windows timestamp with the date, so
  a log excerpt from a multi-day run is unambiguous.

### Changed
- Dependencies updated to current versions (peewee 4, pyzotero 1.13,
  PyMuPDF 1.28); Zotero write-back handles both the old and new pyzotero error
  classes and HTTP backends.

---


## [0.1.1] - 2026-07-24

Citation-network visualization, installers for all three desktop platforms, and
dependency-security hardening.

### Added
- **Citation network graph.** Right-click a paper → an interactive ego-network
  of its citations: the papers it cites, the papers that cite it, and the
  external works it cites that aren't in the library. Node fill shows the
  direction relative to the focused paper; the border marks whether a paper is
  held with a PDF, held without one, or external (cited-only). Click a node to
  re-center and walk the graph.
- **Installers for every platform.** In addition to the Windows portable zip,
  releases now include a Windows installer (Inno Setup), a Linux **AppImage**,
  and a macOS **DMG** — all built and published by CI on a tag.
- **Global crash handler.** An unexpected error now surfaces as a dialog and is
  logged, instead of silently closing the window.

### Changed
- The references (Qwen) read timeout was raised from 240 s to 360 s and made
  adjustable via a preference, so an occasional busy-GPU spike no longer aborts
  a batch.

### Security
- Removed the unused `python-dotenv` dependency and updated Pillow (→ 12.3) and
  requests (→ 2.33) to versions without known advisories; CI now runs
  `pip-audit` on every push and weekly.


## [0.1.0] - 2026-07-23

Initial tagged release of the PaperMeister desktop app.

### Added
- Turn a PDF paper collection into a searchable knowledge base: PDF library with
  Zotero sync, OCR (RunPod / Chandra2), LLM bibliographic extraction, and
  full-text (FTS5) search with title-boosted ranking and match highlighting.
- **References & citation network.** Parse each paper's reference list, resolve
  citations to held papers, and normalize external cited works into canonical
  nodes — the foundation of the citation network.
- **Server-outage resilience.** References / biblio / OCR batches pause and
  auto-resume when the LLM or OCR server goes down, instead of failing every
  remaining item.
- CJK author names shown surname-first joined (정직한) in the paper list.
- Windows portable build (PyInstaller) produced by CI, with a cross-platform
  test suite (ruff + mypy + pytest on Linux and Windows).
