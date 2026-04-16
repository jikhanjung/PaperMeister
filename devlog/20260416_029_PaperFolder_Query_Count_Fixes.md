# 029 — PaperFolder 쿼리 수정 + 카운트 기준 Paper 단위 통일 + Standalone 전체 수집

**날짜**: 2026-04-16 (세션 15)

## 배경

Kstrati 컬렉션에서 Zotero에는 7개 있는데 PaperMeister에서 5개만 보이는 문제가 발견됨.
또한 "All" 카운트가 12,113으로 표시되는데 Zotero 기준 9,877과 크게 불일치.

## 변경 사항

### 1. `list_by_folder()` — PaperFolder M2M 쿼리 전환

**파일**: `desktop/services/paper_service.py`

- **이전**: `Paper.folder == folder_id` (legacy 1:1 FK)
- **이후**: `PaperFolder` junction table JOIN

**원인**: Zotero에서 한 논문이 여러 컬렉션에 속할 수 있는데, `Paper.folder`는 하나만 가리킴.
예: Paper 9862, 9674는 `Paper.folder`가 "태백산분지(538)"를 가리키지만 PaperFolder에는 Kstrati(547)에도 등록되어 있음.

### 2. Library 카운트 기준을 PaperFile → Paper 단위로 변경

**파일**: `desktop/services/library.py`

| 항목 | 이전 | 이후 |
|------|------|------|
| `_count_all()` | `PaperFile.select().count()` = 12,113 | `Paper.select().count()` = 9,877 |
| `_count_status()` | `PaperFile` 행 수 (PDF+JSON 중복) | `Paper JOIN PaperFile ... DISTINCT` |
| "All Files" 라벨 | "All Files" | "All Papers" |

**원인**: 한 Paper에 PDF + JSON 등 여러 PaperFile이 있으면 중복 카운트.

`list_by_library('pending'/'processed'/'failed')` (`paper_service.py`)도 PaperFile에서 paper_id를 뽑을 때 `set()`으로 distinct 처리 + limit을 Paper 쿼리 쪽에 이동.

### 3. Standalone attachment — non-PDF 포함으로 확장

**파일**: `papermeister/zotero_client.py`

- `_classify_raw_items()`: `contentType == 'application/pdf'` 필터 제거 → `.doc`, `.djvu`, `.epub`, `.pptx`, `.png`, `.mhtml` 등 모든 standalone attachment 수집
- `_build_results()`: `content_type`을 `'application/pdf'` 하드코딩 → 실제 값 사용

Zotero 9,877개 중 22개가 non-PDF standalone이었고, 이전에는 이들이 무시됨. full sync 후 22개 신규 Paper 생성.

### 4. Paper 9862 (최덕근 2009) PaperFile 누락 복구

Kstrati 컬렉션의 "태백산분지 삼엽충 화석군..." 논문이 Zotero에 PDF가 있는데 PaperMeister에서 "no PDF"로 표시.

- **원인**: 최초 sync 시 attachment 없이 Paper만 생성됨. 이후 incremental sync에서 이 item이 batch에 안 들어와 children fetch fallback 미작동.
- **즉시 수정**: PaperFile 수동 생성 (zotero_key=NPKS9BKG)
- **근본 수정**: `ingestion.py`의 `sync_zotero_items()` 끝에 backfill 로직 추가 — PaperFile 없는 Zotero paper를 찾아 API children fetch. 전체 9,877편 중 이 케이스는 1건뿐.

### 5. Paper 9693 (orphan standalone) 삭제

`zotero_key=NPKS9BKG`로 생성된 Paper — 이건 실제로 Paper 9862의 child attachment key인데 standalone PDF로 잘못 생성된 것. PaperBiblio/Author 없으므로 안전 삭제.

## 최종 수치

| 항목 | 이전 | 이후 |
|------|------|------|
| All 카운트 | 12,113 (PaperFile) | **9,877** (Paper) |
| Kstrati 표시 | 5개 | **7개** |
| Zotero 일치 | 9,877 vs 12,113 불일치 | **9,877 = 9,877 정확 일치** |

## 수정 파일 목록

- `desktop/services/library.py` — 카운트 기준 변경
- `desktop/services/paper_service.py` — `list_by_folder()` M2M, `list_by_library()` distinct
- `papermeister/zotero_client.py` — standalone non-PDF 수집, content_type 실제값
- `papermeister/ingestion.py` — PaperFile backfill 로직
