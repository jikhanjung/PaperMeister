# 057 — 단건 Extract Biblio 큐 단일화 + biblio 상태/pill 정합성

> 세션 44 (2026-06-09). 056의 배치 견고화 이후, collection 단위 biblio를 계속 돌리면서
> 드러난 "단건 경로와 배치 경로가 다르게 동작"하는 문제들과 상태 표시 불일치를 일괄 정리.

## 1. 단건 우클릭 Extract Biblio를 공유 큐로 라우팅 (commit `d38027b`)

**문제**: PaperList 우클릭 단건 Extract Biblio(`_run_biblio_extraction`)가 자체
`BackgroundTask`를 직접 띄움 → 폴더 배치가 살아있는 동안 단건을 누르면
`self._biblio_task`를 **덮어쓰고 동시 실행**. 배치의 직렬화 가정이 깨짐.

**수정**: 확인 다이얼로그 후 `(paper_id, file_id)`를 `_auto_biblio_queue`에 넣고
`_drain_biblio_queue()` 호출 — 배치와 완전히 같은 경로. 중복 구현이던 `_do_extract`
제거 (-39줄). 단건도 배치와 동일한 윈도우/refresh/에러 핸들링을 공짜로 얻음.

## 2. 단건도 biblio 진행창 표시 (commit `4c0f632`)

1의 큐 라우팅 후 단건 추출은 status bar만 갱신되고 팝업이 없었음. 단건도
`BiblioWindow.begin(1)` 호출 — 배치가 이미 떠 있으면 total을 +1 확장(`add_total`과
같은 메커니즘), 없으면 새 창. 단건도 per-paper 결과 라인을 받음.

## 3. 추출 실패가 진행창을 멈춘 것처럼 보이던 문제 (commit `1a827bf`, window 부분)

biblio 추출 `task.failed` 핸들러가 큐 drain만 하고 **진행창은 안 건드림** → 실패한
논문에서 창이 그대로 멈춘 듯 보임(카운트 정지, finish 안 됨). 두 failed 핸들러를
`_on_biblio_failed`로 통일: progress 창에 `error` 행 기록 + `_after_biblio`(advance +
finish 판정).

## 4. `already_complete`를 terminal `done`으로 stamp (commit `eccf754`)

추출 결과가 Zotero와 완전 일치하면 evaluate가 `skip/already_complete`를 반환하는데,
biblio가 `status='extracted'`로 남아 (a) pill이 계속 `OCR`, (b) 매 run마다 재평가
대상. `reflect_all`과 desktop 핸들러 둘 다 이 케이스를
`auto_committed`(review_reason=`already_complete`)로 stamp — terminal이라 'done' pill
+ 이후 평가에서 제외. (`already_applied`/`already_committed`는 원래 terminal이라 불변)

## 5. needs_review 전용 pill (commit `b0920a7`)

`_row_from_paper`가 processed→done 승격을 `applied` biblio에만 적용 →
needs_review 논문이 일반 OCR 완료와 구분 안 됐고, `reflect_all`이 만든
`auto_committed`도 `OCR` pill에 머묾. 이제:
- `{applied, auto_committed}` → **done**
- `needs_review` → **review** (주황 `rev` pill)

`_on_biblio_extracted`의 needs_review 분기도 `biblio.status='needs_review'` stamp +
`refresh_row` — 목록 pill과 Library "Needs Review" 필터가 구조적으로 일치.

## 6. OCR JSON meta는 applied인데 로컬 PaperBiblio가 없는 경우 (commit `3b753d8`)

OCR JSON의 `papermeister_meta.biblio_state=applied`인데 로컬 DB에 PaperBiblio row가
없는 논문(DB 재구축 후 캐시/Zotero JSON만 meta를 보존한 경우)이:
biblio 타겟으로 계속 수집 → `BiblioAlreadyApplied`로 매번 skip → 영원히 'done' 안 됨.

**수정**: 그 skip 시점에 Paper의 현재(이미 적용된) 메타데이터로 **marker
PaperBiblio**를 생성하고 meta의 status를 그대로 박음 → 이후 타겟 수집에서 빠지고
pill도 done.

## 메모

- 1~3으로 단건/배치 biblio가 단일 직렬 큐 + 단일 진행창으로 합류 — 앞으로 biblio
  실행 경로를 건드릴 땐 `_drain_biblio_queue` 체인 하나만 보면 됨.
- 4~6은 모두 "biblio 상태의 terminal 여부와 pill 표시가 어긋나는" 같은 부류의 버그.
  공통 원인은 status 전이가 여러 곳(reflect_all / desktop 핸들러 / evaluate)에 흩어져
  있다는 것. Phase 2 데이터 모델 개정 때 상태 머신으로 명문화할 가치 있음.
