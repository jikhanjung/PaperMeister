# PaperMeister PRD (Product Requirements Document)

## 1. Overview

PaperMeister is a system that transforms a user's paper (PDF) collection into a searchable knowledge base.

Core idea:
- Ingest papers from sources (Zotero, directories)
- Extract full text via OCR/layout analysis
- Build internal bibliographic + fulltext database
- Enable full-text (inverted index) search

---

## 2. Goals

### Primary Goals
- Convert PDF collections into structured, searchable data
- Provide reliable full-text search across papers
- Minimize manual metadata entry

### Non-Goals (MVP)
- Advanced semantic reasoning
- Full automation of knowledge extraction
- Real-time interactive latency optimization

---

## 3. User Scenarios

### Scenario 1: Import from Zotero
User connects Zotero → Papers are ingested → OCR → searchable

### Scenario 2: Import from Folder
User selects directory → PDFs scanned → processed → searchable

### Scenario 3: Search
User searches: "Furongian trilobite Guizhou"
→ relevant papers + passages returned

---

## 4. System Architecture

### Pipeline

Source → Ingestion → OCR → Metadata Extraction → DB → Search

---

## 5. Functional Requirements

## 5.1 Source Integration

### Inputs
- Zotero library
- Local directories

### Features
- Scan and detect PDFs
- Track source origin
- Avoid duplicate processing

---

## 5.2 PDF Ingestion

### Features
- Register PDF in system
- Generate file hash
- Assign internal file_id
- Queue for processing

---

## 5.3 OCR & Layout Processing

### Using Runpod (Chandra2)

### Features
- Page batching
- Adaptive batching (payload-aware)
- Store raw OCR JSON

### Outputs
- Page text
- Block structure
- Captions
- Page mapping

---

## 5.4 Metadata Extraction

### Extract
- Title
- Authors
- Year
- Journal
- DOI (if available)

### Storage
- papers table
- authors table
- file linkage

---

## 5.5 Fulltext Storage

### Structure
- Passage-level storage
- Page number
- Section info (if available)

---

## 5.6 Search (MVP Core)

### Type
- Full-text search (BM25 / inverted index)

### Scope
- Title
- Authors
- Body text
- Captions

### Output
- Matching papers
- Matching passages
- Page references

---

## 6. Data Model (Minimal)

### papers
- id
- title
- year
- journal
- doi

### authors
- paper_id
- name
- order

### files
- file_id
- paper_id
- path
- hash

### passages
- passage_id
- paper_id
- page
- text

---

## 7. Non-Functional Requirements

### Performance
- Batch OCR processing
- Async job queue

### Reliability
- Retry failed OCR jobs
- Track processing state

### Scalability
- Incremental ingestion
- No need for full rebuild

---

## 8. Future Extensions

### Phase 2
- Hybrid search (BM25 + embedding)
- Query interpretation (LLM)
- Deduplication improvement

### Phase 3
- Entity extraction (taxon, locality)
- Relation extraction
- Zotero sync back

---

## 9. MVP Definition

PaperMeister MVP is complete when:

- PDFs can be ingested from Zotero/folder
- OCR results are stored
- Metadata is extracted
- Full-text search works reliably

---

## 10. Key Principle

"Store first, understand later"

- Preserve fulltext as source of truth
- All extractions are derived layers

---

