# P10: PaperFolder Junction Table — Multi-Collection Membership

**날짜:** 2026-04-12
**상태:** 계획

## 문제

Zotero item은 여러 컬렉션에 동시 소속될 수 있지만, PaperMeister의 `Paper.folder`는 단일 FK다.
`fetch_zotero_collection_items()`가 `Paper.zotero_key`로 global dedup하므로, 첫 번째 sync된 컬렉션만 `Paper.folder`에 기록되고 나머지 membership은 유실된다.

**영향:**
- Needs Review 논문의 소속 컬렉션을 정확히 파악할 수 없음
- Ctrl+click reveal이 primary collection 하나만 보여줌
- Zotero desktop과 동작 불일치

**현재 데이터:**
- 9,783 papers, 543 folders
- 모든 Paper에 folder 할당됨 (null 0건)
- zotero_key 중복 0건 (global dedup 정상 동작 중)

## 설계

### 1. `PaperFolder` 모델 (junction table)

```python
class PaperFolder(BaseModel):
    paper = ForeignKeyField(Paper, backref='paper_folders', on_delete='CASCADE')
    folder = ForeignKeyField(Folder, backref='paper_folders', on_delete='CASCADE')

    class Meta:
        indexes = (
            (('paper', 'folder'), True),  # unique together
        )
```

`Paper.folder` FK는 **유지** (backward compat + primary collection). `PaperFolder`가 전체 membership 담당.

### 2. Migration + Backfill

`database.py`:
- `ALL_TABLES`에 `PaperFolder` 추가
- `_migrate()`에서 기존 `Paper.folder`로부터 backfill:
  ```sql
  INSERT OR IGNORE INTO paperfolder (paper_id, folder_id)
  SELECT id, folder_id FROM paper WHERE folder_id IS NOT NULL
  ```
- 앱 시작 시 자동 실행 → 기존 DB에 즉시 적용

### 3. Zotero API — `collections` 필드 전달

`zotero_client.py`:
- `_parse_item_metadata()` 반환 dict에 `'collections': data.get('collections', [])` 추가
- `get_collection_items()`에서 parent item의 `full_item['data']['collections']`를 item dict에 전달
- standalone PDF는 `collections: []`

### 4. Ingestion — `PaperFolder` 생성

`ingestion.py` `fetch_zotero_collection_items()`:
1. Paper 생성/조회 후, 현재 `folder`에 대해 `PaperFolder.get_or_create(paper=paper, folder=folder)`
2. `item['collections']`의 각 collection key → `Folder.zotero_key`로 lookup → 존재하면 `get_or_create`

이렇게 하면:
- 전체 resync 시: 모든 컬렉션 순회하며 PaperFolder 누적 → 완전한 membership
- 단일 컬렉션 클릭 시: 해당 컬렉션 + API가 알려주는 타 컬렉션까지 한 번에 기록

### 5. Service layer

`paper_service.py`:
- `PaperDetail`에 `collections: list[tuple[int, str]]` 추가 — `(folder_id, "Parent › Child › Leaf")` 형태
- `load_detail()`에서 `PaperFolder.select().where(PaperFolder.paper == paper)` → 각 folder의 parent chain walk

### 6. UI

`detail_panel.py`:
- Metadata 카드의 Collection 행: 다중 컬렉션 줄바꿈 표시
- Ctrl+click reveal은 primary folder 기준 유지

### 7. Cascade 삭제

- `PaperFolder.paper`와 `PaperFolder.folder` 모두 `on_delete='CASCADE'`
- Paper 삭제 → PaperFolder 자동 삭제 (SQLite FK pragma ON)
- `resync_zotero.py`에서 명시적 cleanup 불필요

## 수정 파일

| 파일 | 변경 |
|------|------|
| `papermeister/models.py` | `PaperFolder` 모델 추가 |
| `papermeister/database.py` | `ALL_TABLES` + backfill migration |
| `papermeister/zotero_client.py` | `_parse_item_metadata`에 `collections` 필드 |
| `papermeister/ingestion.py` | `PaperFolder.get_or_create` 로직 |
| `desktop/services/paper_service.py` | `PaperDetail.collections` 다중 경로 |
| `desktop/views/detail_panel.py` | 다중 컬렉션 표시 |

## 검증

1. `init_db()` 실행 → `paperfolder` 테이블 생성 + 9,783건 backfill
2. `SELECT count(*) FROM paperfolder` → 9,783 이상
3. `python -m desktop` → Needs Review 논문 → Metadata 탭 → Collection 행에 다중 컬렉션 표시
4. Ctrl+click → SourceNav reveal 정상 동작
