# 060 — 'My Library' 우클릭 Process All: 라이브러리 전체 OCR + biblio

> 세션 45 (2026-06-10). Phase D 대량 운영의 트리거 — 폴더 단위로 돌리던 Process를
> 라이브러리 전체 단위로 확장하고, 실제 전 라이브러리 biblio 작업을 개시.

## 문제 (commit `2bf9519`)

SourceNav의 source 루트("My Library") 우클릭 메뉴가 `process_folder`를 **Source.id**와
함께 emit → `_process_folder`가 이를 folder_id로 해석해 매칭되는 폴더가 없어 **아무
것도 수집 못 함**. 사실상 루트 우클릭 Process가 무동작.

## 수정

폴더 처리 로직을 `_run_process_scope(folder_ids | None, scope_label)`로 리팩터:

- `folder_ids=None` = **라이브러리 전체** (collection 필터 없음 — uncollected 포함)
- 리스트면 기존처럼 해당 폴더(+하위) 제한

SourceNav는 `kind == 'source'`일 때 전용 액션 **"Process All (OCR → Biblio)"** 를
`process_source`로 emit (폴더용 Upload OCR JSON 항목은 루트에서 숨김).

수집 범위는 폴더 Process와 동일한 2종:
1. **OCR**: `pending` + `failed` PDF (failed는 pending 리셋 + force 재OCR, 세션 43~44
   메커니즘 그대로)
2. **Biblio**: `processed` PDF 중 PaperBiblio 없는 paper → `_auto_biblio_queue`
   (이미 biblio 있으면 skip, `Paper.id desc` 순)

## 운영 개시

이 커밋으로 **데스크탑 앱에서 라이브러리 전체 biblio 작업을 실제 가동 중** (2026-06-10~).
OCR은 99.9% 완료 상태라 사실상 biblio 추출 + auto-apply가 본체. 흐름:

- My Library 우클릭 → Process All → 다이얼로그에서 OCR/Biblio 카운트 확인 → 진행
- 직렬 biblio 큐 + BiblioWindow per-paper 결과 라인 (devlog 054/057)
- 한 편의 에러는 error 행 기록 후 큐 계속 (devlog 056), Zotero 5xx는 자동 재시도
- needs_review로 빠진 논문은 Library "Needs Review" 필터에 모임 → 추후 일괄 검토

## 메모

- 전체 스코프 쿼리는 `PaperFolder` join을 아예 생략 — Zotero multi-collection
  membership으로 인한 중복 paper 문제도 자연 회피.
- 대량 실행에서 지켜볼 것: Zotero API rate limit(429는 의도적으로 재시도 안 함 —
  devlog 056), 멈춘 것처럼 보이면 진행창 error 행과 콘솔 traceback 먼저 확인.
- 중간에 끊겨도 안전: 이미 biblio 있는 paper는 재수집 안 되므로 Process All 재실행이
  곧 resume.
