# 044 — Collections incremental sync (Phase 1 11s → 4s)

날짜: 2026-06-05

## 동기

세션 43 끝 무렵 사용자가 "Sync collection이 생각보다 오래 걸리는 것 같다"고 보고. 코드 보니 worker가 `client.get_collections()`를 since 없이 호출 → 매번 full fetch. `ZoteroClient.get_collections(since=N)`은 incremental 코드를 이미 갖고 있는데(있는 줄도 잊고 있었음) worker가 안 씀.

이전 분석(같은 세션 초반)에서 "45개면 부담 적음, 바꾸지 말자" 권고했는데 사용자 라이브러리가 **실제로 547개**였음 (10배 차이). 그래서 의견 번복하고 incremental 진행.

## 측정

worker `_sync` Phase 1에 phase별 `time.perf_counter()` 추가해서 첫 raw 측정:

```
collections: load_cached took 0.00s (547 entries)
collections: sync(cached) took 2.09s
collections: get_collections() took 7.21s (547 entries)   ← dominant
collections: sync(fresh) took 2.10s
collections: phase 1 total 11.40s
```

hotspot 두 군데:
1. **`get_collections()` 7.21s** — 547개 / 25개씩 = 약 22 API round-trips. 네트워크 latency가 dominant
2. `sync(cached)` + `sync(fresh)` = 4.19s — 같은 입력에 같은 DB 작업을 거의 두 번 (cached는 cold-start UX, fresh는 진실 데이터). 구조적 중복

## 결정 (A + B 같이 진행)

세 후보 중 두 개 묶어서:

- **A. `get_collections()` incremental** — 7.21s → ~0.5s. 이미 코드 있음. 한 줄 변경 + 별도 pref. 위험 거의 없음
- **B. `sync(cached)` 제거** — 2.09s 절감. **출처**: 사용자 확인에 따르면 예전 DB 도입 전(혹은 migration) 잔재로 들어간 코드. 현재는 Folder 테이블이 persistent라 cold-start UI 응답성 가치도 없음 (desktop이 sync 시작도 전에 last-known Folder 트리를 즉시 표시). 안전하게 제거 가능
- C. `sync_zotero_collections` 내부 bulk pre-fetch — 0.3~0.5s 추정. micro-optimization. 나중에

## 구현

`desktop/workers/zotero_sync.py` 한 파일만 수정. `sync_zotero_collections`와 `cli.py`는 안 건드림 (다른 caller에 영향 없도록).

### 별도 pref `zotero_collections_version`

`zotero_library_version`(items용)과 분리. 이유:
- items 변경만 일어나도 library version은 올라감 → `zotero_library_version`만 보면 collections sync가 매번 "이전과 다름" 판정해 incremental 효과 없음
- collections만의 last-seen library version을 별도 추적해야 "collections 변경이 진짜 있을 때만" fetch

### Worker 흐름

```python
last_col_ver = get_pref('zotero_collections_version', None)
col_since = None if needs_full else (int(last_col_ver) if last_col_ver else None)

# Phase 1 — no more cached pre-warm.
fresh = client.get_collections(since=col_since)
if fresh is None:
    # No collection changes since last_col_ver — Folder table already truth.
    col_count = Folder.select().where(Folder.source == source).count()
else:
    sync_zotero_collections(client, source, fresh)
    col_count = len(fresh)

# Always stamp — sync_zotero_collections only writes zotero_library_version.
new_col_ver = client.get_library_version()
set_pref('zotero_collections_version', new_col_ver)
```

### Race 회피

`sync_zotero_collections`는 내부에서 `set_pref('zotero_library_version', ...)`를 매 호출 overwrite. worker가 phase 시작 전 `last_version`을 미리 캡처하는 패턴은 그대로 유지(세션 13에서 도입된 안전장치).

## 결과

A만 적용했을 때(첫 측정) 결과:

```
collections: load_cached took 0.00s (547 entries)
collections: sync(cached) took 2.09s
collections: get_collections(since=54469) took 0.77s (0 entries)   ← 7.21s에서
No collection changes.
collections: phase 1 total 4.00s    ← 11.40s에서
```

A + B 같이 적용한 최종 예상치 (사용자 검증 보류):

| 구간 | Before | A만 | **A + B** |
|---|---:|---:|---:|
| `load_cached` | 0.00s | 0.00s | (제거) |
| `sync(cached)` | 2.09s | 2.09s | **(제거)** |
| `get_collections` | 7.21s | 0.77s | 0.77s |
| `sync(fresh)` | 2.10s | skip | skip |
| `get_library_version` (stamp) | — | ~1s | ~1s |
| **phase 1 total** | **11.40s** | **4.00s** | **~2s** |

약 80% 절감. 두 번째 sync부터 영구적.

## 남은 흠

phase 1 total 4.00s 중 component 합은 2.86s. 차이 ~1.14s는 우리가 박은 `client.get_library_version()` 추가 round-trip 1회 + log overhead.

엄밀히는:
- 변경 없을 때 stamp 안 해도 다음 sync에서 같은 since로 같은 결과 받으니 동작 동일 → `get_library_version` 호출 skip 가능
- 또는 items phase의 `get_library_version()` 한 번으로 collections version도 같이 stamp (단, collections fetch와 items fetch 사이 library version 변동이 있으면 미스 가능성 미세)

micro-optimization이라 보류. 일단 4s면 사용자 응답성 충분.

## 후속

남은 후보:
- `get_library_version()` 추가 round-trip ~1s — items phase의 `get_library_version()` 한 번으로 collections version도 같이 stamp하면 제거 가능. 다만 collections fetch와 items fetch 사이 library version이 살짝 올라가면 미스 가능성 미세. micro-optimization
- `sync_zotero_collections` 내부 bulk pre-fetch (변경 있는 sync에서 매 collection × select N+1 → 1 SQL로 단축) — 변경 있을 때만 의미

둘 다 단순화 가치는 있지만 즉시 ROI는 작음. 별도 작업.
