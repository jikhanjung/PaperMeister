# 100 — P16 D: 스키마 보강 · 보호 판정 한 곳 · 사람의 행이 조각을 대변 · 쪽 의심 자리표시 행 · 파일 단위 격리

[P17](./20260916_P17_P16_Client_Readiness_For_ocrserver.md) §3.6·3.7 + [클라이언트 계획](../docs/figure_pipeline_client_plan.md) §2.4 + [099](./20260916_099_P16_Uncertainty_Reasons.md) §4.
서버 변경 없음. 라이브 DB에는 **사본으로 dry run**만(§5).

## 1. 스키마 — `_migrate()`가 표 하나로 채운다

`database.py`의 figure 블록을 `(표, 컬럼, DDL)` 표로 바꿨다. 표가 없으면 `create_tables()`가 통째로 만들고, 있으면 없는 컬럼만 더한다.

| 표 | 칸 | 쓰는 단계 |
|---|---|---|
| `figure` | `uncertain_reasons_json` · `bbox_source`(assembly \| detect \| user) | ① 099의 사유 / 누가 상자를 정했나 |
| | `detect_key` · `detect_attempts` · `detected_at` · `detect_caption_json` | ①′ |
| | `caption_pages_json` · `continuation_of`(self FK) | ② — 두 쪽에 걸친 설명(fsis EC §6-12), 세 쪽에 걸친 한 그림(§4-3) |
| | `panel_entries_digest` | ③ — 항목이 바뀌면 재분할이 아니라 재연결(D6) |
| | `bbox_locked` · `caption_locked` · `panels_locked` | 보호(§2) |
| `figureentry` | `printed_label` · `label_status` · `specimen_number` | ② — 편집 보정과 인쇄 번호 분리(fsis DG §4-6) |
| `figurepanel` | `annotation` | ③ — 범례 표시는 두되 세지 않는다(DG §4-5) |

`dismissed_by`에 `detect`, `assembly`에 `page`(§4) 값이 늘었다. 회귀: 옛 표에서 컬럼을 지우고 `init_db` → 다시 생긴다.

## 2. 보호 판정 — `figure_store.protection(row) -> Protection(assembly, caption, panels)`

fsis는 `user_confirmed`·`own_caption`·`manual_fix`를 경로마다 다르게 봐서 사람이 고친 33행이 덮일 뻔했고(EC §6-4), 캡션은 지켰는데 `alt`는 덮였다(§6-13).
여기서는 **함수 하나**: `user_confirmed`(또는 사람이 접음)는 셋 다, `*_locked`는 그 칸만. 재조립(`plan_store`)·curate가 이미 이것을 보고, ②·③ 반영도 이것만 본다.
`set-bbox`·`merge`는 `bbox_locked` + `bbox_source='user'`를 세운다 — 상자만 고치고 캡션·패널은 자동에 맡길 수 있게.

재조립은 **자기가 접은 것만 되살린다**(`dismissed_by='reassembly'`). detect나 사람이 접은 행은 규칙이 다시 만들어도 접힌 채다.

## 3. 사람의 행이 조각을 대변한다 — `plan_store`의 `absorbed` / `contested`

fsis EC §6-14: 좌표를 넓힌 행이 있으면 동기화가 원본 청크를 매일 새 행으로 되살렸다. PaperMeister는 병합·set-bbox 행이 `blocks_json`에 자기 블록을 갖고 있으므로,
재조립이 만든 도판의 **블록 전부가** 같은 파일·쪽의 보호된 행 하나에 정확히 들어 있으면 `absorbed`(만들지 않음). **포함 관계는 쓰지 않는다** — 독립 사진을 삼킨다.
두 보호 행이 같은 블록을 주장하면 `contested`(만들지 않고 셈). 테스트: merge 뒤 재조립 → create 0.

## 4. 쪽 의심의 자리표시 행 — `assembly='page'`

`plate_without_pictures`·`caption_without_figure`는 붙일 도판이 없다. `with_placeholders()`가 그런 쪽마다 상자 = 쪽 전체, `blocks=()`, 사유를 실은 행을 만든다.
키·시도·접기·보호가 다른 행과 같은 테이블에서 돈다. 의심이 풀리면(다음 재조립에 사유가 없으면) 보통 행처럼 접힌다. Text 탭(`figures_for_paper`)은 뺀다.

## 5. `store_mode` 파일 단위 격리 + 라이브 사본 dry run

파일마다 `try` — 캐시 하나가 깨져도 나머지는 간다(fsis DG §6-1). 실패 목록과 종료코드 1. 읽기 전용 dry run이 마이그레이션 전 DB를 만나면
컬럼 이름을 들어 "앱을 한 번 열거나 `cli.py list papers -n 1`로 마이그레이션"이라고 말하고 끝난다(`--execute`는 `init_db`라 스스로 마이그레이션한다).

라이브 DB **사본**(3GB, `/tmp`)을 마이그레이션해 파일럿 108파일 dry run:

| | |
|---|---|
| 도판 | 3,790 (의심 969) |
| new | **66** = 자리표시 37 + Bala 1976 플레이트 병합 9 + Toumansky 1 (099의 키릴 `ХХV`·`Tabl.` 파싱 수정 — 사용자가 지적한 8833 #416–439가 쪽별 플레이트로 묶인다) |
| refreshed | 909 (사유 저장) · folded 30 (위 두 편의 옛 single) |
| 사람 결정 | 2 (#791·#889) 그대로 · absorbed 0 · contested 0 · **failed 0** |

## 6. 테스트

`test_figure_store.py` +8(마이그레이션 · 보호 판정 · 병합 뒤 조각 흡수 · 두 행이 주장 · 잠긴 상자 · 남의 접기는 안 되살림 · 사유 저장·갱신 · 자리표시 행 생성·숨김·접힘).
전체 479 통과.

## 7. 다음

Windows에서 `assemble_figures.py --pilot … --execute`(마이그레이션 포함) → 시트 재생성. 그다음 **E**: `link_payload`(도판 목록 + 힌트만, 클라이언트 계획 §3) + `validate_link_result`·`apply_link`(P17 §3.4, 보호 판정은 §2의 것).
