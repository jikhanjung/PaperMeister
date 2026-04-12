# 026: PaperFolder M2M, Zotero Incremental Sync, SourceNav Rework

**날짜:** 2026-04-12 (세션 13)

## 요약

Zotero의 multi-collection membership을 지원하기 위해 `PaperFolder` junction table을 도입하고, library-wide incremental item sync를 구현하고, 좌측 SourceNav 패널을 Collections/Status 2-section 구조로 재구성했다.

## 변경사항

### 1. PaperFolder junction table (P10)

**문제:** `Paper.folder`가 단일 FK라 Zotero item이 여러 컬렉션에 소속되어도 첫 번째 sync된 컬렉션 하나만 기록됨. `fetch_zotero_collection_items()`가 `zotero_key`로 global dedup하므로 두 번째 이후 컬렉션에서는 skip.

**해결:**
- `PaperFolder(paper FK, folder FK)` 모델 추가 (unique composite index)
- `Paper.folder`는 유지 (backward compat, primary collection)
- `database._migrate()`에서 기존 `Paper.folder` → PaperFolder 자동 backfill (9,783건)
- backfill 시 `paperfolder_needs_full_sync` pref 세팅 → 다음 sync에서 full item fetch

### 2. Zotero API `collections` 필드 전달

- `_parse_item_metadata()` 반환 dict에 `'collections': data.get('collections', [])` 추가
- standalone PDF에도 동일 적용
- `get_collection_items()` 내부를 `_classify_raw_items()` + `_build_results()`로 리팩토링 (코드 재사용)

### 3. Library-wide incremental item sync

**이전:** collections만 sync, items는 컬렉션 클릭 시 개별 fetch (543개 컬렉션 × API 1회)

**이후:**
- `ZoteroClient.get_all_items(since=version)` — `zot.items(since=N)`으로 변경분만 library-wide fetch
- `ingestion.sync_zotero_items()` — Paper 생성/갱신, PaperFile 생성, PaperFolder membership 구축
  - 새 Paper: `item['collections']`의 첫 번째 collection을 primary folder로 설정
  - 기존 Paper: title/date/year/journal/doi 갱신
  - orphan attachments (incremental에서 parent 없이 attachment만 온 경우) 별도 처리
- `preferences.zotero_library_version`에 새 version 저장 → 다음 sync의 `since` 값

### 4. Desktop Sync 버튼 + Worker

- Rail에 **Sync** 액션 버튼 추가 (`sync.svg` Lucide refresh-cw 스타일)
- `ZoteroSyncWorker(QThread)` — `progress(str)` / `done(dict)` / `failed(str)` 시그널
  - Phase 1: collections (캐시 → API fresh)
  - Phase 2: items (incremental, full sync 플래그 있으면 since=None)
  - 진행률 실시간 status bar 표시: `"Syncing collections…"` → `"Processing 150 items…"` → `"[42/150] Title…"`
- Sync 중 아이콘 **opacity pulse 애니메이션** (QPropertyAnimation, InOutSine 900ms)
- `QThread.finished` 시그널을 safety net으로 연결 → animation 해제 보장
- **우클릭 → "Full Sync (re-fetch all items)"** context menu: `paperfolder_needs_full_sync=True` 세팅 후 sync
- 시작 시 자동 sync + Settings 저장 후 re-sync

### 5. Metadata 카드 — Collection 경로 표시

- `PaperDetail`에 `collections: list[tuple[int, str]]` 추가 (PaperFolder 기반)
- `PaperRow`에 `folder_id: int | None` 추가 (Ctrl+click용)
- Metadata 카드: Source 행 아래에 Collection 행 — `Parent › Child › Leaf` 형식, 다중이면 줄바꿈

### 6. Ctrl+click → SourceNav reveal

- `PaperListView.folder_reveal_requested(folder_id)` 시그널
- `itemPressed` + `ControlModifier` 감지
- `SourceNav.reveal_folder(folder_id)` — DFS 탐색 → 탭 전환 + 조상 expand + scrollTo + setCurrentItem
- `blockSignals`로 감싸서 `selection_changed` emit 안 함 → paper list 유지

### 7. SourceNav 재구성 (v4)

**이전:** 단일 QTreeWidget에 Library filters + COLLECTIONS 헤더 + 컬렉션 트리 혼합

**이후:**
- Collections tree (QTreeWidget, scrollable, 상단)
- `_StatusPanel` (하단 고정, 탭 바깥):
  - 클릭 가능한 `"▼ STATUS"` / `"▶ STATUS"` 헤더 → 접기/펴기
  - 항상 하단에 보임 — 컬렉션 스크롤해도 밀리지 않음
  - All Files / Pending OCR / Processed / Failed / Needs Review / Recently Added
- Zotero source 탭 이름: `"Zotero (6518039)"` → `"My Library"`

## 수정 파일

| 파일 | 변경 |
|------|------|
| `papermeister/models.py` | `PaperFolder` 모델 |
| `papermeister/database.py` | `ALL_TABLES` + backfill migration |
| `papermeister/zotero_client.py` | `collections` 필드, `get_all_items()`, refactor |
| `papermeister/ingestion.py` | `sync_zotero_items()`, PaperFolder 생성 |
| `desktop/components/sidebar.py` | Sync 버튼, pulse animation, context menu |
| `desktop/services/paper_service.py` | `PaperRow.folder_id`, `PaperDetail.collections` |
| `desktop/views/detail_panel.py` | Collection 행 표시 |
| `desktop/views/paper_list.py` | `folder_reveal_requested` 시그널 |
| `desktop/views/source_nav.py` | 2-section 구조, `_StatusPanel`, `reveal_folder` |
| `desktop/windows/main_window.py` | ZoteroSyncWorker 배선, full sync, Settings re-sync |
| `desktop/workers/zotero_sync.py` | 전용 sync worker (신규) |
| `desktop/theme/icons/sync.svg` | sync 아이콘 (신규) |
| `devlog/20260412_P10_PaperFolder_Multi_Collection.md` | 계획 문서 |
