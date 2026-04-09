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
- **OCR:** RunPod serverless (Chandra2-vllm) — Preferences에서 API 키 설정
- **Zotero:** pyzotero — Preferences에서 user_id + api_key 설정
- **Settings:** `~/.papermeister/preferences.json` (RunPod, Zotero 자격증명)
- **LLM 서지 추출:** `claude -p` (Haiku 텍스트, Sonnet vision) — Max 플랜 사용량 차감
- **Dependencies:** Pillow, requests, pyzotero

## Data Model

```
Source (directory|zotero) → Folder (계층구조, zotero_key) → Paper → PaperFile (hash, status, zotero_key)
                                                                 → Author (name, order)
                                                                 → Passage (page, text) → passage_fts (FTS5)
                                                                 → PaperBiblio (LLM 추출 서지정보, source 필드로 모델 구분)
```

## Architecture Notes

- 텍스트 추출은 항상 RunPod OCR 사용 (텍스트 레이어 유무 불문, 일관성 위해). PyMuPDF는 메타데이터만.
- Import 2단계: ScanWorker(폴더 구조 + PaperFile 생성, 빠름) → ProcessWorker(OCR, 느림)
- Hash-based deduplication (SHA256) at ingestion. Zotero는 zotero_key 기반 dedup.
- `PaperFile.status`: `pending` → `processed` / `failed`. PaperFile 없으면 `no PDF`.
- FTS5 `passage_fts`: title(×10), authors(×5), text(×1) BM25 가중치
- UI는 QThread로 비동기 처리, DB는 peewee thread-local 연결
- OCR health 체크: `ensure_workers_ready()`로 세션당 한 번만 수행
- OCR 병렬 처리: `get_worker_status()`로 idle worker 수 확인 → `ThreadPoolExecutor`로 병렬 제출
- `database.py`의 `_migrate()`가 기존 DB에 새 컬럼/인덱스 변경 자동 적용
- Zotero: 시작 시 컬렉션 자동 동기화, 컬렉션 클릭 시 아이템 fetch, PDF는 OCR 시점에만 임시 다운로드
- 설정: `~/.papermeister/preferences.json` (RunPod, Zotero). `.env` 사용하지 않음.
- OCR JSON → Zotero 자동 업로드: `zotero_upload_ocr_json` pref로 opt-in (기본 OFF)
- Zotero attachment sync: 모든 타입(PDF+JSON) 수집, JSON은 status='processed'로 자동 설정
- LLM 서지 추출: `PaperBiblio` 테이블에 비파괴 보관 (source 필드로 모델/버전 구분)
  - 텍스트 추출: Haiku (`scripts/extract_biblio.py`). needs_visual_review 자가 보고
  - Vision pass: Sonnet (`scripts/extract_biblio_vision.py`). CJK/표지/TOC에 필수
  - Standalone promote: `scripts/promote_standalone.py` (confidence=high만 자동)
  - In-place update: `scripts/update_promoted_items.py` (itemType 변경 시 template 재생성)
- CJK 저자 이름 분리: 4글자→2/2(일본), 3글자→1/2(한국)

## Scripts (scripts/ 디렉토리)

| 스크립트 | 용도 |
|---------|------|
| `resync_zotero.py` | Zotero DB 초기화 + 전체 재동기화 |
| `update_hashes.py` | NAS storage에서 PDF hash 계산 + OCR 캐시 매칭 |
| `upload_ocr_json.py` | OCR JSON을 Zotero sibling attachment로 일괄 업로드 |
| `build_eval_set.py` | 서지 추출 평가셋 구축 (stratified sampling) |
| `run_baseline.py` | 정규식 baseline 평가 |
| `run_haiku_eval.py` | LLM 서지 추출 평가 (--model 지정 가능) |
| `extract_biblio.py` | 본격 LLM 서지 추출 (--scope, --paper-ids) |
| `extract_biblio_vision.py` | Vision pass 서지 추출 (PyMuPDF 렌더 + Claude vision) |
| `promote_standalone.py` | Standalone PDF → Zotero parent item 생성 |
| `update_promoted_items.py` | 기존 Zotero parent item in-place 수정 |
| `preview_standalone_biblio.py` | Standalone PDF 추출 결과 미리보기 (read-only) |

## Future Phases

- **Phase 1.5 (진행 중):** LLM 서지정보 추출 → Zotero 메타데이터 보강
- **Phase 2:** Hybrid search (BM25 + embeddings), LLM query interpretation
- **Phase 3:** Entity extraction (taxon, locality), relation extraction
