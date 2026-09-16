# 099 — P16 D′: 규칙이 스스로 의심하는 곳 — `figures.suspect()`와 그 규모

[클라이언트 계획](../docs/figure_pipeline_client_plan.md) §2.1·§8 D′. 서버 변경 없음, 라이브 DB 쓰기 없음. [098](./20260916_098_P16_Review_Sheets_And_Curation.md) §7·§9의 후속.

## 1. 무엇

Phase 1 게이트에서 사용자가 정한 것: **규칙은 여기까지, 안 걸리는 건 LLM에 텍스트를 다 주고 찾게 한다**(D4). 그러려면 규칙이 "어디서 자신이 없는지"를
스스로 말해야 한다 — 그게 ①′ detect의 입력이다. 판정은 `figures.py` 한 곳(`suspect()`), `assemble_document`·`assemble_page`가 끝에 부른다.
결과는 `AssembledFigure.reasons`(도판마다)와 `PageAssembly.suspicions`(도판이 없어 붙일 데가 없는 쪽).

| 사유 | 조건 | 검수에서 나온 근거 |
|---|---|---|
| `dup_number` | 쪽 verdict가 DUP_NUMBER — 두 쪽이 같은 번호 | 1080 Jaekel(PDF 안에 같은 플레이트 3번), 6278 |
| `many_marks` | 쪽에 번호 둘 — 플레이트 둘이거나 펼침 스캔 | 562 · 8833 · Bala 1976 |
| `unmarked_plate_page` | verdict NO_MARK · 사진 ≥ 3 · 어느 사진에도 제 캡션 없음 · 글자 ≤ 160 | Zhou & Zhang 1978 p.28(사진 26장, 표기는 앞 쪽 설명에), Sandford 2005 |
| `no_caption` | body single · 아래에도 위에도 캡션 없음 · 이 쪽·앞뒤 쪽에 플레이트 표기·설명 없음 | 옆 단 캡션(Myrow) · 마주 보는 쪽 캡션 · 표를 그림으로 · 장식 |
| `text_as_figure` | 그림 블록에 `<img>`가 없다(전 캐시 그림 블록의 1.8%) | 8615 `圖版` 글자 |
| `fragmented` | 조각 병합인데 조각 ≥ 6 | — |
| 쪽: `plate_without_pictures` | verdict PLATE인데 도판 0 / 사진 0 + 헤더 표기 + 글자 ≤ 160 | 1191 `Pl. 50`(OCR이 도판을 안 잡음) |
| 쪽: `caption_without_figure` | 사진 0인데 `Fig. N` 캡션 | 다음 쪽 꼬리말로 넘어간 캡션(fsis 4-1), 그림이 텍스트로 |

`plate_inferred`는 사유가 **아니다** — 근거 있는 추론이고 검수 11/11 맞았다.

## 2. 덤 — 표기를 *못 읽던* 구멍 셋 (규칙이 아니라 파싱)

`no_caption` 표본을 렌더해 보니 대부분이 표기를 못 읽은 플레이트 쪽이었다. 인쇄돼 있는데 못 읽는 것은 고친다:
- **`图 版 IV`** — CJK 플레이트 단어가 글자 사이 공백으로 조판됨(`block_text`가 공백을 하나로 접는다) → `图\s?版` 등
- **`Tabl. I`** — 라틴 표기 누락(Toumansky 1935) → `tabl\.`, 스킴은 `табл`
- **`ТАБЛИЦА ХХV`** — 로마 숫자에 키릴 Х(U+0425)·І·С·М, 그리고 유니코드 로마 숫자 `Ⅻ` → `_numeral`이 NFKC + 동형문자 접기. 토큰도 접어 저장(`XXV`)

## 3. 규모

파일럿 100편(도판 3,332, 오늘 규칙으로):

| | 도판 | 쪽 |
|---|---:|---:|
| `no_caption` | 382 | 307 |
| `unmarked_plate_page` | 289 | 27 |
| `many_marks` | 84 | 15 |
| `text_as_figure` | 42 | 39 |
| `dup_number` | 22 | 22 |
| `fragmented` | 6 | 5 |
| 쪽 `caption_without_figure` | — | 29 |
| 쪽 `plate_without_pictures` | — | 8 |
| **합** | **814 (24.6%)** | **≈ 450 detect 항목** |

- 도판 수로는 24.6%지만 **detect 호출 단위로는 쪽**이 맞다 — `unmarked_plate_page` 289장은 27쪽, 즉 27번 호출. 파일럿 ≈ 450 항목 ≈ D8(5분 1건)로 **1.6일**.
  클라이언트 계획 D′ 기준("10% 안팎이면 설계대로")에 든다.
- `no_caption`의 두 번(전후) 표본 24장 렌더: 처음엔 표기 없는 플레이트 쪽이 대부분 → `unmarked_plate_page`로 분리. 남은 것은 옆 단 캡션·마주 보는 쪽 캡션·
  하단 공동 캡션(Miller & Clarkson `FIGURES 17–21`, verdict text_figure라 조건 밖)·표·장식 — **전부 규칙이 모르는 게 맞다.**
- 전 캐시 수치는 §5.

## 4. 요청 모양에 미치는 것 (G 단계 메모)

- detect 항목은 **도판이 아니라 쪽 단위로 묶는다** — 한 쪽의 `no_caption` 셋, `unmarked_plate_page` 26장은 한 항목(힌트 상자 여러 개). 클라이언트 계획 §2.2의 `items[]`는 `figure_key` 하나였다 → `figure_keys[]` + `hint_boxes[]`.
- 쪽 단위 의심(`plate_without_pictures`·`caption_without_figure`)은 붙일 행이 없다 → D 단계에서 **자리표시 행**(`assembly='page'`, 상자 = 쪽 전체)을 두어 키·시도·접기가 같은 테이블에서 돌게 한다. 1191 p.221은 실제로 쪽 전체가 도판이라 그 상자가 대충 맞기도 하다.
- detect 결과에 **`merge`** verdict가 필요하다(클라이언트 계획 §2.3엔 kept/adjusted/replaced/split/not_a_figure뿐) — `unmarked_plate_page`의 정답은 "이 26장은 Plate IV 하나"다.

## 5. 전 캐시 (9,832 파일, 도판 153,115)

| 사유 | 도판 | 쪽(파일럿 비율로 환산) |
|---|---:|---:|
| `no_caption` | 27,449 | ≈ 22,000 |
| `unmarked_plate_page` | 20,745 | ≈ 1,900 |
| `text_as_figure` | 1,969 | ≈ 1,800 |
| `many_marks` | 1,268 | ≈ 230 |
| `dup_number` | 488 | 488 |
| `fragmented` | 290 | ≈ 240 |
| 쪽 `caption_without_figure` | — | 2,522 |
| 쪽 `plate_without_pictures` | — | 241 |
| **합** | **51,195 (33.4%)** · 5,564편 | **≈ 29,000 항목** |

- 도판 기준 **33.4%** — 파일럿(24.6%)보다 높고, 클라이언트 계획 D′의 "40%면 ①′가 기본 경로" 쪽에 가깝다. 사용자 결정(D4)이 이미 그 방향이므로 설계는 그대로다.
  다만 **비용의 4분의 3이 `no_caption`** 이다.
- **`no_caption`은 ①′ 전에 보낼 이유가 없다.** ② link는 어차피 논문의 도판 전부를 받고 텍스트 전체를 읽어 캡션을 찾는다 — 규칙이 힌트를 못 찾은 도판은
  ②가 찾으면 끝이고, ②도 못 찾으면 그때 `link_mismatch`로 ①′에 간다(클라이언트 계획 §2.1의 6·7 경로). 그러면 ①′ 사전 항목은 **≈ 7,000(전 캐시) · ≈ 140(파일럿)** 으로 준다.
  → `no_caption`은 detect 트리거가 아니라 **② 입력의 힌트**(`caption_hint=''`인 도판)로 둔다. 코드는 그대로(사유는 기록), 레인의 대상 선정에서 뺀다.
- 그래도 도판을 **만들지 못한** 것(`plate_without_pictures` 241)과 **잘못 나눈** 것(`unmarked_plate_page` ≈ 1,900쪽·`many_marks` 230·`dup_number` 488)은 ② 전에 ①′가 먼저 봐야 한다 —
  ②는 받은 도판 목록을 고치지 않기 때문이다.
- 전체 백필은 계획에 없다(요청 단위, P16 §7.3). 위 수치는 규모 감각용.
