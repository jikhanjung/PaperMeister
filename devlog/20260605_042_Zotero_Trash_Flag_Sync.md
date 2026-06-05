# 042 — Zotero trash flag sync

날짜: 2026-06-05

## 동기

세션 41 끝나고 사용자가 "서버 쪽에서 삭제된 item도 sync 돼?"라고 물음. 코드 확인 결과:

- `ZoteroClient.get_all_items(since=N)`이 `zot.items(since=N)`만 호출 — 이 endpoint는 **trash로 간 item을 포함하지 않음**
- `papermeister/ingestion.py` 전체에 `deleted` / `trash` 처리 코드 0건
- 결과: 사용자가 Zotero에서 paper나 attachment를 trash로 보내도 우리 DB에는 영구 잔존, sync로 절대 반영 안 됨

이번 작업은 **trash로 가 있는(아직 영구 삭제 안 된) 상태**만 flag로 박는 게 목적. 영구 삭제(empty-trash)는 별도 작업.

## 결정

| 항목 | 선택 | 근거 |
|---|---|---|
| 컬럼 타입 | `DateTimeField(null=True)` | 단순 boolean보다 정보 풍부 — grace period 정책이나 "지난 7일 trash" 통계 등에 활용 가능. NULL=정상, datetime=trash 진입 시점 |
| 모델 | `Paper.trashed_at` + `PaperFile.trashed_at` 둘 다 | Zotero에선 parent item과 attachment를 독립적으로 trash로 보낼 수 있음 |
| API | `zot.trash()` full snapshot | Zotero는 `/items/trash`에 `since` 미지원. 매 sync마다 전체 fetch. 보통 trash는 비워두니까 소형 라이브러리 |
| 복원 처리 | 양방향 sync (set/clear) | snapshot 비교로 자연스럽게 처리. 사용자가 Zotero에서 trash 비우거나 복원하면 다음 sync에서 자동 반영 |
| 영구 삭제 | 별도 작업 | 사용자 의사: "새로 추가하면 그때 다시 작업" — 일단 trash만 |
| Cascade 보호 | 변경 안 함 | 이번 fix는 row 삭제를 안 하므로 `PaperBiblio` cascade 위험 없음. 영구 삭제 작업에서 다룸 |
| UI | 변경 안 함 | 데이터만 박아둠. PaperList 숨김/회색/별도 필터는 다음 결정 |

## 영구 삭제와 restore의 비대칭

snapshot 비교 방식의 한계: row의 zotero_key가 "이전엔 trash에 있었는데 지금은 없다"는 신호는 (a) 사용자가 복원했거나 (b) trash를 비웠을 때(영구 삭제) 똑같이 보임. 우리는 둘을 구분 못 함.

현재 동작: 둘 다 `trashed_at = NULL`로 clear. (b)인 경우 row는 우리 DB에 dangling pointer로 남고 다음 작업(예: Zotero PATCH)에서 404. **해롭지는 않지만 정확하지도 않음**. 영구 삭제 작업에서 `zot.deleted(since=N)`을 같이 fetch해서 (b) 케이스만 row 자체를 삭제하도록 분리하면 해결.

## 구현

### models.py
```python
class Paper(BaseModel):
    ...
    trashed_at = peewee.DateTimeField(null=True)

class PaperFile(BaseModel):
    ...
    trashed_at = peewee.DateTimeField(null=True)
```

### database.py `_migrate()`
```python
if 'trashed_at' not in columns:  # paper
    database.execute_sql('ALTER TABLE paper ADD COLUMN trashed_at DATETIME')
if 'trashed_at' not in pf_columns:  # paperfile
    database.execute_sql('ALTER TABLE paperfile ADD COLUMN trashed_at DATETIME')
```

### zotero_client.py
```python
def get_trash_keys(self):
    raw = self._zot.everything(self._zot.trash())
    keys = set()
    for it in raw or []:
        data = it.get('data') or {}
        k = data.get('key') or it.get('key')
        if k:
            keys.add(k.upper())
    return keys
```

### ingestion.py `sync_trash_state(zotero_client, progress_callback=None)`
- 한 트랜잭션 안에서 Paper × {set, clear} + PaperFile × {set, clear} 총 4개 bulk UPDATE
- trash가 비어있는 경우(`trash_list == []`)는 `IN ()` SQL syntax 에러 방지 위해 별도 분기 (모든 flag clear)
- key 매칭은 `zotero_key.in_(trash_list)` — 우리 DB의 zotero_key가 대소문자 보존된 채 저장돼 있지만 Zotero key는 사실상 항상 대문자라서 OK. 방어적으로 normalize 하려면 양쪽 다 UPPER() 처리 필요 (현재 안 함)
- 반환: dict with 4 카운트 (newly_trashed_papers, restored_papers, newly_trashed_files, restored_files)

### desktop/workers/zotero_sync.py
- `_sync()`에 Phase 3로 추가 (Phase 1 collections / Phase 2 items / Phase 3 trash)
- try/except로 best-effort — trash sync 실패가 메인 sync을 망치지 않도록
- 상태바: 변경 있을 때 `Trash sync: trashed N papers / M files, restored ...`, 없으면 `Trash sync: no changes.`

### CLI 미연동
`cli.py`의 `zotero sync` 서브커맨드는 `sync_zotero_collections`만 호출 (item sync는 별도 `zotero fetch`). desktop이 메인 sync 경로이므로 일단 CLI는 그대로. 필요하면 별도 작업.

## 검증

마이그레이션 검증 — 9,888 papers / 19,983 paperfiles DB 사본에 `init_db()` 호출:
```
paper schema:     (9, 'trashed_at', 'DATETIME', 0, None, 0)
paperfile schema: (7, 'trashed_at', 'DATETIME', 0, None, 0)
paper trashed:     0
paperfile trashed: 0
```
컬럼 추가 OK, 기존 데이터 무손상, 초기값 NULL.

라이브 sync 검증은 사용자 측에서 desktop 재실행 → Sync 한 번 돌려서 status bar 메시지 확인 + (필요 시) Zotero에서 테스트 item 하나 trash로 보냈다가 다음 sync에서 `trashed_at` 박히는지 SQL로 확인.

## 후속 작업

HANDOFF.md에 두 TODO 추가:
- **영구 삭제 (empty-trash) 핸들링** — `zot.deleted(since=N)` 활용, restore와 분리
- **Trash UI 노출** — PaperList 숨김 vs 회색 vs 별도 "Trash" library 필터

이번 작업이 한 일은 **데이터 인프라만**: 사용자가 다음 단계로 UI 정책을 결정하면 바로 wiring 가능한 상태.
