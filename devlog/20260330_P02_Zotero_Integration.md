# P02: Zotero Integration 계획

**작성일:** 2026-03-30
**상태:** 계획 (구현 전)

---

## 목표

PaperMeister에 Zotero 연동을 추가하여 Zotero 라이브러리의 컬렉션/논문/PDF를 가져와 OCR 처리하고 DB에 저장한다.

## 핵심 결정 사항

| 항목 | 결정 | 이유 |
|------|------|------|
| Zotero API 라이브러리 | **pyzotero** | Python 표준 Zotero 클라이언트 |
| 인증 정보 저장 | `~/.papermeister/preferences.json` | JSON 파일, 가볍고 단순 |
| PDF 로컬 저장 | **안 함** | OCR 시 임시 다운로드만 수행, 디스크 낭비 방지 |
| PaperFile.path | 원본 파일명 저장 | UI 표시용 (`os.path.basename` 호환) |
| Zotero 메타데이터 | API 데이터 우선 | PDF 내장 메타데이터보다 정확 |
| 중복 체크 | hash 기반 (기존과 동일) | 같은 PDF 재임포트 방지 |
| 다운로드 시점 | 스캔 시 1회(hash용) + OCR 시 1회 | 캐시 있으면 OCR 시 다운로드 불필요 |

## 모델 변경

### `papermeister/models.py`
- `PaperFile`에 `zotero_key = TextField(default='')` 추가 — PDF 첨부파일의 Zotero key
- `Folder`에 `zotero_key = TextField(default='')` 추가 — collection key

### `papermeister/database.py`
- `_migrate()`에 `paperfile.zotero_key`, `folder.zotero_key` 컬럼 추가 마이그레이션

## 신규 파일

### 1. `papermeister/preferences.py`
- `~/.papermeister/preferences.json` 읽기/쓰기
- `get_pref(key, default)`, `set_pref(key, value)`
- 저장 항목: `zotero_user_id`, `zotero_api_key`

### 2. `papermeister/zotero_client.py`
- pyzotero 래퍼 클래스 `ZoteroClient(user_id, api_key)`
  - `test_connection()` → bool (인증 확인)
  - `get_collections()` → 컬렉션 트리 (key, name, parent_key)
  - `get_collection_items(collection_key)` → 논문 메타데이터 + 첨부파일 목록
  - `download_attachment(item_key)` → temp file path (caller가 삭제 책임)

### 3. `papermeister/ui/preferences_dialog.py`
- QDialog: Zotero User ID + API Key 입력 필드
- "Test Connection" 버튼으로 연결 확인
- Save / Cancel

### 4. `papermeister/ui/zotero_import_dialog.py`
- QDialog: Zotero 컬렉션 트리 표시 (체크박스 선택)
- "Import" 버튼 → 선택된 컬렉션의 아이템+PDF 가져오기

## 수정 파일

### 5. `papermeister/ingestion.py`
- `import_zotero_collection(zotero_client, source, collection, progress_callback)` 추가
  - Zotero API로 아이템 조회
  - Paper, PaperFile 생성 (zotero_key 포함)
  - PDF 다운로드 → hash 계산 → 중복 체크

### 6. `papermeister/text_extract.py`
- `process_paper_file()` 수정
  - `PaperFile.zotero_key`가 있으면 → Zotero에서 임시 다운로드 → OCR → 삭제
  - Zotero 메타데이터(title, authors, year, doi)를 PDF 메타데이터보다 우선 적용

### 7. `papermeister/ui/main_window.py`
- File 메뉴에 "Import from &Zotero..." (Ctrl+Z), "&Preferences..." 추가
- `ZoteroScanWorker(QThread)` 추가 (ScanWorker와 유사 패턴)

### 8. `requirements.txt`
- `pyzotero>=1.5.0` 추가

## Import Flow

```
1. File > Import from Zotero...
2. Zotero 자격증명 없으면 → PreferencesDialog 열기
3. ZoteroImportDialog 표시 (컬렉션 트리 로드)
4. 사용자가 컬렉션 선택 → Import 클릭
5. ZoteroScanWorker 실행:
   a. Source(type='zotero') 생성/재사용
   b. 선택된 컬렉션 → Folder 생성 (zotero_key=collection_key)
   c. 각 아이템 → Paper 생성 (title, authors, year, doi from Zotero API)
   d. PDF 첨부파일 → 다운로드 → hash → PaperFile 생성 (zotero_key=attachment_key)
   e. temp PDF 삭제
6. ProcessWindow로 OCR 처리 시작
   - zotero_key 있는 파일은 다시 다운로드하여 OCR
   - OCR 완료 후 temp 삭제, JSON 캐시는 보존
```

## 검증 방법

1. `pip install pyzotero` 후 `python main.py` 실행
2. File > Preferences에서 Zotero 자격증명 입력 + Test Connection
3. File > Import from Zotero에서 컬렉션 트리 확인
4. 컬렉션 선택 → Import → ProcessWindow에서 OCR 진행
5. 소스 트리에 Zotero 라이브러리 표시, 논문 검색 가능 확인
