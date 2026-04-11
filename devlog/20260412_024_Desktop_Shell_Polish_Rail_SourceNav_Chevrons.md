# 024: Desktop 앱 첫 실행과 쉘 손보기 — Rail, PaperList, SourceNav, Tree Chevrons

[023](./20260411_023_Phase2_Cleanup_And_Needs_Review_Helper.md)에서 Phase 2를 닫은 후, HANDOFF에 "desktop GUI 실제 실행 + 버튼 클릭 실증이 아직 안 됨"으로 남아 있던 blocker를 **Windows + Anaconda 환경**에서 처음 실행하며 드러난 쉘 레벨 버그들을 한 바퀴 정리한 세션.

## 컨텍스트

환경이 WSL에서 Windows로 옮겨졌다. 019에서 스캐폴드만 잡아둔 `desktop/` 패키지를 사용자가 처음으로 **눈으로 보면서** 조작하기 시작했고, 그 순간 WSL display forwarding에 가려져 있던 UI 버그들이 줄줄이 드러났다. 이 세션의 작업은 전부 "시각적으로 돌려봤을 때 잘못된 부분"을 발견 → 수정 → 다음 문제로 이동하는 루프였다.

## 1. Rail (좌측 아이콘 바) — 이모지 렌더 실패 + wiring 누락

### 증상

> 제일 왼쪽에 아이콘 같은 게 네 개 보이는데 위의 두 개는 비어있고 세번째 것은 톱니바퀴 모양인데 Process 라고 툴팁이 나오고 그 아래는 ... 이라고 쓰여 있는데 Setting 이라고 툴팁이 나와. [...] 넷 다 아무런 변화도 일으키지 않아.

두 가지 문제가 겹쳐 있었다.

### (a) 이모지 폰트 부재

`desktop/components/sidebar.py`의 원래 코드:

```python
SECTIONS = [
    ('library', '📚', 'Library'),
    ('search',  '🔍', 'Search'),
    ('process', '⚙',  'Process'),
    ('settings','⋯',  'Settings'),
]
```

Windows 기본 Qt 폰트(Segoe UI)는 `📚`(U+1F4DA), `🔍`(U+1F50D) 같은 **이모지 plane**을 렌더하지 못해서 빈칸으로 표시됐다. 반면 `⚙`(U+2699), `⋯`(U+22EF)는 일반 심볼 영역이라 정상 표시되어 "위 두 개는 비어있고 아래 두 개는 보인다"는 증상이 나왔다.

### (b) `section_changed` 시그널이 연결 안 됨

`main_window.py`의 `_wire_events()`:

```python
def _wire_events(self):
    self.source_nav.selection_changed.connect(self._on_nav_selection)
    self.paper_list.paper_selected.connect(self.detail_panel.show_paper)
    self.detail_panel.apply_completed.connect(self._on_apply_completed)
    # ← rail.section_changed 연결이 통째로 누락
```

시그널 자체는 버튼 클릭 시 `emit` 되고 있었지만 받는 쪽이 없어서 `QButtonGroup`의 체크 상태만 토글될 뿐 실제 동작이 전혀 일어나지 않았다. 019 스캐폴드 단계에서 "다음 세션에 연결" 수준으로 남겨두고 P07 매트릭스에도 이 누락이 반영 안 됐음.

### 해결 방향 결정 — 옵션 A 채택

세 가지 옵션을 제시했다:

1. **Segoe UI Emoji 폰트 강제** — 이모지 유지, 톤 깨짐
2. **단색 심볼로 교체** — `▤` / `⌕` / `⚙` / `☰` 등
3. **SVG 아이콘 도입** — `QIcon` 기반, 프로덕트급

사용자 선택: **③ SVG**. 에셋 파이프라인 추가지만 어차피 나중엔 해야 할 일이고, 색 tinting/상태별 렌더가 가능해서 추후 확장이 쉽다.

섹션 동작 설계도 함께 정리:

- **옵션 A** (채택): Library/Search는 인라인 모드, Process/Settings는 **기존 동결 GUI의 `ProcessWindow` / `PreferencesDialog` 재사용** 다이얼로그
- 옵션 B: 네 섹션 모두 `QStackedWidget`으로 좌측 패널 교체 (일관성 ↑, 작업량 ↑↑)

A를 고른 이유는 명확하다. HANDOFF가 "Phase 4 hookup은 Apply Biblio 단일 경로 외엔 미완"이라고 못박고 있으니, 지금은 **동작하는 쪽으로 빠르게 실증**하는 타이밍이고, 기존 검증된 다이얼로그를 재활용하면 작업량이 최소화된다. 동결된 `papermeister/ui/`의 실익이 여기서 드러남.

### 구현

**SVG 4개 추가** (`desktop/theme/icons/`):
- `library.svg` — Lucide `book` (열린 책)
- `search.svg` — 돋보기
- `process.svg` — CPU chip (gear는 설정 아이콘 관습과 충돌해서 회피)
- `settings.svg` — Lucide `settings` gear

전부 `stroke="currentColor"`로 작성해서 런타임 색 치환이 가능하게 했다.

**`desktop/theme/icons.py` 신설** — SVG 문자열의 `currentColor`를 실제 HEX로 치환 후 `QSvgRenderer`로 `QPixmap` 렌더:

```python
def rail_icon(name: str, size: int = 20) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render_svg(name, COLORS_DARK['text.secondary'], size),
                   QIcon.Mode.Normal, QIcon.State.Off)   # idle
    icon.addPixmap(_render_svg(name, COLORS_DARK['accent.primary'], size),
                   QIcon.Mode.Normal, QIcon.State.On)    # checked
    icon.addPixmap(_render_svg(name, COLORS_DARK['text.primary'], size),
                   QIcon.Mode.Active, QIcon.State.Off)   # hover
    return icon
```

한 파일의 SVG에서 3-state 아이콘이 나온다. 다크/라이트 테마 스왑도 같은 메커니즘으로 확장 가능.

**Rail 리팩터** — 모드와 액션 분리:

```python
MODES = [
    ('library', 'library', 'Library'),
    ('search',  'search',  'Search'),
]
ACTIONS = [
    ('process',  'process',  'Process'),
    ('settings', 'settings', 'Settings'),
]
```

- 모드(Library/Search): `QButtonGroup(exclusive=True)`, checkable, `section_changed(key)` 시그널
- 액션(Process/Settings): non-checkable, `action_triggered(key)` 시그널
- 사이에 `addStretch(1)`로 상하 분리 → VSCode/Zed 스타일

액션 버튼을 non-checkable로 둔 이유: Process/Settings는 **순간 작업**이지 지속 모드가 아님. 클릭 후 체크 상태가 남아 있으면 "내가 Settings 모드에 있다"는 잘못된 멘탈 모델을 주게 된다.

**MainWindow 핸들러**:

```python
def _on_rail_section(self, section: str):
    if section == 'library':
        self.source_nav.setFocus()
    elif section == 'search':
        self.search_bar.setFocus()
        self.search_bar.selectAll()

def _on_rail_action(self, action: str):
    if action == 'process':
        self._open_process()
    elif action == 'settings':
        self._open_preferences()
```

`_open_process()`는 `PaperFile.status='pending'` 조회 → 0개면 "No pending files" 메시지, 있으면 `QMessageBox.question`으로 개수 확인 → **기존 `papermeister/ui/process_window.ProcessWindow`를 lazy-init으로 띄운다**. `processing_updated` 시그널로 status bar 카운트 자동 갱신까지 연결.

`_open_preferences()`는 `papermeister/ui/preferences_dialog.PreferencesDialog` modal exec 단 한 줄.

### 후속 피드백 — "아이콘 너무 작아"

초기 사이즈(rail.width=44, button 36×36, icon 20×20)가 Windows 네이티브 DPI에서 작아 보였다. 바꾼 값:

- `LAYOUT['rail.width']`: 44 → **52**
- 버튼: 36×36 → **44×44**
- 아이콘: 20 → **26** (`rail_icon(name, size=26)`, 픽스맵 자체를 크게 렌더해서 선명도 유지)

`QIcon.addPixmap`에 큰 픽스맵을 넣으면 축소 렌더링에서 오는 뭉그러짐이 없다. Qt가 필요 시 downscale만 한다.

## 2. PaperList — 컬럼 리사이즈/순서/축소

### 요구사항 (순차)

1. 컬럼 폭 조절 가능하게
2. Authors와 Title 위치 바꿈, Title 넓게 / Authors 좁게
3. Source 컬럼 제거
4. Status 컬럼 축소

### 컬럼 순서 + 리사이즈 모드

기존: `Status | Title | Authors | Year | Source`
- Status: `ResizeToContents` (드래그 무시됨)
- Title: `Stretch`
- Authors: `Interactive`, 260
- Year: `ResizeToContents` (드래그 무시됨)
- Source: `Interactive`, 160

변경 후: `Status | Authors | Title | Year`
- Status: `Interactive`, 60 (→ "작게")
- Authors: `Interactive`, 160 (→ "좁게")
- Title: `Stretch` (→ "넓게", 남은 공간 전부)
- Year: `Interactive`, 64
- **`setStretchLastSection(False)`** — 이게 켜져 있으면 Qt가 마지막 컬럼을 자동 확장해서 Title의 Stretch 설정과 충돌함

모두 `Interactive`로 바꾼 게 핵심. `ResizeToContents`는 사용자가 헤더 경계를 잡고 드래그해도 즉시 원복되어서 "조절 안 된다"는 경험을 만든다.

### Status pill 축소

Status 컬럼을 줄이려면 pill delegate 자체도 같이 줄여야 했다. 기존 `'processed'` 라벨은 폰트 xs에서 ~60px + pad 20 + offset 10 = 약 90px. 컬럼 60에 클립됨.

라벨 단축:

| 기존 | 변경 |
|------|------|
| `processed` | `done` |
| `pending`   | `wait` |
| `failed`    | `err`  |
| `review`    | `rev`  |

그리고 `pad_x`를 10→6, pill offset 10→6으로 줄여서 전체 pill 폭이 컬럼 60에 여유 있게 들어가게 했다. `sizeHint` 최소 폭도 100→56.

### "왜 Pending 논문 제목 앞에 `----` 이 붙어?"

별도로 지적된 버그. 원인:

```python
title = row.title if not row.is_stub else f'— {row.title}'
```

이건 하이픈 4개가 아니라 **em-dash 한 글자**(`—`, U+2014)다. 폰트에 따라 길어 보여서 `----`처럼 착시. 원래 의도는 "stub 논문임을 시각적으로 알리는 prefix". 하지만 같은 렌더에서 빈 필드 플레이스홀더로도 `—`를 쓰고 있어서(Authors, Year, Source가 비면 `—`) **"제목 필드가 비었다"로 오해**를 만든다.

더 큰 문제는 `_is_stub()` 판정이 생각보다 관대하다는 것:

```python
def _is_stub(paper: Paper) -> bool:
    return (
        (paper.title or '').strip() == '' or
        paper.year is None
    ) and Author.select().where(Author.paper == paper).count() == 0
```

**(제목이 비었거나 year=None) AND 저자 0명** → stub.

Zotero에서 방금 pull한 pending 논문들은 title은 있지만 year/authors가 아직 안 채워진 경우가 많다. 이들이 전부 stub으로 판정되어 `— Title` prefix가 붙고 있었다.

해결: prefix 제거. Stub 표시는 이미 italic 폰트로 하고 있으니 중복. 빈 필드 플레이스홀더와 시각 충돌도 해소.

```python
# Stub papers are conveyed via italic; no text prefix (it looked like
# an empty-field placeholder next to real em-dash blanks).
title = row.title
```

## 3. SourceNav — 두 섹션 스택 → QTabWidget

### 요구사항

> Sources 는 왼쪽 컬럼의 탭으로 만들어줘. 현재는 Zotero 만 있으니까 Zotero 를 탭의 제목으로 만들어주고, Library 는 hierarchical 한 폴더(컬렉션) 구조를 보여줘.

### 구조 재작성

기존 구조:

```
[LIBRARY 헤더]
library_tree (flat: All/Pending/Processed/Failed/Needs Review/Recent)
[SOURCES 헤더]
sources_tree (Zotero root → source → folders)
```

새 구조:

```
[Zotero]  ← QTabWidget 탭 (source별 한 개)
┌─────────────────────┐
│ All Files    11,978 │  ← Library 필터 섹션
│ Pending OCR   7,481 │
│ Processed     4,494 │
│ Failed            3 │
│ Needs Review     31 │
│ Recently Added 9,783│
│ COLLECTIONS         │  ← 구분 헤더 (비활성)
│ Zotero (6518039)    │  ← 소스 루트
│   ▶ 0. Antarctic... │  ← hierarchical 컬렉션
│   ▶ 0. Estaingia... │
│   ...               │
└─────────────────────┘
```

- `QTabWidget` + `setDocumentMode(True)` — 탭바가 본문과 경계선 없이 매끄럽게 붙음
- Source 하나당 탭 하나. 각 탭은 `_new_tree()`로 만든 `QTreeWidget`에 Library 필터 상단 + `COLLECTIONS` 구분 헤더 + 계층 컬렉션 하단 순으로 populate
- `selection_changed(kind, value)` 시그널과 세 kind(`library`/`source`/`folder`)는 **완전히 그대로 유지** → `MainWindow._on_nav_selection()` 수정 불필요. 시그니처 호환을 지키는 리팩터.
- Source 0개 fallback: 단일 `Library` 탭만 표시 (빈 패널 방지)

### QSS 탭 스타일

Linear/Zed 스타일로:

```
#SourceTabs QTabBar::tab:selected {
    color: {text.primary};
    border-bottom: 2px solid {accent.primary};
}
```

선택된 탭은 하단 2px accent blue 밑줄, 비선택은 muted gray, hover는 primary. 배경/테두리는 제거.

## 4. 보너스 버그 — "컬렉션이 flat하게만 보여"

### 증상

탭 전환까지 정상인데, `Zotero (6518039)` 하위의 45개 top-level 컬렉션만 펼쳐지고 **그 아래 자식 컬렉션들이 안 보임**. "flat"하다는 리포트.

### 진단

먼저 데이터가 flat한지 확인:

```
source 2 (Zotero (6518039)): 543 folders, 45 roots, 498 with parent
```

DB 원본은 계층 정상. 다음으로 `source_service.load_source_tree()` 출력:

```
Source 2 Zotero (6518039): 45 roots
  root: 0. Antarctic Trilobite  children=8
  root: 0. Estaingia taphonomy  children=4
  ...
```

서비스 레이어 출력도 정상. 그러면 렌더 단계 문제다. `QApplication`을 offscreen 모드로 띄워서 `QTreeWidget.invisibleRootItem()`을 직접 탐색:

```
top-level count: 8
  [7] 'Zotero (6518039)'  children=45
      [0] '0. Antarctic Trilobite'  grandchildren=8
      [1] '0. Estaingia taphonomy'  grandchildren=4
      ...
```

**트리 위젯 데이터도 계층 정상**. `Zotero (6518039)`가 45개 children을 가지고, 각 child가 grandchildren을 가진다. 즉 데이터는 완벽. 그러면 남은 건 **렌더 시 펼치기 화살표가 안 보이는 것**뿐.

### 원인 — `border-image: none`에 대체 이미지 없음

`desktop/theme/qss.py`의 branch 규칙:

```css
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    border-image: none;
}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings  {
    border-image: none;
}
```

Qt의 기본 branch indicator는 작은 삼각형인데, 이 규칙이 `border-image: none`으로 그걸 **지우기만 하고 대체 이미지를 지정하지 않아서** 자식이 있는 항목에도 아예 chevron이 렌더되지 않았다. 사용자는 펼칠 수 있다는 힌트 자체를 못 받는다. 클릭해도 (펼쳐지긴 하는데) 화살표가 회전하는 시각 피드백이 없어서 "flat"으로 느껴짐.

019 스캐폴드 단계에서 "Qt 기본 dotted branch 이미지가 보기 싫어서 제거"까지만 하고 대체를 넣지 않은 흔적. 시각 검증이 없었다는 증거.

### 해결

SVG chevron 두 개 추가:

- `desktop/theme/icons/chevron-right.svg` — 접힘 상태, stroke `#8A8F9A` muted
- `desktop/theme/icons/chevron-down.svg` — 펼침 상태

QSS에 경로 주입해야 하는데, QSS `url()`은 런타임에 파일을 읽으므로 절대경로가 필요하다. `qss.py`에 헬퍼 추가:

```python
_ICONS_DIR = Path(__file__).parent / 'icons'

def _icon_url(name: str) -> str:
    return (_ICONS_DIR / name).as_posix()
```

`Path.as_posix()`를 쓰는 이유: Windows에서 `\\` 구분자가 나오면 QSS url() 파싱이 깨진다. Qt는 Windows에서도 forward slash 경로(`C:/Users/...`)를 잘 먹는다.

그리고 f-string으로 주입:

```python
chevron_right = _icon_url('chevron-right.svg')
chevron_down = _icon_url('chevron-down.svg')
return f"""
...
QTreeView::branch:...closed {{
    border-image: none;
    image: url({chevron_right});
}}
QTreeView::branch:...open {{
    border-image: none;
    image: url({chevron_down});
}}
"""
```

검증:

```
chevron-right: /mnt/d/projects/PaperMeister/desktop/theme/icons/chevron-right.svg exists= True
chevron-down:  /mnt/d/projects/PaperMeister/desktop/theme/icons/chevron-down.svg exists= True
qss length: 7502
has chevron-right url: True
```

## 배운 점

### 실행 안 해본 UI는 망가진 UI

019에서 `desktop/` 스캐폴드를 만들 때 WSL 환경에서 **렌더 검증 없이** 코드만 썼다. 이번 세션에서 Windows로 옮기면서 한 번 띄우자마자 네 건의 독립 버그가 드러났다:

1. 이모지 폰트 부재 → 아이콘 빈칸
2. `rail.section_changed` wiring 누락 → 버튼 무반응
3. 아이콘 크기 부적절 → "너무 작음" 피드백
4. Branch chevron 누락 → 트리 flat으로 보임

이 넷 다 코드 리뷰로는 절대 안 잡혔을 문제들이다. (1)은 "내 맥에서는 되는데" 클래스, (2)는 빠뜨린 것 자체는 코드 리뷰로 잡힐 수 있지만 "버튼이 안 눌린다"는 증상이 없으면 우선순위가 안 올라감, (3)은 순수 시각 감각, (4)는 데이터가 정상이고 QSS만 봐서는 "대체 이미지 없음"이 즉시 명백하지 않음.

교훈: **프론트엔드 코드는 한 번이라도 띄워보기 전엔 "작성 중"이다**. HANDOFF에 "buttonA 누르면 X가 뜬다"를 완료로 적을 수 없다 — 실제로 버튼을 눌러본 적이 없으면 그건 가설이다. Phase 4 hookup 항목들도 같은 기준으로 체크해야 한다 (작성 후 한 번 눌러봤는가?).

WSL Qt display forwarding을 구축하는 것과 Windows 네이티브로 넘어가는 것 중 후자가 훨씬 빨랐다. Windows 이식성 체크를 020에서 해둔 게 이 시점에 값어치를 했다 — tar.gz 풀고 conda env 만들면 바로 뜬다.

### 동결된 코드의 실익은 재사용 지점에서 드러난다

P09에서 `papermeister/ui/`를 동결로 선언할 때는 "새 코드 진행에 방해되지 않게 격리"라는 defensive 동기였다. 하지만 오늘 Rail 액션 버튼을 연결할 때, **동결된 `ProcessWindow`와 `PreferencesDialog`를 그대로 import해서 띄우는 것**으로 Phase 4의 Process/Settings 경로를 거의 공짜로 얻었다.

만약 `papermeister/ui/`가 동결이 아니라 "리팩터 중"이었다면 두 가지 나쁜 시나리오가 가능했다:
1. 새 desktop 앱 작업 중 기존 다이얼로그가 중간 상태로 망가져서 재사용 불가
2. "어차피 리팩터할 거니까 새 다이얼로그도 새로 쓰자" → 작업량 2배

동결의 가치는 "바뀌지 않는 안정적인 재사용 지점"을 남기는 것. 지금은 옵션 A(기존 다이얼로그 재사용)가 옵션 B(모두 스택 뷰 신규)보다 훨씬 빠른 Phase 4 진행을 만들어준다. 나중에 정식으로 desktop 쪽에서 프레퍼런스/프로세스 뷰를 다시 쓰고 싶어질 때 그때 마이그레이션하면 된다 — 그때까진 동결 코드가 실사용 중.

### "데이터 flat"과 "렌더 flat"을 구분하자

사용자가 "컬렉션이 flat하게 top level만 보이네"라고 했을 때, 첫 인스팅트는 `source_service.load_source_tree()`의 parent 처리 버그를 의심하는 것이었다. 그 버그도 실제로 있었을 법한 자리다 (peewee FK 접근은 `.parent_id` vs `.parent.id`로 갈리고, 둘 다 엣지 케이스가 있다).

그래서 **밑에서부터 위로** 검증 레이어를 하나씩 쳤다:

1. Raw DB (`SELECT parent_id FROM folder`) → 45 roots, 498 with parent ✓
2. `source_service.load_source_tree()` Python 구조 → 각 root의 `children` 리스트 정상 ✓
3. `QTreeWidget.invisibleRootItem()` 재귀 탐색 → 아이템 트리도 계층 정상 ✓

세 레이어가 전부 정상이면 남은 건 **렌더** 하나. 그 시점에 QSS 파일을 열어서 branch 규칙을 확인했고 즉시 원인이 보였다. 만약 1~2단계를 스킵하고 바로 "source_service 버그겠지"로 뛰어들었다면 엉뚱한 곳을 고치고 있었을 것이다.

원칙: **"flat하게 보인다"는 시각 증상이지 데이터 증상이 아니다**. 증상이 시각 레이어에 있으면 원인도 거의 항상 시각 레이어에 있다. 데이터 레이어를 의심하는 건 빠른 검증으로 데이터가 정상임을 확인한 후에만.

### 빈 값 기호와 의미 기호가 겹치면 사용자가 헷갈린다

`—` (em-dash)를 두 곳에서 다른 의미로 썼다:

- `row.authors or '—'` → "이 필드는 비어있다"
- `f'— {row.title}'` → "이 논문은 stub이다"

같은 글자를 보는데 한 자리에서는 "없음"을 의미하고 다른 자리에서는 "어떤 속성"을 의미한다. 사용자가 헷갈리는 건 당연하다. 특히 Authors 컬럼에 `—`가 떠 있고 같은 행의 Title 컬럼에 `— Lorem Ipsum`이 떠 있으면, 이 Title도 "일부가 비었다"로 해석된다.

교훈: UI에서 특수 문자는 **딱 한 가지 의미**만 가져야 한다. Stub 표시는 이미 italic 폰트로 하고 있었으니 prefix는 순전히 중복이었고, 빼는 게 정답이었다. 만약 stub을 "더 강하게" 표시하고 싶었다면 별도 배지나 배경 색조 같은 완전히 다른 시각 채널을 썼어야 한다.

## 관련 문서

- [023 Phase 2 뒷정리](./20260411_023_Phase2_Cleanup_And_Needs_Review_Helper.md) — 직전 세션, 서비스/데이터 레이어 마무리
- [019 Desktop 스캐폴드 + P08 러너](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md) — 오늘 버그가 나온 원 스캐폴드
- [P09 Desktop UI 설계](./20260411_P09_New_Desktop_UI_Design.md) — 4-layer 구조, design tokens, 화면별 상태/액션 매트릭스
- [P07 구현 계획](./20260410_P07_Desktop_Software_Implementation_Plan.md) — Phase 4 hookup 범위
