# 003: Zotero Integration 구현

**작성일:** 2026-03-31
**계획 문서:** `20260330_P02_Zotero_Integration.md`

---

## 완료 작업

### 모델 변경
- `Folder.zotero_key` — Zotero collection key
- `PaperFile.zotero_key` — Zotero attachment key
- `PaperFile.hash` — unique 제약 제거 (Zotero 파일은 OCR 시점에 hash 채움)
- `database.py`에 마이그레이션 추가 (zotero_key 컬럼 + hash unique 인덱스 제거)

### 신규 모듈
- **`papermeister/preferences.py`** — `~/.papermeister/preferences.json` 읽기/쓰기
  - `get_pref(key, default)`, `set_pref(key, value)`
- **`papermeister/zotero_client.py`** — pyzotero 래퍼 `ZoteroClient`
  - `test_connection()`, `get_collections()`, `get_collection_items()`, `download_attachment()`
  - `load_cached_collections()`, `save_collections_cache()` — 컬렉션 캐시
  - `get_collection_items()`가 API 1회 호출로 parent item + attachment를 한꺼번에 가져옴 (N+1 문제 해결)
  - `download_attachment()`는 `pyzotero.file()`로 직접 바이너리 다운로드 (`dump()` Windows 권한 문제 회피)

### 신규 UI
- **`papermeister/ui/preferences_dialog.py`** — RunPod + Zotero 자격증명 입력
  - RunPod Endpoint ID + API Key
  - Zotero User ID + API Key + Test Connection 버튼
- **`papermeister/ui/zotero_import_dialog.py`** — 컬렉션 선택 다이얼로그
  - 캐시에서 즉시 로드, Refresh 버튼으로 API 갱신
  - 체크박스 트리로 컬렉션 선택 → Import

### 수정 사항

#### `papermeister/ingestion.py`
- `sync_zotero_collections()` — 컬렉션 트리를 DB Folder로 동기화
- `fetch_zotero_collection_items()` — API 1회 호출로 Paper + PaperFile 생성
  - attachment 있으면 PaperFile(status='pending') 생성, 없으면 Paper만
  - PDF 다운로드 없음 (스캔 단계에서는 메타데이터만)

#### `papermeister/text_extract.py`
- `_resolve_filepath()` — Zotero 파일은 임시 다운로드
- `process_paper_file()`에 `status_callback` 추가
  - Zotero 다운로드/OCR/캐시 로드 단계별 상태 보고
  - Zotero 메타데이터는 API 데이터 우선 (PDF 메타데이터 덮어쓰지 않음)
  - hash 채우기: 다운로드 후 hash 계산 → OCR 캐시 확인

#### `papermeister/ocr.py`
- `.env`/`dotenv` 의존 제거 → `preferences.json`에서 RunPod 설정 읽음
- `reset_config()` 추가 (설정 변경 시 캐시 리셋)

#### `papermeister/ui/main_window.py`
- File 메뉴: "Import from Zotero..." (Ctrl+Z), "Preferences..." 추가
- `ZoteroCollectionSyncWorker` — 시작 시 + Preferences 저장 후 컬렉션 자동 동기화
- `ZoteroFetchItemsWorker` — 컬렉션 클릭 시 아이템 가져오기 (WaitCursor 표시)
- `ZoteroScanWorker` — Import from Zotero 메뉴용
- 가운데 패널 Status 컬럼: `pending`/`processed`/`failed`/`no PDF`

#### `papermeister/search.py`
- `get_papers_in_folder()`, `get_papers_in_source()` — LEFT_OUTER JOIN으로 PaperFile 없는 Paper도 표시

#### `main.py`
- `.env` → `preferences.json` 자동 마이그레이션 (1회)

#### `requirements.txt`
- `pyzotero>=1.5.0` 추가

## 해결한 이슈
- pyzotero `itemType` 필터 `-attachment -note` 사용 불가 → 코드 레벨 필터링
- pyzotero `dump()` Windows `Permission denied` → `file()`로 직접 바이너리 다운로드
- `mkdtemp` Windows 권한 문제 → `~/.papermeister/tmp/` 고정 디렉토리 사용
- `PaperFile.hash` unique 제약 → Zotero 파일은 hash='' 로 생성, OCR 시 채움
- N+1 API 호출 → `collection_items()` 1회로 parent+attachment 매칭

## Import Flow
```
시작 시 → Zotero 자격증명 있으면 컬렉션 구조 자동 동기화 → 소스 트리 표시
컬렉션 클릭 → API에서 아이템 목록 가져와 DB 저장 (PDF 다운로드 없음)
Process Pending → Zotero PDF 임시 다운로드 → OCR → 삭제 (캐시는 보존)
```
