# 098 — P16 검수 도구: 층별 contact sheet와 결정 기록(replay 가능)

[P17](./20260916_P17_P16_Client_Readiness_For_ocrserver.md) §3.9 = 클라이언트 계획 §8의 **A**. 서버 변경 없음, 라이브 DB 쓰기 없음.

## 1. 왜 먼저

Phase 1 게이트는 "파일럿 100편(도판 3,750)의 도판 목록을 사람이 보고 맞다"인데, Text 탭에서 하나씩 누르는 건 현실적이지 않고
**틀렸을 때 기록할 경로가 없었다**(`user_confirmed`·`dismissed_by='user'` 칸은 있는데 세우는 코드가 없음). fsis DG §8-6 "검수 화면을 일찍",
§6-5 "사람 수정도 재현 가능한 결과로". 097 §4가 손으로 한 "규칙이 발동한 쪽을 렌더해 눈으로"를 명령으로 만들었다.

## 2. `scripts/figure_contact_sheet.py` — `papermeister/figure_sheet.py`

- 파일럿(또는 `--paper-ids`)의 캐시에 `figures.assemble_document`를 돌리고, **그림 블록이 있는 쪽**을 규칙이 한 일에 따라 9층으로 나눈다
  (첫 매치가 이긴다): `dropped`(그림 블록은 있는데 도판 0 — 필터가 버린 것) · `plate_inferred` · `dup_number` · `many_marks` · `captioned_plate` ·
  `plate_single` · `plate_union` · `cut_up` · `body`. 층마다 **무엇을 확인할지**를 헤더에 쓴다(각 층은 다른 실수를 본다).
- 층마다 `--per-stratum`(기본 40, `--all`이면 전부)을 seed로 뽑아 **쪽을 렌더하고 그 위에 그린다** — 그림 블록·캡션 블록은 얇게, 조립된 도판은
  조립 방식별 색으로(단일 파랑 · 플레이트 병합 빨강 · 조각 병합 초록 · 한 장 플레이트 보라 · 도판별 캡션 사진 주황). 옆에 이름 힌트·조립·page_kind·
  플레이트 번호(추론 표시)·캡션 힌트·라벨 힌트·verdict·dropped 사유.
- 도판 식별자: 저장돼 있으면 `#id`, 아니면 `file:page:x0,y0,x1,y1` — 둘 다 `figure_curate.py`가 받는다. **저장 전에도 돌아간다**(라이브 DB 읽기 전용,
  PDF는 `pdf_cache`). 출력은 `<DATA_DIR>/tmp/p16_review/index.html` + 층별 HTML + `img/`.
- 파일럿 실측(WSL, 읽기 전용): PDF 108 · 그림 있는 쪽 **2,857** — dropped 34 · plate_inferred 11 · dup_number 28 · many_marks 7 · plate_single 467 ·
  plate_union 191 · cut_up 94 · body 2,025. 240쪽 렌더 51초, 21MB.

## 3. `scripts/figure_curate.py` — `papermeister/figure_curation.py`

- `confirm` · `dismiss` · `restore` · `rename --name` · `set-bbox --bbox` · `merge`(같은 파일·쪽, 첫 행이 살아남고 상자·블록 합집합, 나머지 접힘).
  모두 `--reason` 필수, `--execute` 없으면 dry run이 변경을 보여준다. 대상은 `--figure-ids` 또는 `--keys`.
- 모든 연산이 **`user_confirmed`를 세운다** — 자동 경로가 덮지 않는 유일한 근거. `dismiss`는 `dismissed_by='user'`라 재조립이 되살리지 않는다
  (테스트: 접은 뒤 같은 규칙으로 재조립 → restore 0 · create 0).
- **기록**: 적용된 연산은 `<DATA_DIR>/tmp/p16_curation/YYYYMMDD.json`에 행의 **정체**(해시·쪽·상자·조립 = `figure_store`의 키)와 변경 전 값과 함께 append.
  `replay --record FILE`이 재조립·재OCR 뒤 **id가 아니라 정체로** 행을 다시 찾아 같은 결정을 얹는다. 대상 행이 하나라도 없으면 그 항목은 건너뛴다
  (merge 절반은 안 하느니만 못하다). fsis의 `scripts/curation/<date>.json` + 적용기와 같은 이유 — DB에만 있는 수정은 DB를 다시 만드는 순간 사라진다.
- 도판 테이블이 없으면 "먼저 `assemble_figures.py --execute`"라고 말하고 끝난다.

## 4. 첫 발견 — 도구가 바로 보여준 것

`dropped` 층 첫 쪽들 중 **Westergård, Paradoxides oelandicus p.27**: 번호 캡션(`Fig. 10. …`)이 달린 작은 본문 그림이 `tiny`(면적 4,000‰² 미만)로 버려졌다.
fsis EC §4-3의 폭 필터 사고와 같은 모양 — P17 §3.8 후보 2("좁은 사진이 TINY_AREA에 걸리는가")가 **첫 표본에서 실증**됐다.
처방 후보: 번호 캡션이 바로 아래 있으면 크기와 무관하게 도판(캡션이 있는 그림은 장식이 아니다). **C 단계에서 전 캐시 dry-run으로 규모를 재고 넣는다.**
나머지 dropped 33쪽은 표지·목차 쪽의 출판사 마크(정상).

## 5. 테스트

`tests/test_figure_review.py` 15건 — 층 분류 7 · 표본 추출 반복성 · 그리기(픽셀) · HTML(층 헤더·`#id`·키) · PDF 렌더(Pillow가 만든 1쪽 PDF) ·
curate(reason 필수 · 키 파싱 · dismiss 뒤 재조립 · merge 합집합/같은 쪽 제약 · rename/set-bbox 인자 · **기록 replay**: 행을 지우고 재조립한 뒤 이름·접힘이 다시 얹힘, 없는 행은 skip).
전체 456건 통과, ruff clean.

## 6. 다음 — B

Windows에서(앱 닫고) `assemble_figures.py --pilot … --execute` → `figure_contact_sheet.py --pilot …`를 다시 돌리면 식별자가 `#id`로 바뀐다 →
`index.html`을 열어 층별로 본다 → 틀린 것은 `figure_curate.py … --execute`. 게이트 판정은 층별로: `plate_inferred` 11 · `dup_number` 28 · `many_marks` 7 · `dropped` 34는
**전부**, 나머지는 표본 40씩.
