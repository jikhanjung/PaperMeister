# P09: 새 데스크탑 앱 UI 설계

## 문서 역할

[P07 Phase 3](./20260410_P07_Desktop_Software_Implementation_Plan.md)의 **선행 조건 설계 문서**.

- 어떤 UI 스타일/테마 스택을 쓸 것인가
- 레이아웃과 디자인 토큰은 무엇인가
- 화면별 상태/액션 매트릭스
- 기존 `papermeister/ui/`와의 경계

구현은 `desktop/` 패키지에서 이 문서를 따른다.

## 전제

- 기존 `papermeister/ui/` (PyQt6 3-pane)는 **동결**. 삭제/리팩토링하지 않는다.
- 새 앱은 `desktop/` 패키지에 둔다. 공용 로직은 `papermeister.*`에서 import하되, **양방향 import 금지** (기존 ui → desktop 경로는 없음).
- DB/OCR 캐시/Preferences는 동일 경로 공유 (`~/.papermeister/`).
- 엔트리포인트: `python -m desktop` 또는 `desktop/app.py`.

## 디자인 방향

### 참고 제품

- **Linear** — 조밀한 정보 밀도 + 얇은 border + subtle shadow
- **Raycast** — 강한 좌측 rail + 검색 바 우위
- **Zed / VS Code** — 3-pane + 상태바 + 키보드 중심
- **Zotero 7** — 같은 도메인, 참고할 만한 메타데이터 표현

핵심 느낌: **조용하고 밀도 높은 도구 앱**. 화려한 애니메이션/그라데이션은 배제.

### 테마 스택 결정

후보 평가:

| 스택 | 장점 | 단점 |
|------|------|------|
| qt-material | 즉시 modern, 무료 | opinionated, material 느낌 고정 |
| PyQt6-Fluent-Widgets | Windows 11 느낌, 예쁨 | 추가 의존성 무거움, PyQt6.6 호환성 확인 필요 |
| qdarkstyle | 간단 | dark-only, 구식 느낌 |
| **custom QSS + design tokens** | **무의존성, 완전 제어, 일관성** | 초기 작업 필요 |

**결정: custom QSS + design tokens**.

근거:
- 추가 의존성 없음 (`requirements.txt` 그대로)
- 디자인 토큰을 파이썬 dict로 관리 → 다크/라이트 테마 전환 쉬움
- material/fluent의 고정된 미적 감각에 종속되지 않음
- Linear/Zed/Raycast 류의 "조용한 도구" 느낌을 직접 구현 가능

단점인 "초기 작업"은 **토큰 + 기본 QSS 템플릿 한 번만 작성**하면 됨.

### 다크/라이트

- 시작은 **dark first** (학술 PDF 작업은 저녁 사용 빈도 높음)
- 라이트 테마는 토큰 swap으로 동일 QSS 재사용 가능하게 설계
- 시스템 테마 따라가기는 Phase 3.5

## 디자인 토큰

`desktop/theme/tokens.py`:

### Color (dark)

```python
COLORS_DARK = {
    # Surfaces
    'bg.app':        '#0F1115',  # window background
    'bg.panel':      '#151820',  # side panels
    'bg.elevated':   '#1B1F2A',  # cards, popovers
    'bg.hover':      '#222634',
    'bg.selected':   '#2A3044',

    # Borders
    'border.subtle': '#1F2230',
    'border.default':'#2B2F3D',
    'border.strong': '#3A3F52',

    # Text
    'text.primary':  '#E6E8EF',
    'text.secondary':'#A0A5B4',
    'text.muted':    '#6B7080',
    'text.inverse':  '#0F1115',

    # Accent
    'accent.primary':'#6D8EFF',  # soft indigo
    'accent.hover':  '#8BA4FF',
    'accent.muted':  '#2D3654',

    # Status
    'status.ok':     '#4ADE80',
    'status.warn':   '#FBBF24',
    'status.error':  '#F87171',
    'status.info':   '#60A5FA',
    'status.pending':'#6B7080',
}
```

### Spacing (4px grid)

```python
SPACING = {
    'xxs': 2, 'xs': 4, 'sm': 8, 'md': 12,
    'lg': 16, 'xl': 24, 'xxl': 32, 'xxxl': 48,
}
```

### Radius

```python
RADIUS = {'sm': 4, 'md': 6, 'lg': 10, 'xl': 14}
```

### Typography

```python
FONT = {
    'family.ui':   'Inter, -apple-system, Segoe UI, sans-serif',
    'family.mono': 'JetBrains Mono, SF Mono, Consolas, monospace',
    'size.xs':   11,
    'size.sm':   12,
    'size.md':   13,
    'size.lg':   14,
    'size.xl':   16,
    'size.xxl':  20,
    'weight.normal': 400,
    'weight.medium': 500,
    'weight.bold':   600,
}
```

## 레이아웃

### 전체 구조 (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [logo]  [ Search bar (⌘F)                    ]    [settings] [profile]  │  ← TopBar (h=48)
├────┬────────────────────────┬────────────────────────┬───────────────────┤
│ R  │ SourceNav              │ PaperList              │ DetailPanel       │
│ A  │  Library               │  status ◯ Title        │                   │
│ I  │  ├ All Files           │   Author · Year · Src  │   ┌─ Metadata ─┐  │
│ L  │  ├ Pending OCR    (12) │                        │   │ title...   │  │
│    │  ├ Processed   (2.1k) │                        │   │ authors... │  │
│ 4  │  ├ Failed          (3) │                        │   └────────────┘  │
│ 0  │  ├ Needs Review   (87) │                        │                   │
│ p  │  └ Recently Added      │                        │   ┌─ Biblio ───┐  │
│ x  │                        │                        │   │ diff view  │  │
│    │  Sources               │                        │   │ [Apply]    │  │
│    │  ├ Zotero              │                        │   └────────────┘  │
│    │  │  └ Collections...   │                        │                   │
│    │  └ Local               │                        │   ┌─ OCR ──────┐  │
│    │     └ Directories...   │                        │   │ preview    │  │
│    │                        │                        │   └────────────┘  │
├────┴────────────────────────┴────────────────────────┴───────────────────┤
│ [●] 2,143 papers · 12 pending · 87 needs review          [OCR: idle]    │  ← StatusBar (h=24)
└──────────────────────────────────────────────────────────────────────────┘
```

- 총 4개 컬럼: Rail (40) · SourceNav (260) · PaperList (flex) · DetailPanel (420)
- Rail은 아이콘 버튼만: Library/Search/Process/Settings — 향후 확장용
- SourceNav와 DetailPanel은 QSplitter로 리사이즈 가능, PaperList는 항상 flex
- TopBar는 상시 검색 바 (Phase 5 전까지는 비활성 플레이스홀더)

### 반응형 / 밀도

- 최소 윈도우: 1100×700
- 밀도 옵션 (Phase 3 이후): compact / cozy / comfortable → 토큰 swap

## 컴포넌트 카탈로그

### 기본 컴포넌트 (`desktop/components/`)

- `Sidebar` — 좌측 rail
- `SourceTree` — Library + Sources 이중 트리
- `SearchBar` — 상단 검색 입력 (mvp에서는 placeholder)
- `PaperListView` — QTreeView 기반, 커스텀 delegate
- `StatusBadge` — 상태 dot + 라벨 (ok/pending/processed/failed/review)
- `DetailPanel` — 세로 스크롤 카드 스택
- `BiblioDiffCard` — Paper vs Biblio diff + Apply 버튼
- `OCRPreviewCard` — 모노스페이스 텍스트, 페이지 navigation
- `StatusBar` — 하단 상태바
- `Toast` — 우측 하단 알림

### 위젯 → QSS class 매핑

모든 커스텀 위젯은 `objectName`을 설정해 QSS에서 `#objectName` 또는 `.className` 형태로 스타일 적용. 예:

```python
class StatusBadge(QLabel):
    def __init__(self, kind: str):
        super().__init__()
        self.setObjectName('StatusBadge')
        self.setProperty('kind', kind)  # QSS: [kind="ok"]
```

## 화면별 상태/액션 매트릭스

### 1. Library 폴더 선택

| 선택 | PaperList 내용 | 가능한 액션 |
|-----|----------------|------------|
| All Files | 전체 PaperFile | 정렬, 필터 |
| Pending OCR | `PaperFile.status='pending'` | "Process Selected" |
| Processed | `status='processed'` | "Extract Biblio", "Reflect Biblio" |
| Failed | `status='failed'` | "Retry", "Show reason" |
| Needs Review | `PaperBiblio.status='needs_review'` OR stub+추출됨 | "Review", "Apply" |
| Recently Added | 최근 30일 created_at | — |

### 2. Source 선택

| 선택 | PaperList 내용 | 가능한 액션 |
|-----|----------------|------------|
| Zotero root | 모든 컬렉션의 paper | "Sync All" |
| Zotero collection | 해당 collection의 paper | "Sync", "Process", "Extract Biblio" |
| Local root | 모든 local directory의 paper | — |
| Local folder | 해당 폴더의 paper | "Rescan", "Process", "Extract Biblio", "Reflect" |

### 3. Paper 선택 (DetailPanel)

| Paper 상태 | DetailPanel 카드 | 기본 액션 |
|-----------|------------------|---------|
| stub + no biblio | Metadata(stub placeholder), File info | "Extract Biblio" |
| stub + biblio available | + BiblioDiff | "Apply Biblio" |
| curated (Zotero) | Metadata(정상), BiblioDiff(있으면) | "Re-extract" |
| failed OCR | Metadata(stub), Failure reason | "Retry OCR" |

stub placeholder 예:
- title: italic "Untitled — filename.pdf"
- authors: "—"
- year: "—"
- 상단에 "Stub metadata. Run biblio extraction to fill." 배너

## 인터랙션 규칙

### 키보드

- `Cmd/Ctrl+F`: 검색 포커스
- `Cmd/Ctrl+1/2/3/4`: Library 폴더 전환
- `Enter`: paper 선택 → OCR 미리보기 확장
- `Space`: 빠른 미리보기 토글
- `Cmd/Ctrl+Enter`: Apply Biblio (가능할 때만)

### 선택 모델

- PaperList는 multi-select 지원 (Shift/Cmd)
- 다중 선택 시 DetailPanel은 "N papers selected" 요약 + batch 액션

### 로딩 / 빈 상태

- 빈 상태는 **설명 + primary action** 형태
  - "No papers yet. Add a source →"
  - "No biblio extracted. Run extraction →"
- 로딩은 skeleton row (absolute 회전 스피너 금지)

### 에러

- Toast (우측 하단)로 error/success
- 블로킹 에러는 다이얼로그 (예: DB migration 실패)

## 파일 구조

```
desktop/
├── __init__.py
├── __main__.py              # python -m desktop 진입점
├── app.py                   # QApplication + 초기화
├── theme/
│   ├── __init__.py
│   ├── tokens.py            # 색/spacing/font 토큰
│   └── qss.py               # 토큰 → QSS 문자열 생성
├── windows/
│   ├── __init__.py
│   └── main_window.py       # 최상위 QMainWindow
├── views/
│   ├── __init__.py
│   ├── source_nav.py        # Library + Sources 트리
│   ├── paper_list.py        # 중앙 리스트
│   └── detail_panel.py      # 우측 디테일
├── components/
│   ├── __init__.py
│   ├── sidebar.py           # 좌측 rail
│   ├── search_bar.py
│   ├── status_badge.py
│   ├── biblio_diff_card.py
│   ├── ocr_preview_card.py
│   └── status_bar.py
├── services/
│   ├── __init__.py
│   ├── library.py           # Library 폴더별 쿼리
│   ├── source_service.py    # source/folder 트리 로딩
│   ├── paper_service.py     # paper list 쿼리 + detail 로딩
│   └── biblio_service.py    # biblio_reflect 래퍼
└── workers/
    ├── __init__.py
    └── background.py        # QThread 래퍼
```

원칙:
- `views/`는 컴포넌트 조립 + 서비스 호출. DB 직접 접근 금지.
- `services/`는 `papermeister.*` 로직을 호출하고 UI에 적합한 형태로 변환.
- `components/`는 재사용 가능한 순수 위젯. 상태를 스스로 fetch하지 않음.
- `workers/`는 모든 비동기 작업의 단일 진입점. `view → service → worker → signal → view`.

## Phase 3 완료 기준 (이 설계 기반)

- [ ] `python -m desktop` 실행 시 윈도우 표시, 크래시 없음
- [ ] 토큰 → QSS 파이프라인 동작 (다크 테마 적용)
- [ ] 좌측 rail + SourceNav(Library + Sources 이중 트리) 표시
- [ ] PaperList 기본 컬럼 (status / title / authors / year / source) 표시
- [ ] DetailPanel의 3개 카드 (Metadata / Biblio / OCR) 정적 렌더
- [ ] StatusBar 기본 카운트 표시
- [ ] 기존 `papermeister/ui/` 와 완전 독립 실행

## 뒤로 미루는 것 (MVP 이후)

- 검색 결과 하이라이트 애니메이션
- PDF viewer 통합
- 설정 다이얼로그 전체
- 키보드 팔레트 (⌘K)
- 다중 윈도우

## 결론

P09는 두 가지를 정했다.

1. **디자인 스택**: 외부 테마 의존 없이 custom QSS + design token. "조용한 도구 앱" 지향.
2. **파일 구조와 레이어 경계**: views / services / components / workers 4계층, DB 직접 접근은 service 경계에서만.

이제 Phase 3 스캐폴딩은 이 문서의 파일 구조를 그대로 따른다.
