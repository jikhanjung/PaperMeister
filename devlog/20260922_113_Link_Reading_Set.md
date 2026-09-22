# 113 — The caption stage reads the neighbourhood first

**Date:** 2026-09-22
**Scope:** `papermeister/figure_link.py` (`reading_set`, `reading_tier`, `reading_digest`,
`workspace_for`, `known_caption_pages`, `items_from_replies` matching), `scripts/link_figures.py`,
`papermeister/figure_pipeline.py`, `papermeister/figure_prompts/link.md`, tests

## The measurement that led here

Two experiments today (HANDOFF): reasoning effort `medium` was 9 % faster
than `high` with the same answers; the prompt telling the model to read
hinted pages first changed nothing — Bruton 2004 (49 pages) was read whole
both times, 916 s both times, and Barrande's Pl. 2B and Pl. 3 read all 231
pages with the hint right there. A 5-entry plate cost 188 s. The fixed cost
of an item is the model's reading, and an instruction does not stop a model
that has the whole paper in front of it.

## What changed

The model no longer has the whole paper in front of it on the first try.
The caption is almost always close by, so the workspace an item gets is a
**reading set** — and each failed attempt widens the next one:

| tier (= attempts so far) | pages |
|---|---|
| 0 | the figure's page ±2; every page the rule saw a plate explanation on; the block of up to 8 pages before a run of consecutive plates; and the pages where this paper's already-linked figures were explained (its habit) |
| 1 | tier 0, plus every page with a numbered caption and every page mentioning the figure's designation ("Pl. 3" / "Pl. III", "Fig. 15", "Tafel IV", "табл. 3", "圖版 3") |
| 2 | the whole text |

A set that would be 60 % of the paper or more is not worth it and the whole
text goes instead (small papers). On the pilot's monographs tier 0 is 21–31
pages of 218–291; a 49-page paper stays whole.

## How it stays consistent

- The full workspace is still uploaded once under the text's digest. A
  reading set is uploaded as its own small workspace under
  `reading_digest(pages, only)` — the server's format unchanged, nothing
  server-side to do. The request's `ocr_digest` and its item keys carry
  that digest; `reading_pages` on the request says which pages, and
  `workspace_for(pf, pages, request)` builds what to upload.
- The row's `link_key` keeps the **full** text's digest: the reading set is
  how the answer was found, not what the answer is about.
- Collect matches replies by file and prompt version, not by digest — a
  reading-set digest depends on what the paper's other rows knew at submit
  time (`known_caption_pages`), which a collect in between changes. The
  text is checked where it matters: `validate_link_result` reads the
  caption off the current pages.
- The prompt tells the model the workspace may hold only the pages selected
  for the job and that a missing page number is deliberate.

Tests: tiers widen with attempts and follow the paper's habit; the request
names its pages and digest, the whole-text request does not; the block
before a plate run; roman/arabic designation forms. **569 passed**.

## Next

The 1189/1190 run in flight was submitted under the previous prompt
version; collect it with that version's prompt file (the keys carry the
version), then re-run one big paper with the reading set to measure.
