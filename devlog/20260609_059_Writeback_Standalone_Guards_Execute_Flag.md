# 059 — write-back standalone 가드 + scripts `--execute` 관례 통일

> 세션 44 (2026-06-09). collection 단위 reflect를 돌리다 standalone PDF에서 만난
> 400 오류 두 건 + 스크립트 플래그 관례 불일치 정리.

## 1. promote 시 `lastRead` 제거 (commit `d301652`)

`promote_standalone_with_filename`이 PDF attachment의 `parentItem`을 설정할 때 fetch한
data를 `update_item`으로 그대로 echo → 서버 관리 read-only 필드 `lastRead`가 있는
attachment에서 `Invalid keys present in item 1: lastRead` 거부. **세션 43에서
`rename_ocr_json.py`에 이미 고친 것과 동일한 버그**가 promote 경로에도 있었던 것.
PATCH 직전 `pop('lastRead', None)` + fetch/update를 transient-retry 헬퍼(devlog 056)
경유로 전환.

## 2. un-promoted standalone write-back 명확한 에러 (commit `c8a932f`)

reflect가 standalone PDF 2편에서 `'date' is not a valid field for type 'attachment'`
400 — 암호 같은 메시지의 정체는 `Paper.zotero_key`가 **attachment 자신을 가리키는
un-promoted standalone**에 biblio write-back을 시도한 것 (attachment에 biblio 필드
PATCH).

`writeback_biblio` 가드: fetch한 item이 attachment 타입이면 `ZoteroPatchRejected`로
"먼저 promote 하라" (`scripts/promote_processed_standalones.py`) 안내.

## 3. `--execute` 관례 통일 (commits `a781ae7`, `c8a932f` 일부)

`reflect_biblio.py` / `rename_ocr_json.py` / `upload_ocr_json.py`는 옛
`--dry-run`(기본=실행) 관례, 최근 스크립트들은 `--execute`(기본=dry-run) 관례로
혼재 — `upload_ocr_json.py --execute`가 unknown arg로 죽으면서 발각.
`promote_processed_standalones.py`의 `--apply`도 같은 부류.

**전부 `--execute`로 통일** (내부적으로 `args.dry_run = not args.execute`).
mutating 스크립트 11개 모두 "플래그 없이 실행 = 안전한 미리보기". CLAUDE.md Scripts
섹션에 관례 명문화.

## 메모

- `lastRead` 류의 "fetch한 dict를 그대로 write에 echo" 패턴은 이제 두 번 물렸음
  (rename_ocr_json, promote). pyzotero write 경로가 하나 더 생기면 server-managed 필드
  strip을 공용 헬퍼로 빼는 게 맞음.
- 2의 가드는 회피책이고, 정공법은 standalone이 OCR 완료 시 auto-promote(세션 36)되는
  흐름이라 신규 유입은 자연 차단됨. 잔존분만 promote 스크립트로 처리.
