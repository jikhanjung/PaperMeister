# PaperMeister

학술 논문 PDF 컬렉션을 검색 가능한 지식 베이스로 변환하는 데스크톱 앱.

**Core pipeline**: Source → Ingestion → OCR → Metadata Extraction → DB → Search

**Key principle**: "Store first, understand later" — 전문(fulltext)이 진실의 원본이고, 모든 서지/색인은 거기서 파생된다.

## 주요 기능

- **PDF 임포트**: 로컬 폴더 구조 그대로 반영 + **Zotero 양방향 동기화** (pull + write-back)
- **OCR**: 3-backend (RunPod serverless / vLLM pod 직결 / wrapper API), Chandra2. 서버 장애 시 자동 일시정지·복구
- **전문 검색**: SQLite FTS5 — 페이지 본문 + 제목·저자 별도 색인, 제목 매치 우선 랭킹 + 일치 부분 강조
- **LLM 서지 추출**: Claude(Haiku/Sonnet) 또는 Qwen3 → PaperBiblio 비파괴 저장 → 검토 후 Zotero 메타데이터 보강
- **참고문헌 + 인용 네트워크**: 각 논문의 참고문헌을 구조화 파싱 → 보유 논문과 매칭, 외부 문헌은 `CitedWork` 대표 노드로 정규화. 인용 ego 그래프 + Cited Works 브라우저
- **세 가지 인터페이스**:
  - **신규 desktop 앱** (`python -m desktop`) — 3-pane + 탭 기반 detail panel, OCR 본문 markdown 렌더링, 전문 검색
  - **기존 GUI** (`python main.py`) — 안정 상태, 동결됨
  - **CLI** (`python cli.py`) — import/process/search/list/show/config/zotero 서브커맨드

## 설치

**릴리스 내려받기** (권장) — [releases](https://github.com/jikhanjung/PaperMeister/releases)에 태그마다
Windows 포터블 zip·설치본, Linux AppImage, macOS DMG가 SHA256과 함께 올라옵니다.

Windows 설치본은 관리자 권한 없이 `%LOCALAPPDATA%\Programs\PaleoBytes\PaperMeister`에 설치되고,
시작 메뉴 `PaleoBytes` 그룹에 등록됩니다. 제거해도 **데이터는 남습니다**(아래 참조).

**소스에서 실행**:
```bash
pip install -r requirements.txt        # Python 3.12+
python -m desktop
```

CI와 동일한 재현 가능 환경이 필요하면 해시 고정 lock을 쓰세요:
```bash
pip install --require-hashes -r requirements.lock
```

## 설정

**Preferences** 에서:

- **RunPod OCR**: Endpoint ID + API Key
- **Zotero** (선택): User ID + API Key ([zotero.org/settings/keys](https://www.zotero.org/settings/keys))

설정은 **OS 설정 위치**의 `PaleoBytes/PaperMeister/preferences.json`에 저장(Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support`, Linux `~/.config`). DB는 `~/PaleoBytes/PaperMeister/papermeister.db`, OCR 결과 캐시는 `~/PaleoBytes/PaperMeister/ocr_json/{hash}.json`.

## 실행

```bash
python -m desktop        # 신규 desktop 앱 (권장)
python main.py           # 기존 3-pane GUI
python cli.py --help     # CLI 도움말
```

## Desktop 앱 사용법

### 레이아웃
```
┌─[Rail]─┬──[Zotero 탭]──────┬──[논문 목록]──┬─[Metadata|PDF|Text|References]─┐
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
- **Sync** — Zotero 증분 동기화
- **Process** — pending 논문 OCR 트리거
- **Import folder** — 로컬 PDF 폴더를 새 소스 탭으로 가져오기
- **Cited Works** — 외부 인용 문헌을 인용 횟수 순으로 탐색
- **Settings** — Preferences 다이얼로그

### 네비게이션
1. 좌측 Zotero 탭에서 Library 필터 또는 컬렉션 클릭 → 중앙 목록 로드
2. 목록에서 논문 클릭 → 우측 상세 패널에 **Metadata / PDF / Text / References** 탭 표시
3. **Metadata** — 메타데이터 + 파일 정보 + Paper(Zotero) vs PaperBiblio(추출) 대조 비교. 필드별 라디오 선택·편집 후 Apply
4. **PDF** — PyMuPDF 렌더 (보이는 페이지만 lazy 디코드) / **Text** — OCR 본문 markdown
5. **References** — 이 논문이 인용한 문헌 + 이 논문을 인용한 라이브러리 논문(양방향). 보유 문헌은 클릭 시 이동. 우클릭 → *Show in citation network* 로 ego 그래프

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

## 참고문헌 / 인용 네트워크 (P11·P12)

```bash
python scripts/extract_references.py --scope all --execute   # 참고문헌 파싱
python scripts/resolve_references.py --execute               # 보유 논문과 매칭
python scripts/normalize_works.py --pass 1 --execute         # 외부 문헌 정규화 (exact)
python scripts/normalize_works.py --pass 2 --execute         # 외부 문헌 정규화 (LLM 병합)
python scripts/citation_stats.py                             # 인용 그래프 통계
python scripts/export_citation_graph.py                      # CSV / GEXF export
```

## 개발

```bash
pip install -r requirements-dev.txt
pytest                  # 테스트
ruff check .            # 린트
make lock-check         # lock 파일이 requirements와 맞는지 확인
```

릴리스는 `CHANGELOG.md`에 섹션 추가 → `version.py` 범프 → `vX.Y.Z` 태그 push.
자세한 내용은 [매뉴얼의 개발자 안내서](https://jikhanjung.github.io/PaperMeister/en/developer_guide.html) 참고.

자세한 정책은 [devlog/20260411_P08_PaperBiblio_Reflection_Policy.md](./devlog/20260411_P08_PaperBiblio_Reflection_Policy.md) 참고.

## 기술 스택

- **GUI**: PyQt6
- **DB**: SQLite + FTS5
- **ORM**: Peewee 4
- **PDF**: PyMuPDF
- **OCR**: RunPod serverless (Chandra2-vllm)
- **Zotero**: pyzotero
- **LLM**: `claude -p` (Haiku + Sonnet, Max 플랜) 또는 자체 서버의 Qwen3
- **문서**: Sphinx (en/ko) → GitHub Pages
- **CI**: ruff + mypy + pytest(Linux·Windows), pip-audit, CodeQL, 해시 고정 lock, 3-플랫폼 릴리스 빌드

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
├── references.py       # 참고문헌 저장 + 보유 논문 매칭 + CitedWork 정규화
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

tests/                  # pytest (unit / ui / integration 마커)
docs/manual/            # Sphinx 매뉴얼 (en/ko) → GitHub Pages
.github/workflows/      # CI: 테스트·보안·CodeQL·문서·릴리스

cli.py                  # CLI 엔트리
main.py                 # 기존 GUI 엔트리
HANDOFF.md              # 세션 간 인계 문서
CLAUDE.md               # 코드베이스 가이드 (Claude Code용)
devlog/                 # 개발 기록 (구현 + 계획)
```

## 문서

- **[사용자 매뉴얼](https://jikhanjung.github.io/PaperMeister/)** — 설치·빠른 시작·사용법·문제 해결 ([한국어](https://jikhanjung.github.io/PaperMeister/ko/))
- [CHANGELOG.md](./CHANGELOG.md) — 릴리스 노트 (GitHub 릴리스 페이지가 인용하는 원본)
- [HANDOFF.md](./HANDOFF.md) — 현재 진행 상태, 다음 할 일, 운영 규칙
- [CLAUDE.md](./CLAUDE.md) — 코드베이스 구조 + 주요 결정사항 (Claude Code용 가이드)
- [devlog/](./devlog/) — 계획 문서 (`YYYYMMDD_PNN_*.md`) + 구현 기록 (`YYYYMMDD_NNN_*.md`)
- [papermeister_prd.md](./papermeister_prd.md) — 원본 PRD

## Phase 로드맵

- ✅ **Phase 1**: MVP (PDF 임포트, OCR, FTS 검색, 기본 GUI)
- ✅ **Phase 1.5**: LLM 서지 추출 + Zotero 메타데이터 write-back
- ✅ **Phase 2**: 반영 정책 (P08), needs_review 식별, 러너 검증
- ✅ **Phase 3**: 신규 desktop 앱
- ✅ **Phase D** (대량 운영): 라이브러리 전체 OCR + biblio 추출 완료
- ✅ **P02**: PyInstaller 패키징 → 3-플랫폼 릴리스 (v0.1.0 / v0.1.1)
- ✅ **P13**: FTS external-content 전환 (DB 40%↓) + document 단위 제목·저자 색인
- 🟡 **P11/P12**: 참고문헌 추출 + `CitedWork` 정규화 + 인용 네트워크 — 코드 완료, 라이브 추출 진행 중
- 🟡 **Phase 4**: hookup — batch Reflect UI, needs_review 일괄 검토
- ⬜ **Phase 5**: Hybrid search (BM25 + embeddings), LLM query interpretation
- ⬜ **Phase 6**: Entity/relation extraction (taxon, locality)

## 라이선스

PaperMeister는 **GPL-3.0-or-later**로 배포됩니다 (전문: [`LICENSE`](./LICENSE)).

배포되는 빌드가 **PyQt6(GPL-3.0)** 를 번들하므로 결합저작물 전체가 그 조건을 따릅니다.
자유롭게 사용·연구·수정·재배포할 수 있으며, 전체 소스는 이 저장소에 있습니다.

0.1.6까지는 **PyMuPDF(AGPL-3.0)** 때문에 AGPL이었으나, 0.1.7에서 렌더링을
**pypdfium2**(BSD-3-Clause / Apache-2.0)로 교체하면서 GPL-3.0이 되었습니다.

서드파티 구성요소와 각각의 라이선스는 앱의 **Preferences → About** 탭에서 확인할 수
있습니다. 판단 근거와 남은 선택지(PyQt6 → PySide6로 가면 permissive 가능)는
[R03 라이선스 감사](./devlog/20260813_R03_License_Audit.md)에 정리돼 있습니다.
