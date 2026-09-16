# 101 — P16 E: ② 캡션 단계의 클라이언트 쪽 — 보낼 것 · 믿을 것 · 쓸 것

[클라이언트 계획](../docs/figure_pipeline_client_plan.md) §3·§8 E, [P17](./20260916_P17_P16_Client_Readiness_For_ocrserver.md) §3.4. 서버 변경 없음, 라이브 DB 쓰기 없음(사본 dry run).

## 1. `papermeister/figure_link.py` — 호출은 안 한다

| 함수 | 무엇 |
|---|---|
| `ocr_digest(pages)` | 캐시 텍스트의 정체(쪽별 sha256). 작업 폴더 키(`file_hash\|ocr_digest`, 클라이언트 계획 §10.1)이자 `link_key`의 일부 |
| `link_key(row, digest, prompt_version)` | 입력의 정체만: 해시·쪽·상자·텍스트·프롬프트. 이게 같으면 다시 안 부른다 |
| `link_targets(pf, …)` | 파일의 도판을 **due / context / excluded(사유)** 로. 접힘·자리표시·`captioned_plate`(제 캡션 — 설명을 같이 주면 모델이 거기 쏟아넣는다, fsis 2360)는 입력에서 빼고, **사람이 잠근 행은 context로 넣는다**(빼면 모델이 그 설명을 이웃에 붙인다, fsis §6-4). 시도 3회 소진은 `--retry-errors`로만 |
| `link_payload(pf, pages, targets, …)` | 요청 본문: 도판마다 id·0-based 쪽·상자·조립·page_kind·이름/캡션/라벨 힌트·의심 사유·`locked`(+잠긴 행은 캡션·항목) + 힌트(`plate_pages`·`explanation_pages`·`caption_pages`). **쪽 텍스트는 없다** — 작업 폴더가 갖는다 |
| `workspace_payload(pf, pages)` | 작업 폴더 원료: 캐시 `pages[].markdown` 그대로 + digest |
| `validate_link_result(payload, result, pages, existing)` | 쓰기 전 검증(§2) |
| `apply_link(targets, check, …)` | 반영(§3) |

## 2. 검증 — 거절(답의 잘못)과 검수(사람이 볼 것)를 가른다

| 거절 | |
|---|---|
| 보낸 적 없는 `figure_id` | `unknown` |
| `caption_pages`가 논문 밖 / 비어 있음 | `caption_pages_outside_paper` |
| 캡션 비어 있음 · entries 모양 틀림 · `continuation_of`가 목록 밖 | 그 도판만 거절, job은 계속 |
| 잠긴(context) 도판에 대한 답 | `locked` |
| 출처 있는 이전 결과보다 항목이 **줄었다** | `entries_shrank` — 덮지 않는다 (출처 없는 원본이면 덮는다: 지어낸 것일 수 있다, fsis 3607) |

| 검수 사유(행의 `uncertain_reasons_json`에 덧붙임) | |
|---|---|
| `caption_not_printed` | 캡션 단어의 80% 미만이 그 쪽들에 있다 — 묘사를 지어낸 것 |
| `description_not_printed` | 항목 설명 단어의 70% 미만이 캡션·그 쪽들에 있다 |
| `caption_shared` | 같은 쪽 다른 상자 도판이 같은 캡션(80자) — fsis 190행 |
| `plate_no_entries` | 플레이트인데 캡션만 있고 항목 0 — 배치가 플레이트를 빠뜨리는 fsis DG §4-3 |

`skipped`는 **"못 찾음"** — 기존 값 그대로, 시도만 센다(fsis §6-7의 매일 `[]` 덮어쓰기 방지).

## 3. 반영

파일 단위 트랜잭션. `protection(row).caption`이면 건너뜀. 결과 **내용 해시**(`link_result_digest`)가 같고 키가 같으면 unchanged(파일명이 아니라 내용, fsis 268).
쓰는 것: `caption`·`caption_source`·`caption_page`·`caption_pages_json`·`name`(인쇄 표기 그대로)·`continuation_of`·`link_*`·`linked_at`, entries는 지우고 다시(`label`·`printed_label`·`label_status='printed'`·`specimen_number`·`description`).
이름 정규화(P17 §3.4)는 **불필요해졌다** — 결과가 `figure_id`로 온다(fsis는 행이 아니라 이름으로 맞춰야 해서 필요했다). ③ 재연결(F)에서 라벨 정규화만 남는다.

## 4. `scripts/link_figures.py` — 서버 전 절반

`--dump`로 논문마다 `link_<id>.json`·`workspace_<id>.json`을 떨어뜨리고 크기를 잰다. 제출·폴링·반영은 H(서버 뒤). 라이브 사본에서 파일럿:

| | |
|---|---|
| 논문 108 · due **3,752** · context 0 · excluded 3(dismissed) | |
| 요청 | 중앙값 **6.2 KB**, 최대 124 KB(215쪽 PLoS 모음), 합 1.4 MB |
| 작업 폴더(텍스트) | 중앙값 **147 KB**, 최대 1.8 MB, 합 **35.8 MB** — 논문당 1회 |

P16 §8 "편당 호출 시간·한도 소모 측정 전"의 **입력 쪽**은 이렇게 답이 났다. 텍스트는 전부 서버가 받으므로 요청 자체는 작다.

## 5. 테스트

`tests/test_figure_link.py` 9건 — 대상 선정과 제외 사유 · payload 모양(텍스트 없음) · 정상 답 반영과 unchanged · 밖의 id/쪽 거절 · 지어낸 설명 검수 ·
skipped는 기존 값 유지 + 시도 · 항목 감소는 질문 · 공유 캡션·빈 플레이트 · 잠긴 캡션은 context이고 절대 안 씀. 전체 488 통과.

## 6. 다음 — F

`panel_key` 재정의(entries 제외) · `split_targets`(제외 사유 출력) · 조각 상자 → 도판 좌표 변환 · 라벨 재연결 · `figure_review.py` 5범주 보고.
