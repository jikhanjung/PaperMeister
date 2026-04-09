# PaperMeister Phase 1 Task Breakdown

**Date:** 2026-04-03  
**Status:** Draft  
**Related:** `docs/papermeister_specification.md`

## 1. Goal

Phase 1 focuses on foundation stabilization.

The purpose of this phase is to make the current MVP reliable enough that later structured corpus work can be added without fighting instability in ingestion, OCR processing, search, or recovery flows.

## 2. Phase 1 Success Criteria

Phase 1 is successful when:

- core ingestion and OCR-derived indexing flows have automated tests
- common failure modes do not leave ambiguous DB state
- search results are easier to inspect through highlighting or equivalent emphasis
- batch processing and recovery paths have been exercised and documented
- the codebase is stable enough to begin Phase 2 schema work

## 3. Workstreams

## Workstream A. Test Foundation

### Objective

Add the minimum automated test suite needed to protect critical behavior.

### Tasks

- choose and install the test runner if not already present
- create a `tests/` directory structure
- add test fixtures for temporary DB setup
- add sample OCR JSON fixtures
- add helper fixtures for sample `Source`, `Folder`, `Paper`, `PaperFile`, and `Passage` records
- document how tests are run locally

### Priority Tests

- DB initialization creates required tables
- DB migration paths do not fail on existing DB state
- folder import registers new PDFs correctly
- duplicate import does not create broken duplicate records
- OCR cache loading path works when JSON exists
- text extraction remains idempotent on reprocessing
- search returns expected papers and passages for basic queries

### Deliverables

- runnable test suite
- fixtures for core models and OCR samples
- short test-running section in project docs or README

## Workstream B. OCR and Processing Reliability

### Objective

Ensure processing failures are visible, recoverable, and consistent.

### Tasks

- review all `pending -> processed -> failed` transitions
- identify unhandled exceptions during OCR and extraction
- handle encrypted or unreadable PDF cases explicitly
- handle malformed or incomplete OCR JSON safely
- verify behavior when OCR cache exists but is unusable
- ensure retry paths reset only the intended state
- verify reprocess paths remain idempotent

### Deliverables

- clearer status transition rules
- improved exception handling
- user-visible error messages in GUI and CLI
- documented retry and recovery behavior

## Workstream C. Search UX Improvement

### Objective

Make search results easier to trust and inspect.

### Tasks

- review current search result rendering in GUI
- add matched-term highlighting to detail view or result snippets
- keep page references visible near matches
- review CLI snippet readability
- ensure highlight logic does not break on special characters or case differences

### Deliverables

- visible highlighting in GUI search display
- clearer snippet rendering
- basic verification for search display edge cases

## Workstream D. Batch and Recovery Validation

### Objective

Validate that the current operational paths behave correctly at realistic usage scale.

### Tasks

- test processing of larger pending batches
- validate `Retry Failed`
- validate `Reindex from Cache`
- validate `Reprocess All`
- validate CLI processing by collection
- confirm progress reporting remains understandable in batch runs
- record observed issues and fix them

### Deliverables

- manual validation checklist
- short operational notes
- bug fixes discovered during validation

## 4. Recommended Execution Order

1. establish the test framework and fixtures
2. cover DB, ingestion, OCR cache, and extraction paths first
3. harden processing error handling
4. improve search highlighting and snippet rendering
5. run batch and recovery validation
6. close remaining defects and publish a short Phase 1 summary

## 5. Suggested Task List

This list is ordered by leverage, not by implementation difficulty.

### P1

- add test framework and first fixtures
- add DB initialization and migration tests
- add folder import tests
- add OCR cache and text extraction idempotency tests

### P2

- normalize processing status transitions
- improve error handling for bad PDFs and bad OCR JSON
- document retry/reprocess behavior

### P3

- implement GUI search highlighting
- verify CLI search output readability
- add tests or manual checks for search display behavior

### P4

- run batch validation scenarios
- fix issues found in retry/reindex/reprocess flows
- write operational checklist

## 6. Risks

- tests may be hard to add cleanly if core code paths are tightly coupled to filesystem or global DB state
- OCR-related logic may depend on external services in ways that need mocking or fixture-based isolation
- GUI highlighting may require careful handling to avoid HTML rendering regressions
- migration coverage may expose assumptions about existing user DB state

## 7. Mitigation Strategy

- prefer fixture-driven tests over network-dependent tests
- isolate OCR cache and extraction logic from live OCR calls
- test GUI display logic with focused rendering helpers where possible
- use temporary DB files or isolated test DB paths

## 8. Definition of Done Checklist

- [ ] test runner and `tests/` structure added
- [ ] DB initialization covered by tests
- [ ] migration behavior covered by tests
- [ ] folder import behavior covered by tests
- [ ] OCR cache loading covered by tests
- [ ] text extraction idempotency covered by tests
- [ ] basic search behavior covered by tests
- [ ] processing failure paths reviewed and hardened
- [ ] bad PDF handling improved
- [ ] malformed OCR JSON handling improved
- [ ] retry/reprocess behavior verified
- [ ] GUI search highlighting implemented
- [ ] CLI search readability checked
- [ ] batch processing validation completed
- [ ] operational checklist written

## 9. Immediate Next Action

The best first concrete task is:

**create the test scaffold and add coverage for DB initialization, folder import, OCR cache loading, and text extraction idempotency**

That work gives the highest confidence return for the least architectural risk.
