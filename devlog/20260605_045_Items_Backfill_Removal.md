# 045 — sync_zotero_items의 backfill 호출 제거 (25s → 0s)

날짜: 2026-06-05

## 동기

세션 044 (collections incremental) 끝나고 timing 로그 보니 Phase 2 items가 변경 0건인데 **25초**. items phase 안에 timing logger 박아서 좁힘:

```
items: main loop (0 items) took 0.00s
items: orphan_attachments (0 atts across 0 parents) took 0.00s
items: backfill (29 papers checked via children API, 0 new attachments) took 25.91s
```

원인 확정: `sync_zotero_items` 끝의 backfill 루프가 PaperFile 0개인 Zotero-sourced Paper 29편 각각에 `zot.children()` API call → 매 sync 25s, 항상 0 attachments.

## Git archaeology

```
git log -S "Backfill: find Zotero-sourced" -- papermeister/ingestion.py
857a6d8 fix: PaperFolder M2M query, Paper-based counts, non-PDF standalone sync
```

2026-04-16 commit (devlog 029) 도입. 당시 commit msg + devlog: **"전체 9,877편 중 이 케이스는 1건뿐"**. 즉 개발 중 발견된 단 1편의 historical case를 잡기 위한 임시 안전망. 그게 매 sync마다 무기한 돌면서 누적 overhead.

## 결정

사용자 지적: **"정상적인 sync라면 backfill이 필요하지 않을 것 같은데. cold 인 경우라도 collections/items/attachments를 제대로 가져와서 parent/collection 관계를 재구성한다면 발생하지 않을 일이잖아."**

맞음. 다음 추론:

| 시나리오 | backfill 필요? |
|---|---|
| 일반 incremental sync | 변경 없으면 안 함 |
| 변경 있는 incremental sync | 새 items가 attachments 같이 가져옴 — 안 함 |
| Cold-start sync | collections/items endpoint가 제대로 응답하면 자동 채워짐 — 안 함 |
| **main loop 버그로 누락 발생** | 그건 main loop에서 fix해야 — 보험으로 매번 25s는 비효율 |

즉 backfill이 의미 있는 시나리오는 **개발 중 임시 brokenness 복구** 뿐. 영구 호출 경로에 둘 이유 없음.

세션 044 끝에 잠시 `do_backfill=(since is None or needs_full)` 게이트로 보수적 처리했는데, 위 추론에 따라 한 단계 더 — **호출 자체 제거**.

## 구현

**선택**: backfill 로직을 별도 함수 `backfill_missing_paperfiles()`로 추출 후 어디서도 호출하지 않음. dead-code 주석 덩어리 안 남기고, 미래에 진짜 필요하면 script/REPL에서 명시적으로 부를 수 있음.

### `papermeister/ingestion.py`

- `sync_zotero_items`: 시그니처에서 `do_backfill` 제거(어차피 사용 안 함), 함수 끝의 backfill 블록 통째 제거. docstring에 "see backfill_missing_paperfiles()" 한 줄
- `backfill_missing_paperfiles(zotero_client, progress_callback=None, logger=None)`: 새 함수. 도입 이력 + dormant 이유 + 측정 수치까지 docstring에 박음. `already_handled` 필터는 빠짐 (호출 시점에 이미 sync 끝났을 가능성이 더 큼; 동시 호출 가정 안 함)

### `desktop/workers/zotero_sync.py`

- `do_backfill=(since is None or needs_full)` 결정 코드 + 인자 전달 제거

cli.py 등 다른 caller에 영향 없음 (sync_zotero_items는 worker만 호출, do_backfill은 044에서 추가했다 045에서 제거 — 외부 노출 없음).

## 결과

검증 sync (변경 0건):
```
items: main loop (0 items) took 0.00s
items: orphan_attachments (0 atts across 0 parents) took 0.00s
# backfill 메시지 자체 없음
```

전체 sync time:

| 단계 | 오늘 시작 | 세션 044 (collections만) | 세션 045 |
|---|---:|---:|---:|
| Phase 1 collections | 11.40s | 1.99s | 1.99s |
| Phase 2 items | ~26s | ~26s | **~1s** |
| Phase 3 trash | 2s | 2s | 2s |
| **합계** | **~31s** | ~30s | **5s** |

세션 044+045 통합으로 약 83% 절감. items의 main loop / orphan_attachments timing 로그는 그대로 유지 — 다음에 진짜 변경 있는 sync에서 어디가 느린지 즉시 알 수 있도록.

## 후속

- `backfill_missing_paperfiles()`는 어디서도 호출 안 되니 lint가 "unused function"으로 잡을 수도 있음. 의도된 dormant라 #noqa 같은 걸 박을지는 lint 도입 시점에 결정
- 진짜 누락 케이스가 또 발생하면 main loop 버그로 진단 → 거기서 fix. backfill 부활은 마지막 선택지
