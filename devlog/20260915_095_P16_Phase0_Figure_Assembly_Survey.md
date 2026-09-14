# 095 — P16 Phase 0: 도판 조립 dry-run, 전 캐시 실측

[P16](./20260914_P16_Figure_Panel_Split.md)의 Phase 0. 서버 변경 없음, DB 쓰기 없음.
조립 판정을 `papermeister/figures.py` 한 곳에 만들고, 그 판정을 OCR 캐시 전체(9,832개)에 돌려 규모를 셌다.

## 1. 만든 것

| 파일 | 내용 |
|---|---|
| `papermeister/figures.py` | 조립 판정. `assemble_page(page, text)` → `PageAssembly`(verdict, figures, dropped). 모델·DB 없음 |
| `tests/test_figures.py` | 50건 — fsis가 비싸게 산 경우 + 이번에 실데이터에서 찾은 경우 |
| `scripts/assemble_figures.py` | read-only 조사. 전 캐시(≈4분, WSL에서 `/mnt/c` 캐시 직독) 또는 `--sample N`. `--report-out`·`--pilot-out` |

조립 방식은 셋이다.

| `assembly` | 언제 |
|---|---|
| `single` | 그림 블록 하나 = 도판 하나 |
| `plate_page_union` | 그림 블록 ≥2 · 머리말/제목/캡션에 플레이트 번호 하나 · 어떤 그림 아래에도 `Fig. N` 캡션 없음 (fsis P41) |
| `caption_group_union` | **이번에 추가.** `Fig. N` 캡션 하나가 같은 단 위쪽 그림 블록 여럿을 가진다 |

## 2. 계획에 없던 것 — 실데이터가 고친 규칙

### 2.1 조각난 도판 (`caption_group_union`)

200편 표본을 먼저 돌렸더니 "플레이트 번호 없음" 쪽에 **OCR이 도판 하나를 여러 블록으로 자른 경우**가 섞여 있었다.
Iv et al. 2015 Figure 2(A–D 사진 넷, 조각마다 "A. Ajacingenia yanshini" 소제목), 저어콘 격자 14장 위의 `그림 3-1-22`.
블록별로 조립하면 조각마다 소제목이 캡션으로 붙는다.

규칙: `Fig. N` 캡션이 그림 폭의 50% 이상 겹치는 **가장 가까운 아래 캡션**이면 그 그림을 소유.
사이에 본문 블록이 끼거나, 그림 바로 위(40‰)에 자기 `Fig. N` 캡션이 있으면(캡션-위 양식) 끊긴다.
조각 사이의 짧은 `Caption`은 **중심이** 조각 합집합 ±25‰ 안이면 `label_hints`로 — 처음엔 완전 포함으로 했다가
라벨이 사진보다 넓게 인쇄되는 Iv 도판에서 라벨 넷을 모두 놓쳤다.

**PDF를 렌더해 눈으로 확인**했다(빨강=도판, 파랑=조각): Iv p.2, Lees 2002 p.13(FIGURE 5 둘·6 셋),
Teichert 2009 p.232(FIG. 141의 1a·1b·1d와 1c가 한 도판 — 텍스트만으로는 판단 못 했던 것), 한반도중서부 보고서 p.34(격자 둘). 모두 맞다.

같은 렌더에서 본 한계 둘:
- OCR 조각 상자가 입자보다 **좁다**. 조각 상자를 패널로 쓰지 않고 Astra에 **힌트로만** 넘기는 이유(P16 §4.3)
- KIGAM 워터마크가 캡션 없는 `single`이 됐다. 캡션 블록과 겹치는 캡션 없는 그림은 600편 표본에서 280/10,487(2.7%)인데,
  열어 보면 대부분 Treatise의 도판 안 라벨이다 — 워터마크 규칙은 만들지 않고 파일럿에서 본다

### 2.2 이중 번호 플레이트

`many_marks`(번호 둘 → 병합 안 함) 표본을 열어 보니 Bruton et al. 2004가 쪽마다 학술지의 "Tafel 13"과 저자의 "Plate 2"를
같이 찍고 있었다 — 플레이트 하나다. 반면 Zhou 1982 도감의 "图版 58 / 图版 59"는 진짜 두 장.
**번호 체계(plate·tafel·planche·табл·CJK)별로 번호가 하나씩이면 한 플레이트**, 한 체계에 번호가 둘이면 여러 장. 이름은 `Plate`를 우선한다.

### 2.3 그 밖에 fsis에서 그대로 가져오지 않은 것
- 캡션 힌트는 세로 거리만이 아니라 **가로 겹침**도 요구 — 2단 조판에서 옆 단 캡션을 가져가지 않게
- 플레이트 번호 숫자는 **대문자만** — "Plate mix"가 1009번이 되지 않게. 300 초과는 오독
- 독일어 Tafel/Taf., 러시아어 Таблица, 简体 图版 추가

## 3. 결과 (전 캐시, 2026-09-15)

| 항목 | 값 |
|---|---:|
| 캐시 / 구조화 | 9,832 / 9,830 |
| 쪽 | 353,741 |
| 그림 블록 | 211,610 |
| └ 제거: 머리말·꼬리말 띠의 로고 / 작은 단독 그림 | 1,532 / 6,265 |
| **도판** | **156,502** |
| └ 보통 | 149,828 |
| └ 플레이트 쪽 병합 | 4,463 (1,008편) |
| └ 조각 병합 | 2,211 (블록 6,295개, 라벨 힌트 있는 것 631) |
| 아래 캡션 힌트 있음 | 98,631 (63%) |
| 보통 도판 중 캡션이 소패널을 말하는 것 | 17,071 |
| 캡션에 지도 표기 | 6,994 |
| **패널 분할 후보 (추정)** | **23,745** = 플레이트 + 조각 도판 + 소패널 캡션 |
| 편당 도판 | 중앙 6 · p90 28 · 최대 2,528 (Treatise 합본) |
| 번호 둘로 병합 안 한 쪽 | 348 |

규칙 변경 전(플레이트·단독만) 같은 캐시: 도판 160,794, 플레이트 4,432, `many_marks` 385, 분할 후보 22,304.

**읽는 법**
- 분할 후보 23,745는 **상한 쪽 추정**이다. 실제 대상은 ②가 entries ≥ 2를 돌려준 도판이고, 지도는 기본 제외.
- 규모 감: ③ Astra를 fsis 운영 속도(장당 15~30초)로 전부 돌리면 100~200시간. 요청 단위 실행(결정 3)이라 한 번에 이만큼 가지는 않는다.
- ②는 논문 1회라 상한은 도판이 있는 편 수(~9,800편)다.

## 4. 파일럿 30편

`--seed 16`으로 층별 무작위, 80쪽 이하. 플레이트 9 · 조각 도판 6 · 소패널 캡션 7 · 비라틴 문자 5(키릴·한글 2·한자·가나) · 지도 3.

| 층 | 논문 |
|---|---|
| plates | Vidal 1998 · Pillola 1996 · Fletcher 2003 · Whittington 1988 · Lu 1954 · Kobayashi & Huzita 1942 · Hemming 1958 · 早寒武世带网状鳞片的蠕形海生动物 · Beecher 1902 |
| cut_up | Beckmann et al. 2007 · Benedetto 1975 · Park & Kihm 2015 · Szczepanik & Salwa · Whittington 1990 · Losso & Ortega-Hernández 2022 |
| compound | Fortey et al. 2011 · Wiman 1906 · Li 2022 (Palaeontology) · Kennard & James 1986 · Wang et al. 2019 · Cortijo et al. 2015 · Kumar et al. 1984 |
| non_latin | Balaova 1969 · Cooling and Thermal Histories… (한글) · 박지훈 2017 · Zhou et al. 2005 · Shimada & Tanimura |
| maps | Kouraiss et al. 2019 · Clarkson & Howells 1981 · Bauer 2010 |

같은 명령을 다시 돌리면 같은 목록이 나온다: `python scripts/assemble_figures.py --pilot-out pilot.json`.

## 5. 다음 — Phase 1

- 스키마(`Figure`·`FigureEntry`·`FigurePanel`) 마이그레이션. `AssembledFigure.label_hints`는 `blocks_json` 옆에 보관
- `assemble_figures.py --execute`로 파일럿 30편 조립 저장 → Text 탭 도판 목록 → **사람이 보고 맞다**가 게이트
