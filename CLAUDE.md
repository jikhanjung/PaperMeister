# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 세션 시작 시

**반드시 [`HANDOFF.md`](./HANDOFF.md)를 먼저 읽어 현재 진행 상황을 파악하세요.**
작업 종료 시에는 HANDOFF.md의 내용을 최신 상태로 업데이트하세요.

## devlog 작성 규칙

개발 관련 문서는 `devlog/` 디렉토리에 작성한다.

| 패턴 | 용도 | 예시 |
|------|------|------|
| `YYYYMMDD_P99_title.md` | **계획 문서** (구현 전 설계/계획) | `20260330_P01_MVP_Architecture.md` |
| `YYYYMMDD_999_title.md` | **구현 기록** (완료된 작업 정리) | `20260330_001_MVP_Initial_Implementation.md` |

- `P` 접두사 = Plan, 숫자 접두사 = 완료된 구현 기록
- 날짜 내 순번으로 정렬 (P01, P02... / 001, 002...)

## Project Overview

PaperMeister transforms a user's academic paper (PDF) collection into a searchable knowledge base.

**Core pipeline:** Source → Ingestion → OCR → Metadata Extraction → DB → Search

**Key principle:** "Store first, understand later" — fulltext is the source of truth; all extractions are derived layers.

## Commands

```bash
pip install -r requirements.txt
python main.py
```

## Tech Stack

- **GUI:** PyQt6
- **DB:** SQLite with FTS5 — `~/.papermeister/papermeister.db`
- **ORM:** Peewee 4.x (`peewee.DatabaseProxy` + `peewee.SqliteDatabase`)
- **PDF:** PyMuPDF (fitz) — 메타데이터 추출 + 페이지 렌더링
- **OCR:** RunPod serverless (Chandra2-vllm) — `.env`에 API 키 필요
- **Dependencies:** Pillow, requests, python-dotenv

## Data Model

```
Source (directory|zotero) → Folder (계층구조) → Paper → PaperFile (hash, status)
                                                     → Author (name, order)
                                                     → Passage (page, text) → passage_fts (FTS5)
```

## Architecture Notes

- 텍스트 추출은 항상 RunPod OCR 사용 (텍스트 레이어 유무 불문, 일관성 위해). PyMuPDF는 메타데이터만.
- Import 2단계: ScanWorker(폴더 구조 + PaperFile 생성, 빠름) → ProcessWorker(OCR, 느림)
- Hash-based deduplication (SHA256) at ingestion
- `PaperFile.status`: `pending` → `processed` / `failed`
- FTS5 `passage_fts`: title(×10), authors(×5), text(×1) BM25 가중치
- UI는 QThread로 비동기 처리, DB는 peewee thread-local 연결
- OCR health 체크: `ensure_workers_ready()`로 세션당 한 번만 수행
- `database.py`의 `_migrate()`가 기존 DB에 새 컬럼 자동 추가

## Future Phases

- **Phase 2:** Hybrid search (BM25 + embeddings), LLM query interpretation
- **Phase 3:** Entity extraction (taxon, locality), relation extraction, Zotero sync-back
