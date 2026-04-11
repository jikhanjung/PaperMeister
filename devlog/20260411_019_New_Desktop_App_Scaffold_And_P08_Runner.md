# 019: 새 데스크탑 앱 스캐폴드 + P08 반영 러너 구현

## 배경

세션 6까지 OCR + LLM 서지 추출 파이프라인은 완성되어 있었으나:

- 기존 `papermeister/ui/` 3-pane GUI는 디자인이 오래됐고, `PaperBiblio → Paper` 반영 흐름이 UI에서 막혀 있었다.
- 대량 추출 결과(148 row)가 `PaperBiblio`에 쌓여 있었지만 `Paper`에 반영하는 정책도, 러너도 없었다.
- P07(데스크탑 구현 계획)는 초안 수준이었고, 현재 실제로 뭐가 구현돼 있는지와 뭐가 남아 있는지가 구분되지 않았다.

이 세션은 다음을 목표로 했다.

1. P07을 현실에 맞게 개정하고, 정책/설계 문서를 분리한다.
2. 기존 GUI를 건드리지 않고 새 모던 앱을 별도 패키지로 스캐폴드한다.
3. `PaperBiblio → Paper` 반영 러너를 구현해 앱에서 한 건 반영이 가능하게 만든다.

## 결과 요약

- 문서 3건: [P07 개정](./20260410_P07_Desktop_Software_Implementation_Plan.md), [P08 작성](./20260411_P08_PaperBiblio_Reflection_Policy.md), [P09 작성](./20260411_P09_New_Desktop_UI_Design.md)
- 새 앱 패키지 `desktop/` 스캐폴드 (기존 `papermeister/ui/`는 동결)
- `papermeister/biblio_reflect.py` + `scripts/reflect_biblio.py` — P08 정책 런타임
- DB migration: `PaperBiblio.status/review_reason`, `PaperFile.failure_reason` (기존 148 row 보존)
- Desktop "Apply Biblio" 버튼이 실제 동작 (background worker + counts 재갱신)
- PaperList Status 컬럼에 컬러 pill delegate

## 커밋 타임라인

```
0dfb972 Wire Apply Biblio button and status pill delegate
0d43f14 Implement P08 biblio reflection policy
1d3634b Update HANDOFF.md for session 7 — new desktop app scaffold
d80aeab Scaffold new desktop app with modern dark theme
2252b66 Revise desktop plan with current-state audit and split policy docs
```

## 1. 문서 개정/신규

### 1.1 P07 개정 (`20260410_P07_...`)

P07 초안의 가장 큰 문제는 "이미 돌아가는 것"과 "만들어야 할 것"을 섞어둔 것이었다. 이 세션에서 추가한 것:

- **현재 구현 상태 섹션**: source/OCR/캐시/FTS/LLM 추출 파이프라인 모두 ✅, UI 통합과 정책만 ❌. Phase 1은 사실상 완료 판정.
- **entity × state machine 매트릭스**: flat status list(`pending/processed/failed/needs_review/promoted/writeback_pending`)는 UI Library 매핑이 모호해진다. 이걸:
  - `PaperFile.status` = OCR 실행 관점 (pending/processed/failed)
  - `PaperBiblio.status` = 추출 결과 검토 관점 (extracted/needs_review/auto_committed/applied/rejected)
  - `Paper` = derived (stub/extracted/curated) — 컬럼 추가 없이 쿼리로 판정
  - Workflow 상태(promoted/writeback_pending)는 별도 큐 테이블로 뒤로 미룸
- **Paper 정체성 비대칭**: 이 세션에서 사용자가 지적한 내용. Zotero source는 Paper가 처음부터 API로 채워지지만 filesystem source는 `Paper.create(title=filename_stem)`으로 stub 생성. 즉 `Paper/PaperFile/PaperBiblio` 분리는 원래 Zotero 중심 모델이고, 디렉토리 import 시점에는 Paper가 placeholder다.
- **Phase 재순서**: `Phase 4(Search) → Phase 5(Review/Automation)` 순서를 `Phase 4(paper list + detail + biblio hookup) → Phase 5(Search)`로 뒤집었다. 근거: Paper 메타데이터가 비어 있는 상태에서 title/author 검색은 쓸모 없음.
- **PDF viewer 최소 기능을 Phase 5로 승격**: PyMuPDF 의존성이 이미 있고, snippet 클릭→페이지 이동이 검색 실사용성을 결정함.

### 1.2 P08 (신규) — `PaperBiblio → Paper` 반영 정책

[P08 전문](./20260411_P08_PaperBiblio_Reflection_Policy.md)

핵심:

- **선택 규칙**: `applied > source(sonnet-vision > haiku-vision > sonnet > haiku) > confidence > recency`
- **Auto-commit 조건** (모두 충족):
  - 필수 필드: title, authors ≥ 1, year (또는 doc_type ∈ {book, chapter, report})
  - confidence = high, needs_visual_review = false
  - doc_type != unknown, doc_type != journal_issue
- **Override 정책**: stub Paper는 자유롭게 덮어쓰기, curated Paper는 **빈 슬롯 채우기만** 허용. 둘 다 실패하면 `override_conflict` 사유로 needs_review.
- **needs_review taxonomy**: `missing_title|missing_authors|missing_year|unknown_doctype|visual_review_flag|low_confidence|override_conflict|journal_issue`
- **멱등성**: auto_committed/applied 상태는 재선택 대상에서 제외. Paper 업데이트는 트랜잭션.

### 1.3 P09 (신규) — 새 데스크탑 앱 UI 설계

[P09 전문](./20260411_P09_New_Desktop_UI_Design.md)

핵심 결정:

- **테마 스택**: 외부 테마 의존성 없이 **custom QSS + design tokens**. qt-material/fluent/qdarkstyle 후보를 두고 선택한 이유는 (1) 추가 의존성 0 (2) 다크/라이트 swap이 dict 교체로 끝남 (3) Linear/Zed/Raycast 류의 "조용한 도구" 미적 감각을 직접 구현 가능.
- **레이아웃**: `Rail(40) | SourceNav(260) | PaperList(flex) | DetailPanel(420)` + 상단 TopBar(48) + 하단 StatusBar(24)
- **디자인 토큰**: 색(dark 20개), spacing(4px grid), radius, font 사이즈/웨이트
- **파일 구조**: `theme / windows / views / services / components / workers` 6디렉토리, **DB 접근은 services 경계에서만** (views는 peewee를 import하지 않음)
- **화면별 상태/액션 매트릭스**: Library 폴더 선택별/Source 선택별/Paper 선택별 가능한 액션과 detail panel 카드 구성을 표로 명시

## 2. 새 앱 패키지 `desktop/`

### 2.1 파일 구조

```
desktop/
├── __main__.py              # python -m desktop 엔트리
├── app.py                   # QApplication + 테마 로드
├── theme/
│   ├── tokens.py            # COLORS_DARK, SPACING, RADIUS, FONT, LAYOUT
│   └── qss.py               # 토큰 → QSS 문자열 (6,750자)
├── windows/
│   └── main_window.py       # TopBar + Rail + 3-pane splitter + StatusBar
├── views/
│   ├── source_nav.py        # Library + Sources 이중 트리
│   ├── paper_list.py        # QTreeWidget + StatusPillDelegate
│   └── detail_panel.py      # Metadata / Biblio / File 카드 스택
├── components/
│   ├── sidebar.py           # 좌측 Rail (icon toggle buttons)
│   ├── search_bar.py        # 상단 검색 입력 (Phase 5 전까지 placeholder)
│   ├── status_bar.py        # 하단 counts + task label
│   └── status_badge.py      # pill 라벨 (재사용 가능)
├── services/
│   ├── library.py           # Library 폴더별 쿼리 + corpus_counts
│   ├── source_service.py    # Source 트리 로더
│   ├── paper_service.py     # list_by_library / list_by_folder / list_by_source / load_detail
│   └── biblio_service.py    # preview_apply + apply_paper (GUI → biblio_reflect 브리지)
└── workers/
    └── background.py        # BackgroundTask(QThread) — done/failed 시그널
```

원칙:

- **views는 DB를 건드리지 않는다**. 모든 조회는 services를 통한다.
- **workers는 모든 DB write의 단일 진입점**. UI 스레드는 절대 블록되지 않는다.
- **컴포넌트는 상태를 스스로 fetch하지 않는다**. props만 받는다.
- **기존 `papermeister/ui/`와 양방향 import 금지**. 공용 로직은 `papermeister.models / biblio / biblio_reflect` 에서만 재사용.

### 2.2 테마 토큰

```python
COLORS_DARK = {
    'bg.app':        '#0F1115',
    'bg.panel':      '#151820',
    'bg.elevated':   '#1B1F2A',
    'bg.hover':      '#222634',
    'bg.selected':   '#2A3044',
    # ...
    'accent.primary':'#6D8EFF',   # soft indigo
    'status.ok':     '#4ADE80',
    'status.error':  '#F87171',
    'status.warn':   '#FBBF24',
}
```

`theme/qss.py::build_stylesheet(tokens)`는 이 dict를 받아 QSS 문자열을 생성한다. 다크 → 라이트는 dict만 교체하면 되도록 설계.

### 2.3 실행

```bash
python -m desktop
```

초기 로드 시 DB에 연결 후:

- Library(All/Pending/Processed/Failed/Needs Review/Recent) 카운트 표시
- Sources 트리(Zotero 45 컬렉션 + Local 1 디렉토리)
- Default로 "All Files" 로드 (현재 corpus 11,981 paper rows)
- StatusBar: `11,981 papers · 7,484 pending · 0 needs review`

## 3. P08 러너 구현

### 3.1 스키마 migration

`papermeister/models.py`:

```python
class PaperFile(BaseModel):
    ...
    failure_reason = peewee.TextField(default='')  # ocr_failed|download_failed|encrypted|...

class PaperBiblio(BaseModel):
    ...
    status = peewee.TextField(default='extracted')
    review_reason = peewee.TextField(default='')
```

`papermeister/database.py::_migrate()`에 `ALTER TABLE` 3개 추가. 기존 148개 `PaperBiblio` row는 자동으로 `status='extracted'`, `review_reason=''` 기본값이 붙는다.

### 3.2 `papermeister/biblio_reflect.py`

```
select_best_biblio(paper) -> PaperBiblio | None
evaluate(biblio, paper) -> Decision
apply(biblio, paper, dry_run=False) -> bool
apply_single(paper_id) -> (Decision, changed)     # GUI 진입점
reflect_all(source_id=..., folder_id=..., dry_run=...) -> ReflectStats
```

구현 포인트:

- `_parse_authors`: `[{"name": "X"}, ...]`와 `["X", ...]` 두 형식 모두 지원 (기존 데이터 혼재)
- `_is_stub_paper`: `year is null AND Author 없음` (P07 derived view 정의)
- `SOURCE_RANK = {'llm-sonnet-vision':50, 'llm-haiku-vision':40, 'llm-sonnet':30, 'llm-haiku-v2':22, 'llm-haiku':20}`
- **`journal_issue` 스킵을 필드 검사 앞**: 초기 구현에서 순서가 잘못돼 `missing_authors`가 64개 나왔다. 순서 수정 후 `skipped(journal_issue)=59 + missing_authors=5`로 정상화.
- `apply()`는 stub이면 전체 교체, curated이면 빈 슬롯만. Author 테이블도 같은 규칙.
- `apply_single()`은 성공 시 `status='applied'`로 마킹 — 사용자 승인이 auto-commit보다 강함.

### 3.3 Dry-run 결과 (현재 corpus)

```
$ python scripts/reflect_biblio.py --dry-run
[DRY RUN] scanned:        97
[DRY RUN] auto_committed: 7
[DRY RUN] needs_review:   31
[DRY RUN] skipped:        59
[DRY RUN] errors:         0
reasons:
  journal_issue            59
  override_conflict        21
  missing_authors          5
  missing_year             2
  low_confidence           2
  missing_title            1
```

- `journal_issue=59`: 「化石」 저널 호차별 표지 — promote 플로우 대상 (P08 범위 밖)
- `override_conflict=21`: Zotero에서 이미 curated된 Paper에 동등한 biblio — 정책상 fill-empty-slot도 안 됨
- `missing_*`: 추출 자체가 불완전한 케이스. 실제 review queue 대상.
- `auto_commit=7`: 실제 실행하면 즉시 Paper 필드가 채워질 후보

실제 apply는 아직 돌리지 않았다. 사용자 직접 검증 후 진행 예정.

### 3.4 CLI (`scripts/reflect_biblio.py`)

```bash
python scripts/reflect_biblio.py --dry-run                # 전체
python scripts/reflect_biblio.py --source 3               # source 범위
python scripts/reflect_biblio.py --folder 42              # folder 범위
python scripts/reflect_biblio.py --paper 1234             # 단일 paper (apply_single)
python scripts/reflect_biblio.py --paper-ids 1,2,3,4      # 리스트
```

## 4. Desktop "Apply Biblio" 루프

### 4.1 service 브리지 (`desktop/services/biblio_service.py`)

```python
@dataclass
class ApplyPreview:
    has_biblio: bool
    decision_action: str       # auto_commit | needs_review | skip
    decision_reason: str
    biblio_id: int | None
    biblio_status: str
    button_enabled: bool
    button_label: str
    tooltip: str

def preview_apply(paper_id) -> ApplyPreview: ...
def apply_paper(paper_id) -> (action, changed, reason): ...
```

- `preview_apply`는 `biblio_reflect.evaluate()`를 호출하고, 결과를 UI용 레이블로 변환
- `tooltip`은 `_REASON_BLURB` 딕셔너리로 사용자 친화적 문구 매핑
- `auto_commit`이면 primary 버튼 enabled, `needs_review`여도 **manual override가 가능**하므로 enabled 유지 (tooltip에 사유 표시), `skip`일 때만 disabled

### 4.2 Background worker (`desktop/workers/background.py`)

```python
class BackgroundTask(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs): ...
    def run(self):
        try:
            self.done.emit(self._fn(*self._args, **self._kwargs))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')
```

단순하지만, 모든 DB write가 이걸 통하도록 규약을 세움 — UI 스레드는 peewee를 건드리지 않는다.

### 4.3 DetailPanel 통합

- `show_paper(paper_id)` 시 `biblio_service.preview_apply()`를 호출해 Decision 라인과 Apply 버튼을 그림
- 버튼 클릭 → `BackgroundTask(biblio_service.apply_paper, paper_id)` 생성/start
- `done` 시 `apply_completed(paper_id, changed, action)` 시그널 emit → MainWindow가 counts/source_nav/status_bar 재갱신
- 실패 시 버튼에 'Failed' + tooltip에 에러 메시지

### 4.4 PaperList StatusPillDelegate

```python
_STATUS_STYLES = {
    'processed': (green_40_alpha, green,  'processed'),
    'pending':   (gray_46_alpha,  gray,   'pending'),
    'failed':    (red_38_alpha,   red,    'failed'),
    'review':    (amber_38_alpha, amber,  'review'),
    'none':      (...,            ...,    '—'),
}
```

`QStyledItemDelegate.paint()`에서 `drawRoundedRect` + `drawText`로 pill을 그린다.
`load_library('needs_review')`일 때만 status 셀을 `'review'`로 override해서 badge가 review 색으로 나오게 함.

## 5. 검증

### 5.1 Import 환경 이슈

첫 실행 시 `PyQt6.QtGui` 로드 실패:

```
ImportError: undefined symbol: _ZN5QFont11tagToStringEj, version Qt_6
```

원인: `PyQt6 6.6.1` 바인딩이 `PyQt6-Qt6 6.11.0` 런타임과 어긋남. `QFont::tagToString`은 Qt 6.7+에 추가된 심볼.
조치: `pip install --upgrade 'PyQt6>=6.7'` → `PyQt6 6.11.0` 설치, requirements.txt도 `PyQt6>=6.7,<6.12`로 갱신.

### 5.2 Headless smoke test

- Import OK
- `QApplication` + `MainWindow` 생성/`show()`/`exec()` 200ms → exit 0
- Services 쿼리 동작 확인:
  - `library.load_library_folders()` → 6 폴더 카운트 정상
  - `source_service.load_source_tree()` → 2 source (directory 1 + zotero 1), 45 collection roots
  - `paper_service.list_by_library(key)` → all/pending/processed/failed/recent 모두 정상 (초기 needs_review=0, 예상됨)
  - `paper_service.load_detail(paper_id)` → Paper + latest biblio flattened

### 5.3 스크린샷 검증

`/tmp/pm_shots/` 7장 캡처, 주요 뷰 확인:

- `01_initial.png` — 초기 상태, All Files 로드
- `03_processed_selected.png` — Processed 폴더 + 첫 row 선택, detail panel 렌더
- `04_detail_auto_commit.png` — Paper #4 (auto_commit 케이스) — Decision 라인 "auto-commit (all P08 gates passed)", Primary 버튼 enabled
- `05_detail_override_conflict.png` — Paper #6 (override_conflict) — Decision 라인 "needs review — override_conflict", 버튼 여전히 클릭 가능 (manual override)
- `06_badges_processed.png` — Processed 뷰에서 초록 "processed" pill 렌더링
- `07_badges_failed.png` — Failed 뷰에서 빨간 "failed" pill 렌더링

### 5.4 Decision 샘플 검증

6개 action × reason 조합을 실제 데이터에서 찾아 preview 확인:

```
paper=4    auto_commit     — "All checks passed"
paper=6    needs_review    override_conflict
paper=17   needs_review    missing_year
paper=18   needs_review    missing_authors
paper=19   needs_review    low_confidence
paper=206  needs_review    missing_title
```

모두 정책대로 동작.

## 6. 알려진 이슈 / 다음 세션 숙제

- [ ] **실제 apply를 아직 돌리지 않음**. 현재 상태는 "코드상 루프 완성 + 0건 apply". 사용자 직접 검증 후 좁은 범위(예: --paper 4)로 시작하는 게 안전.
- [ ] DetailPanel 너비(420)가 7-authors 같은 긴 문자열을 눌러 렌더가 조금 빡빡함. `QLabel.setWordWrap(True)`는 걸려 있지만 grid 컬럼 stretch 재조정 필요 가능.
- [ ] `P08 §4.3 DOI-based forced override`는 구현 안 됨 (opt-in 설정 경로도 없음). Phase 5+에서.
- [ ] batch "Reflect Biblio" 트리거 (source/folder 우클릭 → dry-run → 결과 다이얼로그 → 확정)는 미구현. services는 이미 준비되어 있으니 UI만 붙이면 됨.
- [ ] OCR 미리보기 카드가 아직 placeholder. `~/.papermeister/ocr_json/{hash}.json`에서 `markdown` 필드를 읽어 보여주는 컴포넌트 필요.
- [ ] Review queue 뷰는 "Needs Review" Library 폴더 하나로만 노출되어 있음. reason별 그룹핑은 Phase 6.
- [ ] PaperBiblio → Zotero write-back 정책 문서 미작성 (Phase 6 착수 시점).
- [ ] 기존 `papermeister/ui/` (legacy) vs 새 `desktop/` 양립 상태 — 언제 legacy를 retire할지는 Phase 5/6 완료 후 재판단.

## 7. 배운 점

### 7.1 "무엇이 이미 돼 있는가"를 먼저 쓴 것이 컸다

P07 초안이 Phase 1~6을 linear하게 쓰면서 "전부 미구현"처럼 보이게 만들었다. 현재 구현 상태 audit 테이블을 추가한 순간, Phase 1~2의 80%가 이미 완료돼 있고 실제 남은 작업은 "정책 + UI 통합"이라는 게 명확해졌다. 계획 문서는 **과거 완료된 것**을 명시해야 **미래에 할 것**이 가벼워진다.

### 7.2 entity × state machine은 flat list보다 UI 매핑이 쉽다

P07 초안에 flat status list(`pending|processed|failed|needs_review|promoted|writeback_pending`)가 있었는데, 구현 단계에서 "이게 어느 테이블의 컬럼이냐"로 헷갈렸다. 각 entity가 별개 state machine을 가지고 UI Library 폴더는 그들의 **조합 쿼리**로 정의한다고 못박으니 `list_by_library('needs_review')` 구현이 한 줄 쿼리로 줄어들었다.

### 7.3 Paper stub vs curated 구분을 데이터 모델보다 정책으로 해결한 게 맞았다

사용자가 지적한 "filesystem import는 Paper 상당이 없다"는 문제를 처음엔 데이터 모델 추가(Paper.is_stub 컬럼?)로 풀까 했지만, derived view로 돌린 게 깨끗했다. `year is null AND Author 없음`은 쿼리 한 줄이고 마이그레이션도 없다. 정책은 데이터가 아니다.

### 7.4 custom QSS는 생각만큼 무겁지 않다

qt-material/fluent-widgets를 검토했지만 custom QSS + design token 조합이 실제로는 한 파일(`qss.py`, 6,750자)로 끝난다. 의존성 0, 다크/라이트 swap은 dict 교체, 컴포넌트별 objectName 기반 스타일링이 명시적. 외부 테마의 "이건 이렇게 생길 수밖에 없다"는 제약을 받지 않는다.

### 7.5 services 경계를 처음부터 그은 게 결정적이었다

views가 peewee를 모르게 하는 규약이 구조적으로 많은 버그를 막았다. `list_by_library`의 JOIN 문법 에러가 나도 views는 예외 처리만 하면 되고, `preview_apply`가 추가되어도 detail_panel은 dataclass만 받는다. Phase 5에서 검색/Phase 6에서 review queue가 추가돼도 같은 경계가 유지될 것.

## 관련 문서

- [P07 데스크탑 소프트웨어 구현 계획 (개정)](./20260410_P07_Desktop_Software_Implementation_Plan.md)
- [P08 PaperBiblio → Paper 반영 정책](./20260411_P08_PaperBiblio_Reflection_Policy.md)
- [P09 새 데스크탑 앱 UI 설계](./20260411_P09_New_Desktop_UI_Design.md)
- [P06 데스크탑 MVP 기능 정의](./20260409_P06_Desktop_MVP_Feature_Definition.md)
