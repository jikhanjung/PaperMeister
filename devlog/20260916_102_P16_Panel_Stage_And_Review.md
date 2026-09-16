# 102 — P16 F: ③ 패널 단계의 클라이언트 쪽 · 라벨 재연결 · 5범주 검수 보고 — 그리고 마이그레이션 인덱스 버그

[P17](./20260916_P17_P16_Client_Readiness_For_ocrserver.md) §3.5·3.10, [클라이언트 계획](../docs/figure_pipeline_client_plan.md) §4·§8 F. 서버 변경 없음, 라이브 DB 쓰기 없음(온라인 백업 사본).

## 1. `papermeister/figure_panels.py`

| 함수 | 무엇 |
|---|---|
| `panel_key(row, prompt, dpi=216)` | **이미지의 정체만**: 해시·쪽·상자·dpi·프롬프트. entries는 안 들어간다(D6) |
| `entries_digest(entries)` · `panel_entries_digest` 칸 | 패널을 어떤 항목에 맞췄는지. 지금 항목과 다르면 **재분할이 아니라 재연결** |
| `split_targets(pf, …)` | due / **rematch** / excluded(사유: dismissed · page_placeholder · no_caption · entries_lt_2 · panels_locked · split · **map** · attempts_exhausted). 지도 제외는 **재분할에만** — `kind`는 이 단계의 결과라 첫 실행 전엔 지도가 없다(fsis EC §6-9) |
| `panel_item(row, …)` | 요청 항목: `figure_key = id@panel_key`, 0-based 쪽, 상자, 캡션, 항목, **조각 상자를 도판 좌표(0..1000)로 변환**(`to_figure_frame`; 역변환 `to_page_frame`은 표시용), 라벨 힌트, dpi |
| `validate_panel_result(item, result, siblings)` | fsis `validate_prediction` 이식 + `non_compound_reason`·`annotation_indices` + **뒤쪽 무라벨 패널 채우기**(안 붙은 패널 수 = 안 쓰인 항목 수일 때만 읽는 순서로, EC §6-1) + 검수 사유 |
| `apply_panels(row, …)` | `protection().panels` · 내용 해시 unchanged · `FigurePanel` 재생성(`entry_orders_json`·`annotation`) · `kind`·`is_compound`·`panel_notes_json`(사유·범례 인덱스·이미지 크기) |
| `rematch(row)` | 라벨 정규화로 패널 ↔ 새 항목. **라벨 있는 패널마다 정확히 하나**에 걸려야 한다 — 번호 중복·무표지는 순서로 짝짓지 않는다(DG §6-5). 안 되면 `entries_changed_unmapped` 표시, 상자는 그대로 |

검수 사유: `panels_0` · `panels_1_with_siblings`(같은 쪽 형제 있음 = 이미 나뉜 쪽) · `panel_count_out_of_range`(범례 뺀 항목의 ½~2배 밖) · `single_image_many_captions` · `image_incomplete` · `not_a_figure`.

## 2. `papermeister/figure_review.py` + `scripts/figure_review.py` — 다섯을 같이 센다 (DG §6-6)

`link_targets`·`split_targets`·행의 사유를 **그대로** 써서 센다 — 보고서가 자기 규칙을 갖고 있으면 규칙이 바뀐 날 레인과 어긋난다.
`DETECT_TRIGGERS`(dup_number · many_marks · unmarked_plate_page · text_as_figure · fragmented · 쪽 의심 둘)에 **`no_caption`은 없다**(099 §5 — ②가 푼다).

라이브 사본(온라인 백업)에 D 저장 후 파일럿:

```
1. Waiting for a stage    link 3,732 · detect 510 · panels 0 · rematch 0
2. Fetched, not applied   — (서버 뒤)
3. For a person           no_caption 468 · unmarked_plate_page 289 · many_marks 84 · text_as_figure 51 · caption_without_figure 48 · dup_number 22 · fragmented 9 · plate_without_pictures 8 · (plate_inferred 8)
4. Outside the candidates panels: no_caption 3,732 (②가 안 돌았으니) · placeholder 56
5. Preserved              dismissed_by_user 2
```

## 3. `scripts/split_panels.py` — 서버 전 절반

due/rematch/excluded 사유 출력, `--dump`로 요청 항목, `--rematch --execute`로 재연결. 지금은 due 0(캡션이 없으니), excluded `no_caption` 3,752.

## 4. 🔴 D의 마이그레이션 버그 — 사본에서 잡음

`init_db`는 `create_tables()` → `_migrate()` 순서다. D가 `continuation_of`(self FK)를 더하자 peewee가 **컬럼이 생기기 전에** `CREATE INDEX figure_continuation_of_id`를 만들었고,
SQLite는 그걸 빈 인덱스로 둔다 → `integrity_check`가 "row N missing from index", 이후 `figure` **UPDATE가 "database disk image is malformed"**.
첫 사본 실행에서 108편 중 2편이 그 오류로 실패하고 나머지 refresh도 안 써져 있었다(사유 저장 13행뿐). 처방: 컬럼을 더한 표는 **`REINDEX`**. 회귀 테스트는 `74f34c9`(D 이전) 모델로 옛 스키마 DB를 만들어 `init_db` 뒤 `integrity_check == ok`.
**Windows에서 D 버전으로 `--execute`를 돌리기 전에 잡혀서 다행** — 라이브 DB는 아직 D 이전 스키마다.

교훈: 스키마를 바꾸면 **단위 테스트 + 라이브 사본(온라인 백업 API로 — `cp`는 WAL 때문에 일관성이 없다) 실행**을 둘 다.

## 5. 테스트

`tests/test_figure_panels.py` 9건(대상·키·조각 좌표·정상 답 + 무라벨 채움·거절과 시도·검수 사유·재연결 성공/실패·지도는 재분할에만·5범주) + `test_figure_store.py` +1(옛 스키마 마이그레이션 무결성). 전체 **510** 통과.

## 6. 다음 — G

프롬프트·스키마 파일 3벌(`papermeister/figure_prompts/`) + 명세 v2(P17 §3.1 + 099 §4의 detect 쪽 단위·`merge` verdict + 클라이언트 계획 §10.1 작업 폴더) → ocrserver에 넘긴다.
