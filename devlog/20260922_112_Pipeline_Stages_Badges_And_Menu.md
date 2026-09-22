# 112 — The pipeline, stage by stage: badges, the menu, the Metadata card

**Date:** 2026-09-22
**Scope:** `desktop/services/paper_service.py` (`Stages`, `load_stages`, `_RowContext`),
`desktop/views/paper_list.py` (Stages column, `StagesDelegate`, context menu),
`desktop/views/detail_panel.py` (PROCESSING card), tests

## The pipeline

A paper goes through four stages after it is in the library. Each has a
small set of states, in order of progress:

| stage | states | source of truth |
|---|---|---|
| **OCR** | none (no PDF) → pending → done / failed | `PaperFile.status` |
| **Bibliography** | none → extracted → needs review → done (applied) | `PaperBiblio.status` |
| **References** | none → partial → done / failed (3 attempts) | `Paper.references_checked`, `references_attempts`, `Reference` rows |
| **Figures** | none → assembled → captioned → split | `Figure` rows: `link_key`, `panel_key`, `FigurePanel` |

Until now only the first two were visible: the Status pill said
pending / OCR / rev / done and nothing about references or figures, and
the context menu offered the same items to a paper whether it had been
through them or not.

## What a person sees

- **List — a Stages column** next to Status: four mini-badges `OCR BIB
  REF FIG`, each in its state's colour (green done, blue well along, amber
  a person's turn, red failed, grey pending, muted not run). The tooltip
  says the details; a header click sorts by progress.
- **Context menu follows the stages.** Before OCR only OCR is offered
  (everything after reads the text). Then, per stage, what moves it on:
  *Extract Bibliography* / *Review Bibliography* / *Re-extract*; *Extract
  References* / *Retry References* / *Re-extract*; *Process Figures* with
  the label naming what is next — `(assemble → captions → panels)`,
  `(captions → panels)`, `(panels)`, `(re-check)`. Open PDF and the
  citation network stay on every paper.
- **Metadata tab — a PROCESSING card** between the metadata and the file:
  one row per stage with its state and what it produced ("14 figures ·
  14 captioned · 10 split into 136 panels", "152 extracted, 12 in
  library", "gave up after 3 attempts (152 partial)").

## How

`Stages` (frozen dataclass: four states + a `detail` line per stage) is
built by `_stages_from(...)` from facts the row already has plus two
grouped queries the `_RowContext` (111) runs once per list — references
(count, in library) and figures (count, captioned, split, panels; a
`FigurePanel` count subquery joined in). `load_stages(paper_id)` does the
same for one paper. A 500-row list is ~115 ms with the stages (was 71
without; 457 before 111).

The list item carries the `Stages` object in a data role; the delegate
paints from it, the menu reads it, and the sort text is a rank string.

Tests: the menu's labels per stage combination and the OCR-first rule
(`test_figures_action.py`); batched and single-row stages agree and the
tooltip reads right (`test_list_rows_batched.py`). **561 passed**.
