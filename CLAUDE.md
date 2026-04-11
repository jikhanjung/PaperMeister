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

python -m desktop   # 신규 desktop 앱 (P07~P09, 현재 개발 중)
python main.py      # 기존 PyQt6 GUI (동결, 안정)
python cli.py       # CLI — GUI 없이 import/process/search/list/show/config/zotero
```

## Tech Stack

- **GUI:** PyQt6
  - 기존 `papermeister/ui/` — **동결**. 신규 개발 없음. `main.py` 엔트리. Process/Preferences 다이얼로그는 새 desktop 앱에서 재사용 중
  - 신규 `desktop/` — 4-layer (views/services/components/workers), 다크 테마 design tokens, `python -m desktop` 엔트리
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
- FTS5 `passage_fts`: title(×10), authors(×5), text(×1) BM25 가중치. 단 passage 단위 인덱스라 title 가중치는 passage 내부에서만 작용 — document-level title boost는 미구현 (Phase 5 과제)
- `papermeister/search.py::search()`: `limit` 파라미터는 **distinct paper 수** (2026-04-12 이전엔 passage row 수였음). FTS5 `bm25()`가 aggregate 컨텍스트에서 호출 불가한 제약 때문에 SQL `GROUP BY` 대신 Python dict dedupe로 처리. `max_passages=200_000` 안전 상한
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

## Desktop 앱 구조 (`desktop/`)

- **Entry point**: `python -m desktop` → `desktop/__main__.py` → `desktop.app.main()`
- **4-layer**:
  - `desktop/views/` — top-level screens (source_nav, paper_list, detail_panel)
  - `desktop/services/` — DB/business adapter (paper_service, library, source_service, biblio_service, **search_service**)
  - `desktop/components/` — reusable atoms (sidebar/Rail, search_bar, status_bar, status_badge)
  - `desktop/workers/` — background tasks (QThread)
  - `desktop/windows/main_window.py` — Rail + SourceNav + PaperList + DetailPanel 조립
  - `desktop/theme/` — design tokens (`tokens.py`), QSS generator (`qss.py`), SVG icons + runtime tinting loader (`icons.py`)
- **Rail** (좌측 아이콘 바): Library/Search는 **checkable 모드** → `section_changed` 시그널, Process/Settings는 **one-shot 액션** → `action_triggered` 시그널. Process/Settings는 **동결된 `papermeister/ui/process_window.ProcessWindow` / `preferences_dialog.PreferencesDialog`를 재사용**
- **SourceNav**: `QTabWidget` — 각 Source마다 탭 하나 (현재 Zotero 하나). 각 탭 내부는 단일 트리에 상단=Library 필터, 하단=hierarchical 컬렉션
- **DetailPanel**: `QWidget` (not QScrollArea) + 내부 `QTabWidget#DetailTabs`. 탭 3개 — **Metadata / Biblio / OCR**. 각 탭 독립 스크롤, 논문 전환 시 직전 탭 복원. Stub 배너는 탭바 위에 고정
- **OCR 탭**: `papermeister.biblio.load_ocr_pages()`로 `~/.papermeister/ocr_json/{hash}.json` 페치 → `_sanitize_ocr_markdown()` 적용 → `QTextBrowser.setMarkdown()` 렌더
  - **Sanitizer 필수**: Chandra2 원본을 그대로 `setMarkdown()`에 넘기면 `-qt-list-indent` 누적으로 "텍스트가 계속 오른쪽으로 밀리는" 버그. 원인은 (a) 4+ leading space → indented code block, (b) 줄 시작 `숫자.` → ordered list, (c) 레퍼런스의 바 볼륨 번호(`88.`, `158.`) → 빈 OL이 인접하면 Qt가 nested로 해석해서 indent가 누적. Sanitizer가 모든 줄 `lstrip()` + `^(\d+)\.` regex를 backslash escape로 차단
- **SVG 아이콘**: `desktop/theme/icons/*.svg`는 `stroke="currentColor"`로 작성하고 `icons.rail_icon()` 헬퍼가 런타임에 색을 치환해서 3-state QIcon(idle/checked/hover) 생성. 다크/라이트 테마 스왑도 같은 메커니즘으로 확장 가능
- **QSS**: `desktop/theme/qss.py::build_stylesheet(colors)`가 `desktop/theme/tokens.py::COLORS_DARK`를 받아 풀 스타일시트 생성. QTree branch chevron SVG 경로는 `_icon_url()`이 `Path.as_posix()`로 Windows forward-slash 경로 주입

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
