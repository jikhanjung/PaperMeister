# PaperMeister Data Model Revision Spec

**Date:** 2026-04-03  
**Status:** Draft  
**Scope:** Revision of the data model for multi-source, sync-centric architecture

## 1. Purpose

The current PaperMeister data model was sufficient for the MVP stage, especially while the system was centered on folder import, Zotero import, OCR, and full-text search.

However, the next architecture requires support for:

- multiple source systems at the same time
- source-aware synchronization
- conservative deduplication and canonical merge
- separation between external records and internal corpus records
- future support for bibliographic-only systems such as EndNote exports

This document defines the recommended data model direction.

## 2. Current Model and Its Limitation

The current core model is roughly:

- `Source`
- `Folder`
- `Paper`
- `Author`
- `PaperFile`
- `Passage`

This model worked because the project was still close to the import pipeline:

- `Source` represented Zotero or a directory
- `Folder` represented either a filesystem folder or a Zotero collection
- `Paper` represented the paper record
- `PaperFile` represented the file
- `Passage` represented extracted text

The limitation is that source-specific information is starting to leak into canonical entities.

Examples:

- `Paper.zotero_key`
- `PaperFile.zotero_key`

This is manageable for a Zotero-heavy MVP, but it does not scale cleanly once the system needs to support:

- EndNote-like bibliographic records
- directory-only file sources
- multiple sources describing the same paper
- sync snapshot tracking
- source record lifecycle management

## 3. Revision Goal

The revised model should enforce three levels clearly:

1. external source state
2. canonical paper and file entities
3. derived corpus layers built by PaperMeister

In other words, the model must distinguish:

- what was observed from an external system
- what PaperMeister believes is the canonical paper
- what internal text and knowledge layers were generated from that paper

## 4. Revision Principles

## 4.1 Separate Source Records from Canonical Papers

External records should not be treated as if they are the same thing as canonical internal papers.

A Zotero item, an EndNote record, and a directory-discovered PDF are source observations.
They may map to one canonical `Paper`, but they are not themselves the canonical paper.

## 4.2 Separate Bibliographic Records from File Records

Metadata and files are related but not identical.

This matters because some sources are:

- metadata-rich but file-poor
- file-rich but metadata-poor
- mixed

The model must support these cases cleanly.

## 4.3 Keep Derived Corpus Data Attached to Canonical Entities

OCR outputs, passages, structured text, and later assertions should be attached to canonical `Paper` or `PaperFile` records, not tied directly to raw source-system records.

## 4.4 Preserve Provenance

The model must preserve:

- where a paper came from
- which external record described it
- which external file or attachment supplied the PDF
- which metadata source is currently preferred

## 5. Recommended Core Entities

The following entities are recommended as the next stable model direction.

## 5.1 `Source`

Represents one external source system registered by the user.

Examples:

- one Zotero library
- one EndNote import
- one local directory
- one watched archive folder

### Recommended fields

- `id`
- `name`
- `source_type`
- `source_class`
- `path` or equivalent source locator
- `config_json`
- `sync_status`
- `last_synced_at`
- `created_at`
- `updated_at`

### Notes

The current `Source` table can evolve rather than be replaced.

Recommended categories:

- `source_type`: `zotero`, `endnote`, `directory`, `ris`, `bibtex`
- `source_class`: `hybrid`, `bibliographic`, `file`

## 5.2 `Folder` or Equivalent Hierarchy Node

The current `Folder` abstraction should not be removed immediately.

It is still useful as a source-specific hierarchy container:

- filesystem directory
- Zotero collection
- future source-specific group node

### Recommended role change

`Folder` should be treated less as the defining location of a `Paper`, and more as:

- organizational metadata
- browsing hierarchy
- provenance context

This is important because one canonical paper may later be linked to multiple source contexts.

## 5.3 `SourceRecord`

Represents an external bibliographic or logical record observed from a source.

Examples:

- Zotero parent item
- EndNote bibliographic record
- RIS entry
- inferred directory-level discovered paper record if needed

### Recommended fields

- `id`
- `source_id`
- `external_id`
- `record_type`
- `folder_id` nullable
- `title`
- `year`
- `journal`
- `doi`
- `metadata_json`
- `raw_snapshot_json`
- `metadata_fingerprint`
- `first_seen_at`
- `last_seen_at`
- `is_deleted`
- `created_at`
- `updated_at`

### Why it matters

This table is necessary for:

- sync diffing
- preserving source-native identifiers
- tracking external lifecycle separately from canonical merge state

## 5.4 `SourceFile`

Represents a file or attachment known by an external source.

Examples:

- Zotero attachment
- scanned local PDF in a directory
- future linked PDF from an EndNote-derived import flow

### Recommended fields

- `id`
- `source_id`
- `source_record_id` nullable
- `external_file_id`
- `folder_id` nullable
- `path_or_uri`
- `filename`
- `mime_type`
- `file_hash`
- `file_size`
- `is_available`
- `metadata_json`
- `first_seen_at`
- `last_seen_at`
- `is_deleted`
- `created_at`
- `updated_at`

### Why it matters

This allows PaperMeister to represent how the external source sees the file, without forcing source-specific file identifiers into canonical file tables.

## 5.5 `Paper`

Represents the canonical internal paper entity.

This is the paper that PaperMeister searches, OCRs, enriches, and later analyzes.

### Recommended fields

- `id`
- `canonical_title`
- `canonical_year`
- `canonical_journal`
- `canonical_doi`
- `preferred_metadata_source_record_id` nullable
- `merge_status`
- `created_at`
- `updated_at`

### Notes

`Paper` should no longer directly store source-native identifiers such as `zotero_key`.

Those belong to source-layer tables.

## 5.6 `Author`

The current `Author` entity can remain associated with `Paper`.

However, in future revisions it may be useful to track provenance of author assignments if different sources disagree.

For now, it is acceptable to keep:

- `paper_id`
- `name`
- `order`

## 5.7 `PaperSourceLink`

Represents the relationship between a canonical `Paper` and a `SourceRecord`.

This is one of the most important additions.

### Recommended fields

- `id`
- `paper_id`
- `source_record_id`
- `link_type`
- `confidence`
- `is_primary`
- `created_at`
- `updated_at`

### Suggested `link_type` values

- `exact`
- `merged`
- `candidate`
- `manual`

### Why it matters

This table allows:

- one paper to be linked to multiple source records
- provenance preservation
- candidate merge states without forcing premature canonical merge

## 5.8 `PaperFile`

Represents the canonical internal file associated with a paper.

This is the file entity PaperMeister uses for OCR, caching, and text extraction.

### Recommended fields

- `id`
- `paper_id`
- `source_file_id` nullable
- `storage_path`
- `original_path`
- `hash`
- `mime_type`
- `status`
- `ocr_status`
- `processed_at`
- `created_at`
- `updated_at`

### Notes

The current `PaperFile` model can evolve toward this structure.

`PaperFile` should not permanently hold source-native file IDs such as `zotero_key`.

That information belongs in `SourceFile`.

## 5.9 `Passage`

The `Passage` entity remains valid, but it should become more expressive.

### Recommended additions

- `paper_file_id`
- `page`
- `text`
- `block_type`
- `section_title`
- `source_kind`

### Example `source_kind`

- `body`
- `caption`
- `header`
- `footer`

### Why it matters

This supports the structured corpus work planned for Phase 2.

## 6. Relationship Summary

The intended relationship model is:

- one `Source` has many `SourceRecord`
- one `Source` has many `SourceFile`
- one `Folder` belongs to one `Source`
- one `SourceRecord` may belong to one `Folder`
- one `SourceFile` may belong to one `Folder`
- one `SourceFile` may belong to one `SourceRecord`
- one `Paper` has many `PaperSourceLink`
- one `PaperSourceLink` links one `Paper` to one `SourceRecord`
- one `Paper` has many `PaperFile`
- one `PaperFile` may originate from one `SourceFile`
- one `PaperFile` has many `Passage`

This creates a clean separation between source-layer observations and canonical-layer entities.

## 7. Source-Specific Fields to Phase Out

The following current design pattern should be phased out:

- source-native IDs stored directly on canonical entities

Immediate examples:

- `Paper.zotero_key`
- `PaperFile.zotero_key`

### Replacement strategy

- move external IDs into `SourceRecord` and `SourceFile`
- use `PaperSourceLink` and `source_file_id` to connect canonical entities to source-layer records

This will prevent future schema pollution when additional source types are introduced.

## 8. Sync-Supporting Fields

The revised model should support sync as a first-class capability.

Fields that matter across source-layer tables:

- `first_seen_at`
- `last_seen_at`
- `last_synced_at`
- `sync_status`
- `is_deleted`
- `raw_snapshot_json`
- `metadata_fingerprint`

These fields support:

- change detection
- deletion tombstones
- incremental sync logic
- stable reprocessing decisions

## 9. Metadata Trust and Priority

The model should support future metadata priority policy.

Recommended default trust order:

1. trusted external bibliographic or hybrid source
2. other linked external source metadata
3. embedded PDF metadata
4. OCR-derived metadata guesses

To support this, `Paper` should carry:

- canonical fields
- a reference to the preferred metadata source

This avoids confusing external observations with internal canonical decisions.

## 10. Migration Strategy

This revision should not be implemented as a destructive all-at-once rewrite.

Recommended migration order:

1. keep existing tables working
2. add `SourceRecord`
3. add `SourceFile`
4. add `PaperSourceLink`
5. extend `PaperFile` with source-file linkage
6. extend `Passage` with richer provenance fields
7. update Zotero import to write both old-compatible and new structures temporarily
8. update directory import to write new source/file structures
9. reduce reliance on `Paper.zotero_key` and `PaperFile.zotero_key`
10. remove direct dependence on source-specific canonical fields after transition

This staged approach reduces migration risk.

## 11. Minimum Useful Revision

If the full revision is too large to implement immediately, the minimum high-value revision is:

- extend `Source` with sync metadata
- add `SourceRecord`
- add `PaperSourceLink`
- add source-file linkage concept to `PaperFile`
- extend `Passage` with `paper_file_id` and basic block metadata

This smaller revision already creates the foundation for:

- multi-source support
- source-aware sync
- future structured corpus work

## 12. Expected Benefits

This revised model will make it possible to:

- support Zotero, EndNote-like records, and directory archives together
- keep one canonical paper even when multiple sources describe it
- keep metadata provenance visible
- track sync state cleanly
- trigger OCR and corpus updates from source changes
- move into Phase 2 structured corpus work without source-schema confusion

## 13. Summary

The essential change is not just adding new tables.

The essential change is changing what the center of the model means.

Current tendency:

- imported source record is treated almost like the paper itself

Revised model:

- source record is a source observation
- canonical `Paper` is the internal paper entity
- canonical `PaperFile` is the internal file entity
- OCR, passages, structured corpus, and later assertions attach to canonical entities

That is the correct direction for a multi-source, sync-centric PaperMeister architecture.
