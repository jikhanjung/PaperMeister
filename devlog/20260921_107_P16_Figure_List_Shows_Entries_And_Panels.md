# 107 — P16 Phase 5, step 1: the figure list says what ② and ③ left

**Date:** 2026-09-21
**Scope:** `desktop/services/paper_service.py` (`FigureRow`, `load_figures`),
`desktop/components/figure_list.py`, tests
**Follows:** [106](./20260918_106_P16_Process_Figures_In_The_App.md)

## Why

After the app (or the lanes) ran captions and panels, the Text tab's figure
list still read `Plate I · p. 35 · plate, 33 photos · caption` — the 820
panels of paper 7450 were in the DB and invisible. The review sheet
(`scripts/panel_sheet.py`, and the artifact made from it) showed what a
reviewer actually looks for: how many panels for how many entries, an entry
no panel claimed, a split that was rejected. Those four facts fit on the
line.

## What

`FigureRow` gains `entries`, `panels`, `unmatched` (entries no panel's
`entry_orders_json` names) and `panel_state` — `''` not run, `split`,
`single` (the model said not compound), `failed` (attempts but no result).
`load_figures` computes them with **two queries per paper** (entries joined
to Figure, panels joined to Figure), not two per figure — a plate paper has
a hundred rows and the tab rebuilds this on every paper switch.

The line appends, after the caption state:

| state | line ends with |
|---|---|
| split | `33 panels / 33 entries`, plus `1 unmatched` when an entry has no panel |
| single | `single image` (`, 6 entries` when linked) |
| failed | `panels failed, 6 entries` |
| linked only | `6 entries` |

The tooltip keeps the caption and adds one sentence about the panels
("22 panels matched to 23 caption entries. 1 entries have no panel — check
the plate.").

## Not here

Step 2 — panel tiles under a chosen figure (crop `bbox_page_1000`, then
`bbox_figure_1000`, through the `ocr_view` render worker), label and matched
entry per tile. Then, maybe, boxes drawn over the reader's figure images.

Tests: 5 in `test_figure_list.py` (new: the five line shapes and the
tooltip), pipeline test asserts the counts; **539 passed**.
