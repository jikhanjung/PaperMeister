# 050 — Zotero 영구 삭제(empty-trash) 미러링

> 세션 43 (2026-06-08), [042](./20260605_042_Zotero_Trash_Flag_Sync.md)·[049](./20260608_049_Attachment_Extension_Gate_Skipped_Status.md) 후속.

## 증상

사용자가 Zotero **trash에 있던 item을 영구 삭제(empty-trash)** 했는데 PaperMeister에서는
다시 **restore**되어 정상 목록에 나타남.

## 원인 (세션 39 docstring에 이미 미구현으로 명시한 갭)

`sync_trash_state`는 trash 스냅샷만 본다: "현재 trash에 없으면 = 복원됨"으로 간주해
`trashed_at`을 clear. **영구 삭제와 복원이 trash 목록 관점에서 동일**하게 보이기 때문에,
emptied-trash item이 silently restore됨. (`Paper.update(trashed_at=None).where(...not_in(trash))`)

확인: 영구 삭제한 2편(Segment Anything `VHCPVSPG`, Triplet Loss `29FKEBLQ`)이 `trashed=False`
상태로 DB에 살아있었음 = 버그난 sync가 이미 flag를 지운 것.

## 해결: `/deleted?since=N` 기반 영구 삭제 미러

`/deleted` 엔드포인트는 trash와 달리 incremental이고, **영구 삭제만** 반환 — 복원은 여기
안 뜸. 이게 둘을 구분하는 유일한 방법.

- `ZoteroClient.get_deleted_keys(since)` — `zot.deleted(since=N)['items']` → uppercase key set
- `ingestion.purge_local_by_keys(keys)` — 매칭 Paper를 cascade 삭제(Author/PaperFile/Passage/
  PaperBiblio/PaperFolder) + `passage_fts` 수동 DELETE(FTS5는 FK 없음). 부모가 살아있는
  attachment-only 삭제는 해당 PaperFile만. **OCR JSON 캐시는 보존**(content-addressed, 재활용).
  키 목록은 500개씩 청크(SQLite 999 변수 한도).
- `ingestion.apply_permanent_deletions(client)` — `zotero_deleted_version` pref로 증분 추적.
  첫 실행은 baseline만 기록(과거 이력 스캔 범위 없음).
- **worker Phase 3a** (`zotero_sync._sync`): trash sync **직전**에 실행. 순서가 중요 — 영구
  삭제분을 먼저 지워야 trash sync의 restore 로직이 그걸 "복원"으로 오인하지 않음.

### 결정: 로컬도 삭제 (Zotero 미러)

사용자 선택. Zotero source-of-truth 원칙에 부합. cascade는 DB row만 지우고 OCR 캐시 파일은
디스크에 남아 같은 PDF 재취득 시 재활용 가능(옵션3 이점 자동 포함).

## 기존 backlog: `scripts/purge_deleted_zotero.py`

worker 첫 실행이 baseline만 잡으므로 이미 삭제된 2편은 못 잡음 → `--since 0`으로 전체 삭제
이력 스캔하는 one-off. dry-run 기본, execute 시 purge + baseline 설정.

**실행 결과**: Zotero 전체 삭제 이력 905 key 중 로컬 매칭 **정확히 2편** → cascade 삭제.
검증: paper 2995/4650 소멸, PaperFile cascade 정리, passage_fts orphan 0, failed 5→3
(남은 3 = DETR/ResNet/Focal Loss, 파일 자체가 없는 정당한 실패). 이후 sync는 worker 자동.

## 메모

- `deleted(since=0)`는 905개 반환(라이브러리 전체 삭제 이력) — 청크 처리로 안전.
- linked_url 등 비-paper item 삭제도 deleted['items']에 섞이지만, 로컬 매칭에서 자연 필터됨.
- 남은 한계: attachment 교체(같은 parent, 새 파일)는 영구삭제 신호가 아니라 별도(MD5 추적 TODO).
