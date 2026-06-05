# 043 — Trash UI: 자동 숨김 + Library "Trash" 필터

날짜: 2026-06-05

## 동기

세션 39 (devlog 042)에서 `Paper.trashed_at` / `PaperFile.trashed_at` 컬럼만 추가했고 sync에서 flag set/clear까지만 했음. 같은 세션 끝에 segment anything paper (VHCPVSPG) 한 건을 trash로 박아서 검증한 직후 사용자 지적: "collection별 item 목록 보여줄 때 trashed_at 체크 안 하는 것 같은데?"

확인 결과 정확히 그랬음. 데이터 소스 4곳 모두 trashed 필터 없음:
- `desktop/services/paper_service.list_by_library`
- `desktop/services/paper_service.list_by_folder`
- `desktop/services/paper_service.list_by_source`
- `papermeister/search.search()` (FTS5)

거기다 `library.py`의 모든 카운트 함수 (`_count_all`, `_count_status`, `_count_recent`)와 `needs_review_paper_ids()`도 마찬가지. 사용자에게 trash로 보낸 paper가 PaperList에 그대로 보이는 상태.

## 결정

| 항목 | 선택 | 근거 |
|---|---|---|
| 표시 정책 | 일반 목록에서 자동 숨김 + 전용 "Trash" 필터 | Zotero GUI 표준 동작과 일치 |
| 위치 | Library 트리에 `('trash', 'Trash')` 항목 추가 | 기존 LIBRARY_KEYS 패턴 그대로 확장 — 자동으로 `_StatusPanel` 트리에 노출됨 |
| 카운트 정합성 | 트리 카운트와 list가 같은 SQL 술어 사용 | needs_review 항목이 세션 10에서 카운트 vs list 분기로 한 번 어긋났던 전례 |
| 검색 | post-hoc Python 필터 | FTS5 인덱스에 trash 신호가 없으므로 SQL JOIN으로는 풀 수 없음. dedupe 루프 안에서 `paper.trashed_at` 체크 |
| 우클릭 Restore | 미구현 | 사용자가 Zotero GUI에서 복원 → 다음 sync에서 자동 clear 경로만 제공. 빈번한 UX가 아니라 판단 |

## 구현

### `desktop/services/library.py`
- `LIBRARY_KEYS`에 `('trash', 'Trash')` 추가 — 트리 자동 노출
- `_count_all`, `_count_status`, `_count_recent`: `Paper.trashed_at.is_null()` 술어 추가
- `_count_trash` 신설: `Paper.trashed_at.is_null(False)`
- `needs_review_paper_ids()`: SQL JOIN with Paper + `Paper.trashed_at.is_null()` 추가 (PaperBiblio 단독 select에 술어 못 거니까 explicit JOIN)
- `load_library_folders` 분기에 'trash' 추가
- `corpus_counts()`는 헬퍼 재사용이라 자동 반영

### `desktop/services/paper_service.py`
- `list_by_library`:
  - 'all' / 'pending' / 'processed' / 'failed' / 'recent' 5개 케이스 모두 `Paper.trashed_at.is_null()` AND-merge
  - 'needs_review'는 `needs_review_paper_ids()`가 이미 trashed 제외하므로 추가 술어 불필요
  - 'trash' 신설: `Paper.trashed_at.is_null(False)`, `order_by(Paper.trashed_at.desc())` (최근 trash 우선)
- `list_by_folder`: `(PaperFolder.folder == folder_id) & Paper.trashed_at.is_null()`
- `list_by_source`: `(Source.id == source_id) & Paper.trashed_at.is_null()`

### `papermeister/search.py`
FTS5 결과 dedupe 루프 안에서 새 paper 추가 직전에 `paper.trashed_at is not None` 체크:
```python
seen_papers: dict[int, dict] = {}
skipped_trashed: set[int] = set()
for paper_id, page, passage_id, snippet, rank in rows:
    if paper_id in skipped_trashed:
        continue
    entry = seen_papers.get(paper_id)
    if entry is None:
        if len(seen_papers) >= limit:
            continue
        paper = Paper.get_by_id(paper_id)
        if paper.trashed_at is not None:
            skipped_trashed.add(paper_id)
            continue
        ...
```
`skipped_trashed` 캐시는 같은 trashed paper의 N개 passage가 반복적으로 `Paper.get_by_id` 호출하는 걸 방지.

`search_service.search_papers`는 core search 결과를 그대로 PaperRow로 변환하므로 추가 변경 불필요.

### UI 측 (`source_nav.py`)
변경 없음. `_StatusPanel.populate()`이 `load_library_folders()` 결과를 순회하며 `QTreeWidgetItem`을 만드는 구조라, LIBRARY_KEYS 추가만으로 Trash 항목이 자동 등장.

## 검증

사용자 실제 DB 사본 (9,888 papers / 19,983 paperfiles, Segment Anything VHCPVSPG가 trash로 박힌 상태) 기준:

```
load_library_folders:
  all            count=9887  (이전 9888에서 -1)
  pending        count=118
  processed      count=9815
  failed         count=9
  needs_review   count=0
  recent         count=9887
  trash          count=1    (신규)

Trash list:
  paper_id=2995  Segment Anything  status=failed

All Papers excludes the trashed one:
  list returned 9887 rows
  Segment Anything (id=2995) in list? 0

Search "Segment Anything":
  10 results
  id=9891  Segment Anything    ← 같은 제목 다른 paper가 top 1로 올라옴
  (id=2995 not in results)
```

모든 hot path에서 정확히 1건 제외 — 데이터 무결성 + 카운트/list 정합성 확인.

## 후속

HANDOFF.md TODO 갱신:
- [x] Trash flag (042)
- [x] Trash UI 노출 (043)
- [ ] 영구 삭제 (empty-trash) — 042부터 미해결
- [ ] PaperList 우클릭 "Restore from trash" — 신규

## 메모

WSL에서 NTFS 위의 user DB(`/mnt/c/...`)를 peewee `init_db()`로 직접 열면 `disk I/O error` (WAL cross-mount 충돌). 검증은 `/tmp` 복사본으로 수행. 사용자 실 환경(Windows + Anaconda)에선 문제 없음.
