# 054 — Desktop biblio batch 워크플로우 + 저자 이름 분리

> 세션 43 (2026-06-08). 052/053 write-back 개선의 desktop 운영 측면 + 저자 필드 마무리.

## 배경

052(제목 placeholder)·053(itemType 승격/volume·issue·pages) 이후 실제 collection 단위로
Extract Biblio를 돌려보며 나온 운영상 문제들을 한 묶음으로 정리.

## 저자 이름 firstName/lastName 분리 (write-back, commit `e1a1208`)

자동 write-back은 creators를 single-field `{name}`으로 썼고(override 비교-UI 경로만 분리),
사용자 요청은 "구분 가능하면 항상 firstName/lastName로". `_split_name_for_zotero`에 CJK 분리
휴리스틱(데스크톱 `biblio_service.split_author_name` 포팅: "Last, First", 공백, 일본 4→2/2,
한국 3→1/2; mononym/조직은 single-field)을 넣고 `_author_creators` 헬퍼로 `_compute_patch` +
itemType 승격 payload + override 경로를 통일. core가 desktop을 import할 수 없어 헬퍼는
zotero_writeback에 self-contained로 포팅(중복 감수).

## biblio apply 후 PaperList 행 갱신 (commit `88d8eea`)

`update_status`는 status pill(컬럼 0)만 갱신 → 우클릭 Extract Biblio 자동 적용/수동 Apply 후
Title/Authors/Year가 stale. `paper_service.row_for_paper(paper_id)` + `PaperList.refresh_row()`
신설(행 전체 재조회·재기록), `_on_biblio_extracted`(auto/skip) + `_on_apply_completed`에서
`update_status` 대신 호출.

## 컬렉션 Process Folder가 biblio extraction까지 (commit `1ea6cb6`)

기존 `_process_folder`는 pending/failed PDF(OCR)만 수집 → OCR 완료 폴더는 빈 목록→무동작.
이제 `processed` PDF 중 PaperBiblio 없는 paper도 수집해 `_auto_biblio_queue`로 enqueue(이미
biblio 있으면 skip = 중복 추출 방지). 다이얼로그에 OCR/Biblio 카운트 분리 표시, 둘 다 없으면
"Nothing to do".

## batch biblio 진행 창 (commit `e5174a7`, `desktop/windows/biblio_window.py`)

OCR ProcessWindow처럼 팝업. 기존 직렬 biblio 큐가 구동(begin/set_current/record/finish, worker
없음). per-paper 한 줄 요약(`[n/N] applied — "제목" · 저자 et al. · 연도`, 종류별 색상
applied/review/skip/error) + 진행바 + 하단 집계. post-OCR auto-biblio 합류 시 `add_total`로
total 동기(mixed-case 카운트 오버플로우 방지).

## 처리 순서 = 목록 표시 순서 (commit `7fe0820`)

biblio_targets가 임의 DB 순서였음. `PaperList.visible_paper_ids()`(현재 위→아래, 헤더 정렬
반영)로 rank 매겨 stable sort → 화면 순서대로 처리. 화면에 없는(하위폴더 등) 항목은
`Paper.id desc`(list_by_folder 기본) fallback으로 뒤에. (참고: 폴더 클릭 시 목록 기본 정렬은
`Paper.id.desc()` — 최신 우선.)

## 메모

- 진행 창은 비모달. 단건 우클릭 Extract Biblio는 창 없이 status-bar만(기존 유지).
- `_after_biblio` finish 판정은 "drain 후 queue 비었고 biblio_task 미실행"에 의존 —
  done 슬롯 시점엔 task가 이미 not-running이라는 기존 큐 불변식과 일관.
