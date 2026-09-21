# 108 — P16 Phase 5, steps 2–3: panel tiles, and boxes over the reader's figures

**Date:** 2026-09-21
**Scope:** `desktop/components/panel_tiles.py` (new), `desktop/components/ocr_view.py`
(`draw_panel_boxes`, `set_panels`, `refresh_figures`), `desktop/components/figure_list.py`
(`figure_chosen`, `boxes_toggled`, "Panel boxes" checkbox), `desktop/services/paper_service.py`
(`PanelInfo`, `PanelSet`, `load_panels`, `load_panel_boxes`, `panel_colour`),
`desktop/views/detail_panel.py`, `tests/test_panel_tiles.py`
**Follows:** [107](./20260921_107_P16_Figure_List_Shows_Entries_And_Panels.md)

## What a person sees

Text tab, a paper whose plates were split (③):

1. **Figure list line** (107): `Plate I · p. 35 · plate, 33 photos · caption · 33 panels / 33 entries`.
2. **Choose a line** → under the list, the figure's panels as **tiles**: the
   specimen crop with a coloured frame, its label under it; hover or click
   gives the caption entry it was matched to (label — description, specimen
   number). The header says `Plate I — 33 panels`, and `no panel for 14` when
   an entry was left unclaimed. A tile marked as annotation (scale bar, key)
   or with confidence below high is dimmed and says so.
3. **In the reader**, the same boxes are **drawn over the figure images**, in
   the same colours as the tiles' frames — a tile and its box match. A
   **"Panel boxes"** checkbox in the list header (shown only when there is
   something to draw) turns them off for a clean look at the plate.

## How

- `load_panels(figure_id)` → `PanelSet` (page, page-frame box per panel via
  `figure_panels.to_page_frame`, matched entries, colour).
  `load_panel_boxes(paper_id)` → `{page: [(label, page box, colour)]}` in one
  joined query; the colour index restarts per figure, cycling six colours.
- `PanelTiles`: a `QListWidget` in icon mode (wrapping tiles, 112 px). The
  tiles go up at once with blank icons; a `_TileWorker` thread renders the
  figure's page **once** at 150 dpi and crops each panel, drawing the frame
  in the panel's colour; crops for a figure no longer shown are dropped.
  Same lifecycle as the reader's figure worker (stop on close/del).
- `OcrView.set_panels(map)` before `set_pages`; `loadResource` passes the
  page's panels to the worker's request; `_render` draws them with
  `draw_panel_boxes(crop, panels, crop_box, page_size)` — **the same pixel box
  and page size the crop was cut by**, so a box lands on its specimen and
  not a few pixels off (the crop is padded 0.5 % beyond the bbox; the boxes
  honour that). A plate the OCR cut into pieces is several crops; a panel is
  drawn on every crop it overlaps, clipped. `refresh_figures()` re-lays the
  document for the toggle, keeping the reader's place.
- Checked against the real thing: 664 Plate I rendered through the reader's
  own crop path with the live boxes — 33 boxes on 33 specimens.

## Tests (`test_panel_tiles.py`, 5)

Tiles go up before any crop and the crops land (one page render per figure,
not per panel); clearing between figures drops a late crop; the drawing maps
boxes through the crop's own frame and skips panels outside the crop; the
reader draws boxes only when given them and stops after the toggle; the box
map is by page with colours cycling per figure and `load_panels` names the
unmatched entries. Full suite **545 passed**.

## Addendum (same day): entries without panels

Most linked figures have caption entries and no panels yet (613 of 696
linked figures carry entries; three papers are split). Those had nowhere in
the app to show their entries. Choosing such a figure now lists them under
the figure list in the same widget (`PanelTiles.show_entries`): one line per
entry — label, description, specimen number when the description does not
already carry it — with the header `Plate 1 — 16 caption entries`.
`paper_service.load_entries(figure_id)`. Two tests.

## Left

- Clicking a tile could scroll the reader to that specimen; today it scrolls
  to the page (the list does) and the box's colour finds it.
- Tiles are only as good as the split; an unmatched entry or a dimmed tile is
  where a reviewer should look. Correction from the app (move a box, relabel)
  is `figure_curation` work not yet wired to the UI.
