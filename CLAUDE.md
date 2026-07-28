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
| `YYYYMMDD_R99_title.md` | **리뷰/감사 문서** (코드품질·보안 등 횡단 검토) | `20260723_R01_Code_Quality_Guide_Adoption.md` |
| `YYYYMMDD_999_title.md` | **구현 기록** (완료된 작업 정리) | `20260330_001_MVP_Initial_Implementation.md` |

- `P` 접두사 = Plan, `R` 접두사 = Review/audit(횡단 검토·감사), 숫자 접두사 = 완료된 구현 기록
- 날짜 내 순번으로 정렬 (P01, P02... / R01, R02... / 001, 002...)

## Project Overview

PaperMeister transforms a user's academic paper (PDF) collection into a searchable knowledge base.

**Core pipeline:** Source → Ingestion → OCR → Metadata Extraction → DB → Search

**Key principle:** "Store first, understand later" — fulltext is the source of truth; all extractions are derived layers.

## Commands

```bash
pip install -r requirements.txt                  # Python 3.12+
pip install --require-hashes -r requirements.lock  # CI와 동일한 재현 환경

python -m desktop   # 신규 desktop 앱 (P07~P09, 현재 개발 중)
python main.py      # 기존 PyQt6 GUI (동결, 안정)
python cli.py       # CLI — GUI 없이 import/process/search/list/show/config/zotero
```

### 개발 (P15 이후 상시)

```bash
pip install -r requirements-dev.txt
pytest                  # markers: unit / ui / integration. Qt는 conftest가 offscreen 처리
ruff check .            # 린트 (게이팅)
mypy papermeister/references.py papermeister/search.py papermeister/biblio.py
make lock / make lock-check / make lock-upgrade   # 의존성 lock
cd docs/manual && make html                       # Sphinx 매뉴얼 로컬 빌드
```

**mypy는 의존성이 설치돼 있어야 의미가 있다** — 없으면 `ignore_missing_imports`로 peewee가
`Any`가 되어 ORM 코드가 사실상 미검사된다(CI의 lint 잡이 `requirements.lock`을 설치하는 이유).
peewee가 생성하는 `id`/`<fk>_id`는 `models.py`에 `TYPE_CHECKING`으로 선언돼 있다.
**mypy가 `x_id` 대신 `x`를 제안해도 따르지 말 것** — 통과는 하지만 행마다 관계 fetch가 붙는다.

## Tech Stack

- **GUI:** PyQt6
  - 기존 `papermeister/ui/` — **동결**. 신규 개발 없음. `main.py` 엔트리. Process/Preferences 다이얼로그는 새 desktop 앱에서 재사용 중
  - 신규 `desktop/` — 4-layer (views/services/components/workers), 다크 테마 design tokens, `python -m desktop` 엔트리
- **DB:** SQLite with FTS5 — `~/PaleoBytes/PaperMeister/papermeister.db`
- **ORM:** Peewee 4.x (`peewee.DatabaseProxy` + `peewee.SqliteDatabase`)
- **PDF:** PyMuPDF (fitz) — 메타데이터 추출 + 페이지 렌더링
- **OCR:** RunPod serverless (Chandra2-vllm) — Preferences에서 API 키 설정
- **Zotero:** pyzotero — Preferences에서 user_id + api_key 설정
- **Settings:** OS 설정 위치의 `PaleoBytes/PaperMeister/preferences.json` (RunPod, Zotero 자격증명) — Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support`, Linux `~/.config`. **데이터 디렉터리와 분리**(머신 로컬 상태 + 평문 키, 그리고 데이터 위치를 설정 가능하게 만들 때의 부트스트랩 순환 방지). 규약·근거는 [R02](./devlog/20260728_R02_Config_File_Location_Convention.md)
- **데이터 경로:** `papermeister/paths.py`가 **단일 소스**. PaleoBytes 규약(`~/PaleoBytes/<AppName>/`)을 Modan2·CTHarvester와 공유. **폴백 없음** — 경로는 조건 없는 상수이고 `PAPERMEISTER_DATA_DIR`로만 override. 옛 `~/.papermeister`는 읽지 않으며, 남아 있으면 시작 시 경고만 하고 `scripts/migrate_data_dir.py`를 안내
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
- FTS5 (P13 external-content): `passage_fts`는 **external-content(text-only)** — `passage` 테이블 위에 색인만 두고 원문은 안 복사(OCR 본문 중복 ~1.75GB 제거, DB ~40%↓). 검색은 `passage` JOIN으로 paper_id/page 획득, `snippet(passage_fts,0,…)`, `bm25(passage_fts)`. 제목어/저자명이 본문에 없어도 찾도록 **document 단위 `paper_fts(title, authors)`**(standalone) 추가 — 검색은 본문 ∪ 제목·저자 병합. 제목 부스트는 `search.py::_title_tier` 3단 Python 재랭킹(devlog 063). **동기화는 트리거**(`passage`→passage_fts, `paper`/`author`→paper_fts) — FTS 테이블을 직접 INSERT/DELETE 하지 말 것. 기존 DB는 `scripts/migrate_fts_external_content.py`로 1회 변환(미변환 시 `init_db`가 차단)
- `papermeister/search.py::search()`: `limit` 파라미터는 **distinct paper 수** (2026-04-12 이전엔 passage row 수였음). FTS5 `bm25()`가 aggregate 컨텍스트에서 호출 불가한 제약 때문에 SQL `GROUP BY` 대신 Python dict dedupe로 처리. `max_passages=200_000` 안전 상한
- UI는 QThread로 비동기 처리, DB는 peewee thread-local 연결
- OCR health 체크: `ensure_workers_ready()`로 세션당 한 번만 수행
- OCR 병렬 처리: `get_worker_status()`로 idle worker 수 확인 → `ThreadPoolExecutor`로 병렬 제출
- `database.py`의 `_migrate()`가 기존 DB에 새 컬럼/인덱스 변경 자동 적용
- Zotero: 시작 시 컬렉션 자동 동기화, 컬렉션 클릭 시 아이템 fetch, PDF는 OCR 시점에만 임시 다운로드
- 설정: OS 설정 위치의 `PaleoBytes/PaperMeister/preferences.json` (RunPod, Zotero). `.env` 사용하지 않음.
- OCR JSON → Zotero 자동 업로드: `zotero_upload_ocr_json` pref로 opt-in (기본 OFF)
- Zotero attachment sync: 모든 타입(PDF+JSON) 수집, JSON은 status='processed'로 자동 설정
- LLM 서지 추출: `PaperBiblio` 테이블에 비파괴 보관 (source 필드로 모델/버전 구분)
  - 텍스트 추출: Haiku (`scripts/extract_biblio.py`). needs_visual_review 자가 보고
  - Vision pass: Sonnet (`scripts/extract_biblio_vision.py`). CJK/표지/TOC에 필수
  - Standalone promote: `scripts/promote_standalone.py` (confidence=high만 자동)
  - In-place update: `scripts/update_promoted_items.py` (itemType 변경 시 template 재생성)
- CJK 저자 이름 분리: 4글자→2/2(일본), 3글자→1/2(한국)
- **저자 이름 저장 형식**: Zotero에서 `firstName`/`lastName` 분리 제공 시 `"Last, First"` (쉼표 구분)로 저장. biblio apply로 들어온 이름은 `"First Last"` (공백). 양쪽 모두 `split_author_name()`이 정확히 파싱. 레거시 `"Last First"` (쉼표 없음) 데이터는 `database.py` 마이그레이션으로 일괄 변환 완료
- **P08 evaluate `already_complete`**: curated paper에서 빈 슬롯이 없고, 모든 필드가 biblio와 동일하면 `skip/already_complete` → needs_review에서 제외

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
- **DetailPanel**: `QWidget` (not QScrollArea) + 내부 `QTabWidget#DetailTabs`. 탭 4개 — **Metadata / PDF / Text / References** (Biblio 대조는 Metadata 탭에 통합, PDF·Text·References는 첫 활성화 때 lazy 빌드). 각 탭 독립 스크롤, 논문 전환 시 직전 탭 복원. Stub 배너는 탭바 위에 고정
- **Biblio 탭 대조 비교 UI**: Paper(Zotero) vs PaperBiblio(추출) 필드별 비교 테이블. diff가 있는 행에 라디오 버튼(Paper/Biblio 선택) + 편집 가능한 입력 필드(QPlainTextEdit: Title/Authors/Journal, QLineEdit: Year/DOI) + × 클리어 버튼. Apply 시 `apply_merged()`로 선택/편집된 값 반영. 저자는 한 줄 한 명, "Lastname, Firstname" 형식
- **OCR 탭**: `papermeister.biblio.load_ocr_pages()`로 `~/PaleoBytes/PaperMeister/ocr_json/{hash}.json` 페치 → `_sanitize_ocr_markdown()` 적용 → `QTextBrowser.setMarkdown()` 렌더
  - **Sanitizer 필수**: Chandra2 원본을 그대로 `setMarkdown()`에 넘기면 `-qt-list-indent` 누적으로 "텍스트가 계속 오른쪽으로 밀리는" 버그. 원인은 (a) 4+ leading space → indented code block, (b) 줄 시작 `숫자.` → ordered list, (c) 레퍼런스의 바 볼륨 번호(`88.`, `158.`) → 빈 OL이 인접하면 Qt가 nested로 해석해서 indent가 누적. Sanitizer가 모든 줄 `lstrip()` + `^(\d+)\.` regex를 backslash escape로 차단
- **SVG 아이콘**: `desktop/theme/icons/*.svg`는 `stroke="currentColor"`로 작성하고 `icons.rail_icon()` 헬퍼가 런타임에 색을 치환해서 3-state QIcon(idle/checked/hover) 생성. 다크/라이트 테마 스왑도 같은 메커니즘으로 확장 가능
- **QSS**: `desktop/theme/qss.py::build_stylesheet(colors)`가 `desktop/theme/tokens.py::COLORS_DARK`를 받아 풀 스타일시트 생성. QTree branch chevron SVG 경로는 `_icon_url()`이 `Path.as_posix()`로 Windows forward-slash 경로 주입

## Scripts (scripts/ 디렉토리)

**관례**: 변경을 가하는 스크립트는 모두 **`--execute`** 플래그를 쓴다 (플래그 없으면 dry-run 미리보기가 기본). 옛 `--dry-run` 관례(=실행이 기본)는 폐기·통일됨.

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
| `extract_references.py` | (P11) references 섹션 파싱 → `Reference` 테이블 (Qwen3, `--execute`) |
| `reset_references.py` | (P11) `Reference` 행 삭제 + `references_checked` 해제 → 재추출 대상으로 되돌림. `--paper-ids` 또는 `--scope empty-checked`(checked인데 Reference 0건인 논문 전체 — "no references section" 판정을 재검증할 때), `--execute` |
| `reprocess_references.bat` | (P11, Windows) reset(化石 합본) → extract_references `--scope all` → normalize_works `--pass 1` 일괄 실행 래퍼 |
| `migrate_fts_external_content.py` | (P13) `passage_fts` → external-content + `paper_fts` 추가 1회 변환 (자동 백업 VACUUM INTO + rebuild + VACUUM, `--execute`) |
| `backup-papermeister.ps1` + `_db_snapshot.py` | (운영) 라이브 DB 일관성 스냅샷(online backup) → gzip → 서버 scp + 보존정리. Task Scheduler 3시간 간격 백업용 |
| `resolve_references.py` | (P11) `Reference` → 보유 Paper 매칭 (DOI + 제목 스코어, `--execute`) |
| `normalize_works.py` | (P11 Phase 2) 외부 문헌 → `CitedWork` 노드 정규화. 패스1 exact dedup + 패스2 LLM 병합 + cite_count/reconcile (`--execute`, `--pass`, `--workers`) |
| `probe_qwen.py` | (P11) ocrserver LLM 응답시간 진단 (trivial/1ref/5ref 계측) |
| `refs_progress.py` | (P14) references 추출 진행률·처리율·ETA 모니터 (`--watch`) |
| `citation_stats.py` | (P14 L0) held→held 인용 그래프 통계 |
| `export_citation_graph.py` | (P14 L1) nodes/edges CSV + GEXF(Gephi), `--with-external` |
| `audit_matches.py` | (P14 A2) 참조 매칭 감사 (의심 FP / 미연결 FN 탐지) |
| `verify_image.py` | OCR 이미지 경로(Pillow) 1-커맨드 검증 |
| `migrate_data_dir.py` | 데이터 디렉터리 `~/.papermeister` → `~/PaleoBytes/PaperMeister` 이동 (`--execute`, `--copy`). **앱을 닫고 실행** |

## 문서 / 릴리스

- **사용자 매뉴얼**: `docs/manual/` (Sphinx, en + ko) → push 시 `docs.yml`이 GitHub Pages 배포.
  버전은 `version.py`에서, 릴리스 노트는 루트 `CHANGELOG.md`에서 **single-source**로 가져온다
  (복사 금지). 한국어 번역은 `locale/ko/LC_MESSAGES/*.po`
  - ⚠️ 닫는 강조 표시 뒤에 조사가 바로 붙으면 RST가 마크업을 통째로 삼킨다.
    `**일시정지**한 뒤` → `**일시정지**\ 한 뒤` 처럼 이스케이프 공백(`\ `)을 넣을 것
- **릴리스**: `CHANGELOG.md`에 섹션 추가 → **ko 카탈로그 갱신**(`cd docs/manual && make gettext && sphinx-intl update -p _build/gettext -l ko` → `.po` 번역 → `sphinx-intl build`) → `version.py` 범프 → `vX.Y.Z` 태그 push.
  ⚠️ CHANGELOG는 매뉴얼에 include되므로 **고치면 ko 번역도 같이 손봐야 한다** — 안 하면 한국어 changelog만 영어로 남는다(085에서 실제 발생).
  `release.yml`이 테스트→3플랫폼 빌드→CHANGELOG 섹션을 노트로 발행. 수동 발행은 `manual-release.yml`
- **설치 프로그램**: `installer/PaperMeister.iss.template` — 사용자 단위(관리자 권한 불필요),
  `%LOCALAPPDATA%\Programs\PaleoBytes\PaperMeister`에 설치, 시작 메뉴 `PaleoBytes` 그룹.
  **`AppId` GUID는 절대 바꾸지 말 것**(바꾸면 업그레이드가 별개 프로그램으로 설치되고 옛 항목이 제어판에 남음).
  **런타임 데이터는 설치/제거가 건드리지 않는다** — `[UninstallDelete]` 추가 금지(그 디렉터리가 사용자 라이브러리)
- **CI**: `test.yml`(ruff+mypy, Linux·Windows 테스트, 커버리지 ratchet) / `security.yml`(pip-audit + lock-check)
  / `codeql.yml` / `docs.yml` / `dependabot-lock-refresh.yml`(Dependabot PR의 lock 자동 재생성)

## Future Phases

- **Phase 1.5 (진행 중):** LLM 서지정보 추출 → Zotero 메타데이터 보강
- **Phase 2:** Hybrid search (BM25 + embeddings), LLM query interpretation
- **Phase 3:** Entity extraction (taxon, locality), relation extraction
