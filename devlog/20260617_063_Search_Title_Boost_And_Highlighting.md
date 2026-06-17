# 063 — 검색 품질: document-level title boost + 매칭 패시지 하이라이트

> 세션 48 (2026-06-17). HANDOFF 백로그의 두 항목 — BM25 title boost(Phase 5 경계),
> 매칭 패시지 하이라이트 — 을 함께 처리.

## 배경

- `passage_fts`는 **passage 단위** 인덱스(title/authors/text 컬럼이 모든 passage row에
  denormalize). `bm25(passage_fts, 10, 5, 1)`의 title×10 가중치는 **passage 내부에서만**
  작동 → 제목에 검색어가 있지만 본문이 sparse한 논문이 본문 다수 매치 논문보다 아래로
  내려가는 "trilobite 문제".
- 검색 결과의 `snippet(passage_fts, 2, '**','**', …)`(매치어를 `**`로 감쌈)이 desktop에선
  **버려지고** 있었음 — 결과 목록이 일반 폴더 목록과 구분 안 됨.

## 1. Document-level title boost (`papermeister/search.py`)

별도 `paper_fts` 인덱스 없이 **Python 재랭킹**으로 해결(HANDOFF의 두 안 중 후자).
`query_terms(query)` 신설(소문자 word 토큰, FTS 연산자/따옴표 제거, CJK 보존 —
`\w+` UNICODE, len≥2 또는 non-ASCII). dedupe 후 3-tier 정렬:

- tier 0: **모든** query term이 제목에 있음 → 최상위
- tier 1: 일부 term이 제목에 있음
- tier 2: 없음

각 tier 내부는 기존 BM25 rank 순. 즉 제목 매치가 본문 relevance를 이기되, 같은 tier
안에선 BM25가 순서를 정함. 검증: 본문에 8회 나오는 논문 vs 제목에만 1회 → **제목 매치
논문이 1위**.

## 2. 매칭 패시지 하이라이트

### (a) 검색 결과 행 툴팁 (`search_service` + `paper_service.PaperRow` + `paper_list`)

`PaperRow.snippet`(기본 '') 추가. `search_papers`가 best match snippet을 `_snippet_html`로
변환(HTML escape 후 `**x**`→`<b>x</b>`)해 행에 실음. `_populate`가 snippet 있으면 모든
컬럼에 툴팁 설정 → 결과 위에 마우스 올리면 매치 문맥(매치어 bold)이 뜸. 일반 목록은 snippet
없어 영향 0.

### (b) OCR Text 탭 인라인 하이라이트 (`detail_panel` + `main_window`)

`DetailPanel.set_search_terms(terms)` + `_apply_search_highlight(browser)`:
`setMarkdown` 후 `QTextDocument.find`(대소문자 무시)로 모든 매치를 모아
`QTextEdit.ExtraSelection`(반투명 amber `#fbbf24` alpha 96 배경)으로 오버레이 →
**문서 자체는 안 건드림**(sanitizer/markdown 무손상). 첫 매치로 `ensureCursorVisible` 스크롤.
main_window: 검색 실행 시 `search_service.query_terms(query)`를 detail panel에 전달,
`_apply_current_selection`(검색 이탈) 때 `[]`로 클리어. Text 탭은 lazy build라
`_build_ocr_tab`에서 적용 + `set_search_terms`가 이미 빌드됐으면 즉시 재적용.

검증: 토크나이저(영문/구문/boolean/CJK), snippet HTML escape+bold, 본문 2회 매치→2
selection + 클리어→0, search_papers가 snippet 부착.

## 메모 / 후속

- title boost가 단일어 쿼리("trilobite")엔 정확히 맞고, 다중어는 "전부 제목에"만 tier 0이라
  과승격 방지. 필요 시 author 매치도 tier에 반영 가능(현재 title만).
- OCR 탭 하이라이트는 사용자가 Text 탭을 열어야 보임(기본 Metadata 탭). 검색 결과 클릭 시
  자동으로 Text 탭 전환은 의도적으로 안 함(메타 확인이 우선인 경우 많음). 행 툴팁이 즉시
  문맥 제공.
- 결과 목록에 snippet을 **인라인**(툴팁 아닌 두 번째 줄)으로 그리려면 Title 컬럼 delegate
  필요 — 후속 과제.
