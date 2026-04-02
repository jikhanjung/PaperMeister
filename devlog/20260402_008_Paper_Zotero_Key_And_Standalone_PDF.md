# Paper.zotero_key 추가 및 Standalone PDF Import 지원

**날짜:** 2026-04-02
**유형:** 구현 기록

---

## 배경

- 기존에는 `Paper` 테이블에 Zotero parent item key가 저장되지 않았음
- 중복 체크를 `folder + title` 매칭에 의존 — 동기화 시 불안정
- Zotero에서 parent item 없이 collection에 직접 들어간 standalone PDF는 DB에 아예 import되지 않았음

## 변경 사항

### 1. Paper.zotero_key 컬럼 추가

- **`papermeister/models.py`**: `Paper` 모델에 `zotero_key = TextField(default='')` 추가
- **`papermeister/database.py`**: 기존 DB에 `paper.zotero_key` 컬럼 자동 추가하는 마이그레이션 로직 추가

### 2. Ingestion dedup 로직 개선

- **`papermeister/ingestion.py`**: `fetch_zotero_collection_items()` 수정
  - 먼저 `Paper.zotero_key`로 매칭 시도
  - 없으면 기존 `folder + title` 매칭으로 fallback
  - 기존 레코드에 zotero_key가 비어있으면 자동 backfill
  - 새 Paper 생성 시 `zotero_key` 저장

### 3. Standalone PDF import 지원

- **`papermeister/zotero_client.py`**: `get_collection_items()` 수정
  - `parentItem`이 없는 PDF attachment를 `standalone_pdfs` 리스트에 수집
  - 파일명(또는 title 필드)에서 제목 추출하여 일반 item과 동일한 형태로 반환
  - Standalone PDF의 경우 `Paper.zotero_key`와 `PaperFile.zotero_key`에 동일한 attachment key 저장

## Key 저장 구조

| 케이스 | Paper.zotero_key | PaperFile.zotero_key |
|--------|------------------|----------------------|
| 정상 (parent + attachment) | parent item key | attachment key |
| Standalone PDF | attachment key | attachment key (동일) |

## 향후 확장

- Standalone PDF를 OCR 처리 후 Zotero에 parent item을 생성하면:
  - `Paper.zotero_key` → 새 parent item key로 교체
  - `Paper`의 메타데이터(title, year 등) → 추출 정보로 업데이트
  - `PaperFile.zotero_key` → 기존 attachment key 유지
