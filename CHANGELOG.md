# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
