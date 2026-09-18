# 106 — P16 Phase 4b: "Process Figures" in the app

**Date:** 2026-09-18
**Scope:** `papermeister/figure_pipeline.py` (new), `figure_client.wait(should_stop)`,
`desktop/windows/figures_window.py` (new), `desktop/windows/main_window.py`,
`desktop/views/paper_list.py`, `desktop/views/source_nav.py`,
`tests/test_figure_pipeline.py`, `tests/test_figures_action.py`
**Follows:** [104](./20260917_104_P16_Client_Detect_And_Lanes.md) (lane scripts),
[105](./20260918_105_P16_Figures_Ride_In_The_OCR_JSON.md) (DB ↔ JSON)

## What

The four figure stages — ① assemble → ①′ detect → ② link → ③ panels — that
until now only ran through four lane scripts, one stage across many papers,
now run **one paper at a time through all four** from the app:

- **Right-click a paper** (status processed / review / done, with a PDF) →
  `Process Figures`. Right-click a **collection** → `Process Figures (folder)`;
  the **source root** → `Process Figures (all)`.
- Without the wrapper server configured (`ocr_backend != 'wrapper'` or no
  `ocr_pod_url`), the action is **shown disabled with the reason as tooltip**
  rather than hidden — a user outside the institution network should learn
  why, and still sees figures found elsewhere (105) in the Text tab.
- A **progress window** (`FiguresWindow`, modelled on the References window)
  shows the paper in flight, the stage, jobs submitted, the server worker's
  progress, and — importantly — **a paused worker as "Waiting"** (subscription
  login / usage limit), so a 20-minute hold does not look like a hang.
  Cancel drops the queue and stops the paper in flight at its next step.

## How it is put together

`figure_pipeline.process_file(pf, client, notify, progress, should_stop, stages)`
is the chain. Each stage asks its module what is due by **the keys on the
rows** (`detect_key`, `link_key`, `panel_key`, plus `panel_entries_digest`
for the rematch case) and returns without a server call when nothing is —
so a paper stopped halfway resumes where it stopped, and one whose captions
a person fixed re-runs only the panels. Every stage that touched the DB ends
with `figure_share.write_to_cache(pf)` (105), so the cache JSON — and the
Zotero sibling, when opted in — carries the result.

- `_assemble` also imports the cache JSON's `figures` block first when the
  file has no rows yet (a second machine's first look).
- `_run()` submits and waits; the `on_progress` callback turns the job's
  `worker` block into `notify('wait', …)` when `paused_reason` is set and
  `notify('info', …)` otherwise. `FigureClient.wait()` grew a `should_stop`
  and sleeps in 1-second steps so cancel is felt within a second, not a
  poll interval.
- A cancel raises `Cancelled` **between** steps; nothing half-written. The
  job already on the server finishes there and the lanes' `--collect`
  picks it up later — the same job key, the same result digest logic.
- `PipelineReport` per paper: a `StageReport(ran, due, written, failed,
  note)` per stage, `summary()` like `assemble 24/24, link 24/24, panels 3/3`.

In the main window it mirrors the references flow: a serial queue
(`_figures_queue`), one `BackgroundTask` in flight (`_figures_task`), a
cancel flag the worker polls (`_figures_cancel`), `_drain_figures_queue()`
after each paper. **One paper at a time** is the rule, not a limitation:
the server is serial, and the pipeline writes the DB from its own thread —
it must not overlap another writer. The Text tab is repainted when the
finished paper is the one on screen. Folder/all scope asks once (N papers,
minutes each) and orders the queue by the visible list.

## Why one paper through all stages, and not the lanes

The lanes exist for the pilot: run a stage across 100 papers, gate it,
next stage. A user with one new paper wants the reverse — that paper,
done. Both call the same `figure_detect` / `figure_link` / `figure_panels`
code; the pipeline adds only the order and the skip-by-key. The lanes stay
for batch work (`--no-wait` + `--collect`), and the two never fight over a
row: the same key means the same job, and a reply already applied is
"unchanged" to whichever reads it second.

## Tests

- `test_figure_pipeline.py` (4): a plate paper through all stages with a
  `FakeClient` (link and panels both submitted, entries and panels land,
  JSON carries them; second run submits nothing); cancel during the first
  submit leaves the caption empty and the paper resumable; a server error
  stops before panels; no cache → nothing runs; `server_hint()` names
  the missing setting.
- `test_figures_action.py` (5, ui): the action appears for a processed
  paper, is disabled with the hint without a server, absent for pending;
  the window reads a paused worker as Waiting and counts ok/failed;
  cancel fires the signal and the log says how many were dropped.

Full suite: **537 passed**.

## Not done here

- No **live** run yet from the app — the pilot's pending server jobs
  (link: 7 detect-touched papers + 1191/3853; panels: 112) are still to be
  collected with the lanes. The first app run should be a paper whose
  stages are all done (should say "nothing to do", no server call), then
  one new paper.
- The Process window's OCR flow does not chain into figures; figures
  remain an explicit action (decision 2026-09-14: request-scoped).
- Beta pre-release (`v0.2.0-beta.1`) after the live check.
