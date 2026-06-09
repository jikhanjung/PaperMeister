# 056 — batch biblio 견고성: Zotero transient 오류 처리

> 세션 43 연속 (2026-06-09). 055의 정책 완화로 collection 단위 biblio 적용을 돌리던 중
> Zotero 503에 배치가 멈춘 사건에서 출발.

## 증상

1970s collection biblio 처리(87편)가 **81/87에서 멈춤**. 앱은 살아있는데 더 진행이 없음.
`python -m desktop` 콘솔 traceback:

```
pyzotero.zotero_errors.HTTPError: Code: 503
URL: https://api.zotero.org/users/.../items/89UIC5V4?format=json...
Response: Zotero online services are currently unavailable. Please try again in a few minutes.
  ... writeback_biblio → client._zot.item(paper.zotero_key)   # write-back 직전 fresh fetch
```

= 우리 버그가 아니라 **Zotero 서버의 일시 장애(503)**. 그런데 전날 밤엔 같은 류의 오류로
앱이 **죽었음**(crash). 같은 예외인데 어떨 땐 죽고 어떨 땐 멈추는 비결정성.

## 원인 분석

1. **왜 503에서 끊겼나**: `_on_biblio_extracted`(자동 apply 핸들러)가 apply 주변에서
   `ZoteroWriteAccessDenied`/`ZoteroPatchRejected` 둘만 catch. `HTTPError(503)`는 안 잡혀
   슬롯 밖으로 전파.
2. **왜 죽거나/멈추거나**: 이 핸들러는 `task.done` 시그널 슬롯(메인 스레드 이벤트 루프에서 호출).
   PyQt6는 슬롯 내 미처리 예외를 **때로는 `qFatal`로 abort(크래시), 때로는 C++ 경계에서 삼키고
   루프 유지(멈춤)** — 호출 경로/연결 타입에 따라 비결정적. 멈춤의 경우, 예외가 슬롯을 중간에
   끊어 마지막의 `_after_biblio() → _drain_biblio_queue()`(다음 항목 시작)가 실행 안 됨. 배치는
   "for 루프"가 아니라 "끝나면 다음을 큐에서 꺼내는 이벤트 체인"이라 그 한 줄이 안 돌면 정지.

## 수정 1 — 배치 stall 가드 (commit `8d0d12b`)

`_on_biblio_extracted` 전체를 `try/except/finally`로 감쌈. 어떤 예외든 그 논문만 progress 창에
`error`로 기록하고, **`finally`에서 항상 `_after_biblio`(drain)** → 한 편의 실패가 배치 전체를
멈추거나 죽이지 못함. (참고: CLI `reflect_all`은 이미 논문별 try/except라 영향 없었음 — 데스크톱
이벤트-체인 경로만의 문제였음.)

## 수정 2 — transient 재시도, 단 429는 제외 (commit `f2a26c1`)

503/연결오류는 "몇 초 뒤 재시도하면 대개 성공"하는 transient라, write-back에 `_zotero_retry`
추가. 적용: `writeback_biblio`의 fetch ×5 / `_update_item`(PATCH) / `_build_type_upgrade_payload`
의 `item_template`.

**구분이 핵심** (사용자 요청): rate/usage limit인 **429는 재시도하면 악화**되므로 제외.
HTTP 코드로 깔끔히 분리:
- 재시도 O: `500/502/503/504` + `ConnectionError`/`Timeout`
- 재시도 X: **`429`** (rate/usage limit), `4xx` client 오류 → 로그 후 다음, 나중에 재실행

`_is_retryable_zotero_error(exc)`가 pyzotero 메시지의 `Code: NNN`/`NNN Server Error` 패턴 +
requests 예외 타입으로 판정. 재시도는 메인 스레드에서 도므로 **bounded**(2s→5s, 최대 ~7s)로
UI freeze 제한.

## 두 수정의 관계

- 가드(`8d0d12b`)는 **최후 방어** — 어떤 오류든 배치를 안 멈춤/안 죽임.
- 재시도(`f2a26c1`)는 **자가복구** — 잠깐의 503/끊김은 굳이 error로 안 빠지고 통과.
- 둘 다 실패하면(예: 지속 503, 또는 429) 그 논문은 extracted/needs_review로 남고 →
  `reflect_biblio.py` 또는 Process Folder 재실행으로 나중에 적용.

## 메모

- write-back이 메인 스레드 슬롯에서 도는 구조(=각 논문 apply 동안 UI 블록)는 그대로. 더 큰
  개선(apply를 워커 스레드로)은 별도 과제.
- 429를 정말 무시만 할지 vs `Retry-After` 존중해 1회 대기-재시도할지는 운영하며 재검토 가능.
  현재는 사용자 방침대로 "재시도 안 함".
