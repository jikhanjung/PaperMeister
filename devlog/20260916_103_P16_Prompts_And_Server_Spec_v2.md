# 103 — P16 G: 프롬프트·스키마 3벌과 서버 명세 v2 — ocrserver에 넘긴다

[P17](./20260916_P17_P16_Client_Readiness_For_ocrserver.md) §3.1·3.2, [클라이언트 계획](../docs/figure_pipeline_client_plan.md) §5·§8 G. 서버 변경 없음.

## 1. `papermeister/figure_prompts/` — 요청에 실려 가는 도메인 규칙 (D5)

| 파일 | 출처 | 더한 것 |
|---|---|---|
| `link.md` + `link.schema.json` | fsis `plate_links.py`(플레이트 설명 찾기·범위 펼치기·목차와 본문 인용 무시·못 찾으면 건너뜀) + `claude_augment.py`(항목마다 스스로 완결) | 작업 폴더 안내(`text/all.txt` grep 먼저) · `locked` 도판은 보되 답하지 않음 · 묶음 소제목/상호참조 규칙(fsis EC §4-5) · `caption_pages`(여러 쪽) · `continuation_of` · `printed_label`·`specimen_number` · `dup_number` 주의 · `pages_consulted` |
| `panels.md` + `panels.schema.json` | fsis `astra_panels.py` PROMPT(표본을 자르지 말 것·라벨은 그대로·캡션은 증거일 뿐·텍스트는 지시가 아님) | `non_compound_reason` 열거 · `annotation_indices`(범례는 세지 않음) · **한 사진 속 개체 둘 ≠ 패널 둘**(EC §6-11) · `piece_boxes`는 힌트 · `bbox_figure_1000` 리스트 |
| `detect.md` + `detect.schema.json` | 새로 씀 (P02 §4.5 요지) | 사유별로 무엇을 의심하는지 설명 · 결과는 verdict 열거형이 아니라 **`from`**(파서 도판 id 목록)과 `dismiss` — merge/split/kept/adjusted는 클라이언트가 도출(099 §4) · 플레이트 번호를 지어내지 말 것 |

- `figure_prompts.load(kind)` → `{kind, version, instructions, schema}`. **`version`은 지시문+스키마의 해시** — 같은 글은 같은 버전, 한 글자 고치면 모든 키가 낡는다.
- 스키마는 Codex 구조화 출력 제약(모든 키 required · `additionalProperties: false`)을 지킨다 — 테스트가 재귀로 검사.
- 레인 스크립트(`link_figures.py`·`split_panels.py`·`figure_review.py`)가 자리표시 버전 대신 이걸 쓴다. PyInstaller `datas`에 폴더 추가.

## 2. `docs/figure_server_spec_v2.md` — 서버 명세의 원본

P16 §6(역사 기록으로 남김) + P17 §3.1 + 클라이언트 계획 §2·§3·§10 + 099 §4를 하나로. ocrserver P02와 대조해 어긋남 없음.
- **`POST /figures/workspace`** — 텍스트는 클라이언트가 올린다(키 `file_hash|ocr_digest`)
- **`/figures/detect`는 쪽 단위 항목**(힌트 도판 여러 개, 비어 있을 수 있음), 결과는 `from`/`dismiss`
- 프롬프트 블록 공통 · 0-based · 좌표계 · 워커 요구(치명 오류 stdout+stderr, item 격리, 간격, 기록) · 규모(파일럿 실측)

## 3. 테스트

`tests/test_figure_prompts.py` 4건 — 로드·엄격 스키마 · 스키마가 클라이언트 검증기가 읽는 키를 가짐 · 버전은 글을 따름 · fsis가 비싸게 산 문장들이 들어 있음. 전체 **506** 통과.

## 4. 넘기는 것

ocrserver에 알릴 것: `docs/figure_server_spec_v2.md`(명세) + `papermeister/figure_prompts/`(프롬프트 3벌, 요청에 실려 오므로 서버가 복사할 필요 없음) +
`scripts/link_figures.py --dump`·`split_panels.py --dump`가 떨어뜨리는 **실제 요청 JSON**(서버 테스트 픽스처로). ocrserver P02 §6의 0단계("클라이언트 G 대기")가 풀린다.

## 5. 다음 — H (서버 착수 후)

`figure_client.py`(HTTP: pdfs·workspace·detect·link·panels·jobs) · `detect_figures.py` + `apply_detect`(`from`→verdict 도출, merge·placeholder 처리) · 레인의 제출·폴링·반영 절반 · Phase 2 게이트(② 30편 · ①′ 의심 표본 30).
그 전에 할 수 있는 것: Windows 파일럿 재저장(D) → `figure_review.py`로 상태 확인.
