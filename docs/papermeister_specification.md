# PaperMeister Specification

**Date:** 2026-04-03  
**Status:** Draft  
**Scope:** Post-MVP product direction and execution plan

## 1. Purpose

PaperMeister is no longer just an OCR-backed PDF manager. Its next product goal is to become a **local research corpus platform** that:

- ingests papers from personal sources such as folders and Zotero
- preserves full text and OCR structure as source-of-truth data
- supports reliable retrieval and exploration
- adds derived knowledge layers on top of the corpus
- eventually enables domain-aware research assistant workflows

This specification defines the staged roadmap from the current MVP to that broader system.

## 2. Current Baseline

The current implementation already provides:

- folder import
- Zotero collection sync and paper import
- PDF registration and dedup-related handling
- RunPod Chandra2 OCR
- raw OCR JSON caching
- SQLite + FTS5 full-text search
- PyQt6 GUI
- CLI for import, processing, search, listing, and Zotero operations

In short, the project already has a working ingestion and retrieval foundation.

## 3. Product Principle

The core principle remains:

**Store first, understand later**

This means:

- raw OCR output is preserved
- derived layers must be reproducible from stored source data
- interpretation is additive, not destructive
- advanced intelligence should be built on stable data assets, not replace them

## 4. Product Direction

PaperMeister should evolve in the following order:

1. stabilize the ingestion and retrieval base
2. add a structured corpus layer derived from OCR/layout output
3. add analysis and exploration features on top of the corpus
4. add entity and assertion extraction
5. build research assistant workflows on top of those tools and data layers

This ordering is intentional. Agent behavior is not the next step. Better structure and better derived data are the next step.

## 5. Staged Roadmap

## Phase 1. Foundation Stabilization

### Goal

Make the current MVP operationally reliable enough to support later structured extraction and analysis work.

### Outcomes

- ingestion and OCR flows are predictable
- failures are easier to diagnose and recover from
- search output becomes easier to inspect
- regression risk is reduced through tests

### Scope

- test coverage for critical flows
- OCR exception handling improvements
- search result highlight support
- processing stability checks for larger batches
- reindex and reprocess flow validation

### Out of Scope

- semantic search
- entity extraction
- knowledge graph
- assistant features

## Phase 2. Structured Corpus Layer

### Goal

Convert OCR output from plain searchable text into a reusable structured corpus representation.

### Required Capabilities

- distinguish section headers, captions, body text, and other OCR block types
- preserve block-level and section-level provenance
- expose derived structure without discarding existing passage search

### Expected Outputs

- richer passage metadata
- section-aware or block-aware derived records
- structured text cache or equivalent derived representation per paper

### Why It Matters

This phase is the bridge between “searchable PDF text” and “an analyzable research corpus.”

## Phase 3. Analysis Layer

### Goal

Provide corpus exploration tools that are immediately useful before heavy domain extraction work begins.

### Initial Analysis Features

- word frequency
- unigram, bigram, trigram extraction
- TF-IDF keyword extraction
- keyword comparison by year, collection, or author
- trend summaries across subsets of the corpus

### Higher-Value Extensions

- taxon frequency
- geological time term frequency
- locality and formation extraction candidates
- co-occurrence networks
- author collaboration networks

### Priority Rule

Do not center this phase on tag clouds. Tag clouds can be added as a view, but the primary outputs should be reusable analysis data and reports.

## Phase 4. Entity and Assertion Layer

### Goal

Extract structured domain knowledge from papers as validated assertions rather than loose keywords.

### Target Entity Types

- taxon
- formation
- locality
- stratigraphic interval
- specimen
- paper
- author

### Target Assertion Types

- occurs_in
- found_at
- described_by
- belongs_to
- assigned_to_interval
- synonym_of

### Execution Model

The first version should be semi-automatic:

1. generate high-recall candidates
2. normalize entities
3. validate or review candidates
4. persist confirmed assertions

### Storage Direction

Start with relational tables in SQLite rather than introducing a graph database too early.

## Phase 5. Research Assistant Layer

### Goal

Support question-driven exploration workflows over the corpus and extracted assertions.

### Initial Assistant Pattern

The first assistant should be tool-oriented, not fully autonomous.

Example flow:

1. receive user question
2. search relevant papers
3. gather relevant assertions and passages
4. synthesize a grounded summary
5. cite paper and page evidence

### Non-Goal for Early Versions

- open-ended autonomous looping agent
- always-on persona
- fully unsupervised extraction and reasoning

## 6. Phase-by-Phase Deliverables

## Phase 1 Deliverables

- regression tests for core ingestion and processing paths
- clearer OCR failure states and retry handling
- visible search-term highlighting in search results
- verified behavior for reindex/reprocess commands
- documented operational checklist for batch processing

## Phase 2 Deliverables

- schema changes for richer passage metadata
- parser that derives structure from OCR JSON
- storage of section/caption/body distinctions
- updated search behavior to benefit from structured fields

## Phase 3 Deliverables

- CLI or report generator for corpus statistics
- keyword extraction pipeline
- trend and comparison reports
- optional visualization output formats

## Phase 4 Deliverables

- initial entity extraction pipeline
- normalization rules or resolver stubs
- assertion schema
- review workflow for extracted candidates

## Phase 5 Deliverables

- question-to-report workflow
- citation-grounded output
- tool composition layer for search plus assertion lookup plus summarization

## 7. Detailed Plan for Phase 1

Phase 1 should be treated as the immediate execution plan.

## 7.1 Objectives

- reduce breakage risk in the current MVP
- make debugging easier when OCR or import fails
- improve trust in search output
- prepare the codebase for Phase 2 schema work

## 7.2 Workstreams

### Workstream A. Tests

Add tests for the flows that later phases depend on most.

Target areas:

- database initialization and migration safety
- folder import and duplicate handling
- Zotero import edge cases already addressed in code
- OCR result loading from cache
- text extraction idempotency
- search result generation

Recommended output:

- a minimal but stable pytest suite
- fixtures for sample OCR JSON and small paper records

### Workstream B. OCR and Processing Reliability

Strengthen failure handling around the processing pipeline.

Target areas:

- encrypted or unreadable PDFs
- malformed OCR responses
- missing cached JSON
- partial processing failures
- status transitions between pending, processed, and failed

Recommended output:

- normalized exception paths
- clearer user-facing error messages in GUI and CLI
- explicit retry behavior rules

### Workstream C. Search UX

Make search results easier to trust and inspect.

Target areas:

- highlight matched snippets in GUI detail view
- keep page references obvious
- ensure ranking output remains understandable

Recommended output:

- visible term highlighting in the result detail pane
- consistent snippet formatting between CLI and GUI where practical

### Workstream D. Operational Validation

Verify that current commands and screens behave correctly at batch scale.

Target areas:

- processing many pending files
- retry failed files
- reindex from cache
- reprocess all
- collection-specific CLI processing

Recommended output:

- documented manual validation checklist
- fixes for issues found during that pass

## 7.3 Suggested Execution Order

1. create test scaffolding and fixtures
2. cover DB, ingestion, and text extraction paths first
3. harden OCR and processing error handling
4. implement search highlighting
5. run batch-scale validation and fix defects
6. freeze Phase 1 with a short operational summary

## 7.4 Definition of Done for Phase 1

Phase 1 is complete when:

- core ingestion and OCR-derived indexing flows have automated test coverage
- common failure modes do not leave ambiguous state in the database
- search results are easier to inspect through highlight or equivalent emphasis
- batch processing paths have been exercised and documented
- Phase 2 schema work can start without unresolved reliability concerns

## 8. Recommended Immediate Next Task

If work starts now, the best first task is:

**set up the initial automated test suite for DB initialization, ingestion, OCR cache loading, and text extraction idempotency**

That task has the highest leverage because every later phase depends on those code paths.

## 9. Summary

PaperMeister should evolve from:

**searchable paper archive**

to:

**structured research corpus platform**

and only after that into:

**domain-aware research assistant**

The next correct step is not more agent behavior. The next correct step is a more reliable foundation and a richer structured corpus layer.
