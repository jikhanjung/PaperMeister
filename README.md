# PaperMeister

학술 논문 PDF 컬렉션을 검색 가능한 지식 베이스로 변환하는 데스크톱 앱.

**Core pipeline**: Source → Ingestion → OCR → Metadata Extraction → DB → Search

**Key principle**: "Store first, understand later" — 전문(fulltext)이 진실의 원본이고, 모든 서지/색인은 거기서 파생된다.

## 주요 기능

- **PDF 임포트**: 로컬 폴더 구조 그대로 반영 + **Zotero 양방향 동기화** (pull + write-back)
- **OCR**: RunPod serverless GPU (Chandra2-vllm), idle worker 수만큼 자동 병렬
- **전문 검색**: SQLite FTS5 + BM25 (title ×10, authors ×5, text ×1)
- **LLM 서지 추출**: Claude Haiku(텍스트) / Sonnet(vision) 기반 biblio 추출 → PaperBiblio 비파괴 저장 → Zotero 메타데이터 보강
- **세 가지 인터페이스**:
  - **신규 desktop 앱** (`python -m desktop`) — 3-pane + 탭 기반 detail panel, OCR 본문 markdown 렌더링, 전문 검색
  - **기존 GUI** (`python main.py`) — 안정 상태, 동결됨
  - **CLI** (`python cli.py`) — import/process/search/list/show/config/zotero 서브커맨드

## 설치

```bash
pip install -r requirements.txt
```

Windows + Anaconda 권장:
```bash
conda create -n papermeister python=3.11
conda activate papermeister
pip install -r requirements.txt
```

## 설정

**Preferences** 에서:

- **RunPod OCR**: Endpoint ID + API Key
- **Zotero** (선택): User ID + API Key ([zotero.org/settings/keys](https://www.zotero.org/settings/keys))

설정은 `~/.papermeister/preferences.json`에 저장. DB는 `~/.papermeister/papermeister.db`, OCR 결과 캐시는 `~/.papermeister/ocr_json/{hash}.json`.

## 실행

```bash
python -m desktop        # 신규 desktop 앱 (권장)
python main.py           # 기존 3-pane GUI
python cli.py --help     # CLI 도움말
```

## Desktop 앱 사용법

### 레이아웃
```
┌─[Rail]─┬──[Zotero 탭]──────┬──[논문 목록]──┬──[Metadata|Biblio|OCR]─┐
│ 📚     │ All Files   9,783 │ Status Auth Yr … │ 탭별 독립 스크롤     │
│ 🔍     │ Pending     7,481 │ done  Smith… │                        │
│  ⋮     │ Processed   4,494 │ ...           │                        │
│ ⚙      │ Needs Rev      31 │               │                        │
│ ⋯      │ ── COLLECTIONS ── │               │                        │
│        │ ▼ Zotero          │               │                        │
│        │   ▶ Col A         │               │                        │
│        │   ▶ Col B         │               │                        │
└────────┴───────────────────┴───────────────┴────────────────────────┘
```

### Rail 아이콘
- **Library** / **Search** — 지속 모드 (checkable)
- **Process** — pending 논문 OCR 트리거 (one-shot 액션)
- **Settings** — Preferences 다이얼로그 (one-shot 액션)

### 네비게이션
1. 좌측 Zotero 탭에서 Library 필터 또는 컬렉션 클릭 → 중앙 목록 로드
2. 목록에서 논문 클릭 → 우측 상세 패널에 **Metadata / Biblio / OCR** 탭 표시
3. OCR 탭은 processed 논문에서 sanitized markdown으로 본문 렌더
4. Biblio 탭은 Paper(Zotero) vs PaperBiblio(추출) 대조 비교 + 필드별 라디오 선택/편집 + Apply

### 검색
- 상단 검색창에 쿼리 + Enter → BM25 랭킹으로 최대 200편 논문
- 검색창 Clear (X 버튼 또는 backspace 전체 삭제) → 이전 Library 뷰 자동 복원
- 좌측 nav 클릭 시 검색창 자동 clear

## CLI 사용법

```bash
python cli.py import /path/to/papers     # 로컬 폴더 임포트
python cli.py process                    # 모든 pending 파일 OCR
python cli.py process -c "Collection A"  # 특정 Zotero 컬렉션만
python cli.py search "trilobite"         # FTS5 검색
python cli.py list --folder 123          # 폴더 내 논문 목록
python cli.py show 456                   # 논문 상세
python cli.py zotero sync                # Zotero 컬렉션 재동기화
python cli.py config runpod_api_key XXX  # 설정 읽기/쓰기
```

인터랙티브 모드: 인자 없이 `python cli.py` 실행.

## 서지 추출 파이프라인 (Phase 1.5)

OCR 완료된 논문에서 LLM으로 구조화된 서지정보 추출 → `PaperBiblio` 테이블에 비파괴 저장 → 사람 검토 후 Zotero 메타데이터 보강.

```bash
python scripts/extract_biblio.py --scope pending         # Haiku 텍스트 추출
python scripts/extract_biblio_vision.py --paper-ids 1,2  # Sonnet vision (CJK/표지/TOC)
python scripts/reflect_biblio.py                         # P08 반영 러너
python scripts/promote_standalone.py                     # Standalone PDF → Zotero parent 생성
```

자세한 정책은 [devlog/20260411_P08_PaperBiblio_Reflection_Policy.md](./devlog/20260411_P08_PaperBiblio_Reflection_Policy.md) 참고.

## 기술 스택

- **GUI**: PyQt6
- **DB**: SQLite + FTS5
- **ORM**: Peewee
- **PDF**: PyMuPDF (fitz)
- **OCR**: RunPod serverless (Chandra2-vllm)
- **Zotero**: pyzotero
- **LLM**: `claude -p` (Haiku + Sonnet, Max 플랜)

## 프로젝트 구조

```
papermeister/           # 코어 라이브러리
├── models.py           # DB 모델 (Source/Folder/Paper/Author/PaperFile/Passage/PaperBiblio)
├── database.py         # 초기화 + 마이그레이션
├── ingestion.py        # 디렉토리/Zotero 스캔
├── ocr.py              # RunPod OCR 클라이언트 (병렬, health check)
├── text_extract.py     # OCR 결과 + 메타데이터 → DB
├── search.py           # FTS5 검색 (Python dict dedupe, limit = distinct papers)
├── biblio.py           # OCR JSON 로드 + BiblioResult 데이터클래스
├── biblio_eval.py      # 서지 추출 평가 메트릭
├── biblio_reflect.py   # PaperBiblio → Paper 반영 정책 (P08)
├── zotero_client.py    # Zotero API 래퍼
├── zotero_writeback.py # Zotero 단방향 메타데이터 write-back
├── preferences.py      # 설정 파일 I/O
└── ui/                 # 동결된 기존 GUI
    ├── main_window.py
    ├── process_window.py       # 새 desktop 앱에서 재사용 중
    ├── preferences_dialog.py   # 새 desktop 앱에서 재사용 중
    └── zotero_import_dialog.py

desktop/                # 신규 desktop 앱 (Phase 3~4)
├── __main__.py         # `python -m desktop`
├── app.py              # QApplication + 테마 로드
├── windows/main_window.py
├── views/              # source_nav, paper_list, detail_panel
├── services/           # paper_service, library, source_service, biblio_service, search_service
├── components/         # sidebar (Rail), search_bar, status_bar, status_badge
├── workers/            # background QThread tasks
└── theme/              # tokens, qss, icons (SVG + runtime color tinting)

scripts/                # 운영/배치 스크립트
├── extract_biblio.py           # Haiku 서지 추출
├── extract_biblio_vision.py    # Sonnet vision 서지 추출
├── reflect_biblio.py           # PaperBiblio → Paper 반영 러너
├── promote_standalone.py       # Standalone PDF → Zotero parent
├── update_promoted_items.py    # 기존 Zotero item in-place 수정
├── resync_zotero.py            # Zotero 전체 재동기화 (destructive, 주의)
└── ...

cli.py                  # CLI 엔트리
main.py                 # 기존 GUI 엔트리
HANDOFF.md              # 세션 간 인계 문서
CLAUDE.md               # 코드베이스 가이드 (Claude Code용)
devlog/                 # 개발 기록 (구현 + 계획)
```

## 문서

- [HANDOFF.md](./HANDOFF.md) — 현재 진행 상태, 다음 할 일, 운영 규칙
- [CLAUDE.md](./CLAUDE.md) — 코드베이스 구조 + 주요 결정사항 (Claude Code용 가이드)
- [devlog/](./devlog/) — 계획 문서 (`YYYYMMDD_PNN_*.md`) + 구현 기록 (`YYYYMMDD_NNN_*.md`)
- [papermeister_prd.md](./papermeister_prd.md) — 원본 PRD

## Phase 로드맵

- ✅ **Phase 1**: MVP (PDF 임포트, OCR, FTS 검색, 기본 GUI)
- ✅ **Phase 1.5**: LLM 서지 추출 + Zotero 메타데이터 write-back (진행 중 → 대부분 완료)
- ✅ **Phase 2**: 반영 정책 (P08), needs_review 식별, 러너 검증
- 🟡 **Phase 3**: 신규 desktop 앱 (기본 사용 가능, Phase 4로 넘어감)
- 🟡 **Phase 4**: hookup — Apply/Process/Settings end-to-end 실증, batch Reflect UI, background worker
- ⬜ **Phase D** (대량 운영): OCR 완료 ~2,000편에 Haiku biblio 일괄 추출 + reflect
- ⬜ **Phase 5**: Hybrid search (BM25 + embeddings), LLM query interpretation, document-level title boost
- ⬜ **Phase 6**: Entity/relation extraction (taxon, locality)
