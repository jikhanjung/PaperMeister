# PaperMeister Minimal Multi-Source GUI Spec

**Date:** 2026-04-03  
**Status:** Draft  
**Scope:** Minimal GUI design for supporting multiple sources before full canonical unified views exist

## 1. Purpose

PaperMeister is moving toward a multi-source architecture.

That means the GUI can no longer assume that the left navigation panel represents one source tree only.

At the same time, the system is not yet ready for a full canonical unified paper browser because:

- source-to-canonical merge logic is not mature yet
- duplicate reconciliation is still incomplete
- source-specific provenance must remain visible

This document defines the minimum viable GUI direction for multi-source support.

## 2. Core Design Constraint

The GUI must support multiple sources now, without pretending that canonical cross-source paper unification is already solved.

Therefore the design rule is:

**preserve source-specific navigation, and add only lightweight cross-source operational views**

This avoids overpromising a unified paper model before the underlying data model is ready.

## 3. Main UI Principle

The left panel should represent two different concepts separately:

- source-oriented navigation
- corpus-wide operational state views

These should not be collapsed into a single ambiguous tree.

## 4. Recommended Left Panel Structure

The left panel should have two top-level sections:

- `Library`
- `Sources`

## 4.1 `Library` Section

This section should contain virtual views that are safe even without strong canonical merge logic.

Recommended initial nodes:

- `All Files`
- `Pending OCR`
- `Processed`
- `Failed`
- `Recently Added`

These are intentionally operational views, not true canonical paper views.

### Why this is safe

These views do not require PaperMeister to decide that two records from different sources are the same paper.

They are based on current internal file or processing state, which already exists.

## 4.2 `Sources` Section

This section should show each registered source separately.

Examples:

- `Zotero: Personal Library`
- `Directory: /home/user/PDFs`
- `Directory: /mnt/archive/papers`
- `EndNote: Legacy Import`

Each source node should expand into its own native hierarchy:

- Zotero source -> collection tree
- directory source -> folder tree
- EndNote source -> group tree if available, otherwise flat or simple grouped view

### Why this matters

Different sources organize material differently.

Trying to force them into one merged tree would:

- distort user intent
- hide provenance
- create unnecessary UI confusion

## 5. What the Left Panel Should Not Do Yet

The GUI should not yet attempt:

- a fully unified `All Papers` view that implies canonical deduplication is solved
- merged cross-source folder trees
- hiding duplicates by default
- collapsing source-specific metadata differences into one display automatically

These belong to a later phase, after canonical paper modeling is stronger.

## 6. Middle Panel Behavior

The middle panel should remain a list of papers or files filtered by the current left-panel selection.

Recommended behavior by node type:

- `All Files` -> show all currently known paper/file entries
- `Pending OCR` -> show only pending items
- `Processed` -> show processed items
- `Failed` -> show failed items
- `Recently Added` -> show newest items by ingestion time
- source node -> show items belonging to that source
- source subfolder or collection node -> show items within that subtree

At this stage, the middle panel does not need to pretend that every row is a fully canonical paper.

It only needs to be consistent with current filtering behavior.

## 7. Right Panel Behavior

The right panel should focus on detail plus provenance.

Recommended detail sections:

- title
- authors
- year
- journal
- file status
- OCR status
- snippet or extracted text preview
- source provenance

### Provenance display should include

- source name
- source path or collection context
- file origin if known
- metadata origin if known later

Example:

- `Seen in: Zotero / Trilobites / Ordovician`
- `Seen in: Directory /archive/papers/korea`
- `PDF source: local file`

This becomes more important as multi-source overlap grows.

## 8. Minimal Multi-Source UX Goals

The first GUI version should make the following possible:

- user can understand which sources are registered
- user can browse each source in its own structure
- user can see global processing state
- user can process or inspect items without requiring canonical merge
- user can see provenance clearly

This is enough for an initial multi-source transition.

## 9. Interaction Model

The expected user flow is:

1. user adds one or more sources
2. source nodes appear under `Sources`
3. user expands a source and navigates its own hierarchy
4. user can switch to `Library` virtual nodes for operational views
5. selected node filters the middle list
6. selected paper/file shows details and provenance on the right

This keeps the mental model simple:

- left = where or what view
- middle = matching entries
- right = detail and context

## 10. Why a Full Unified View Should Wait

A true unified view requires more than a new tree node.

It requires:

- stronger canonical `Paper` semantics
- source-record versus canonical-paper separation
- deduplication and merge policy
- conflict handling for source metadata disagreements
- stable provenance display after merge

Until these exist, a fully unified paper browser would be misleading.

That is why the minimal GUI should focus on:

- source-first browsing
- operational cross-source views

instead of:

- premature canonical browsing

## 11. Recommended Incremental Implementation

The GUI transition should happen in small steps.

## Step 1

Keep current source-tree behavior, but support multiple top-level sources explicitly.

## Step 2

Add `Library` virtual nodes:

- `All Files`
- `Pending OCR`
- `Processed`
- `Failed`
- `Recently Added`

## Step 3

Ensure middle-panel filtering works for both virtual nodes and source hierarchy nodes.

## Step 4

Improve right-panel detail view with clearer provenance information.

## Step 5

Later, once canonical merge becomes real, introduce true unified paper views separately.

## 12. Future Upgrade Path

After the data model supports canonical paper reconciliation, the GUI can expand with:

- `All Papers`
- `By Author`
- `By Year`
- `Duplicate Candidates`
- `Merged Records`
- source filters applied to canonical views

These should be treated as future canonical corpus views, not part of the initial minimal multi-source GUI.

## 13. Summary

The correct minimal GUI strategy is:

- keep source hierarchies separate
- display them under a `Sources` section
- add only safe operational virtual views under `Library`
- do not fake a canonical unified paper browser too early

This gives PaperMeister a realistic path from today's source-oriented UI toward a future unified corpus interface.
