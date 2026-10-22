# 114 — 4월 배치 재OCR, 조각 유실 사고와 가드, 서버 몫 따라가기

2026-08-28 ~ 09-09 작업의 기록. 그동안 HANDOFF에만 있던 내용을 2026-10-22 HANDOFF 정리 때 옮겼다.
코드는 `scripts/reocr_legacy_ocr.py`, `papermeister/text_extract.py`(`MIN_PAGE_COVERAGE`), `papermeister/ocr.py`(wrapper 몫).

## 왜

2026-04-09 이전 OCR은 옛 평문 마크다운이라 Text 탭이 헤딩·캡션·그림을 살리지 못한다(형식 전환은 04-09 ↔ 05-13 사이,
이후 처리분은 전부 `data-label` 있는 레이아웃 HTML — [094](./20260828_094_Text_Tab_Reads_The_OCR_Layout.md)).
텍스트에서 레이아웃을 되살릴 방법은 없어 재OCR뿐이다. 대상 **2,049편 / 58,402쪽**.

## 실행 방식

- **대상은 캐시에서 도출한다** — 라벨 없는 JSON이면 대상, 생기면 자동 제외. 그래서 중단·재실행이 그대로 이어달리기다. 짧은 논문부터(중앙값 13쪽, 최장 832쪽)
- 재OCR은 `force=True`라 로컬 캐시와 Zotero sibling 양쪽을 건너뛴다. 끝나면 스크립트가 **sibling JSON을 in-place 교체**한다 —
  안 하면 캐시 미스 때 Zotero에서 옛 JSON을 도로 받아와 조용히 되돌아간다
- 앱을 닫고 Windows에서. references가 끝난 뒤라 ocrserver 경합은 없었다
- **실패분은 DB에 failed로 안 찍힌다**(status는 `processed` 유지) → 재실행이 그냥 집어간다
- 본문 없는 캐시도 대상에 넣는다(기본) — `Geyer - The Cambrian of the Moroccan Atlas`(pf=3767, 0/41쪽)가 `processed`라 앱 Retry로 못 잡던 경우
- `--incomplete`는 "부족한 것 전부"를 넣는다. 기본이 아닌 이유는 Hansen처럼 100%에 영영 못 닿는 논문이 매번 다시 잡히기 때문(references give-up 카운터와 같은 교훈)

## 1차 (2026-08-30, 42.6시간)

1,892편 변환 / 54편 실패, 잔여 52편. 실패는 **끝부분 몇 초에 몰렸다** — 08-30 12:51부터 서버 앞단이 POST를 413으로 막았고(직전 poll은 JSON 대신 HTML),
53편은 wrapper에 닿지도 못했다(서버 job 목록에 없음). 파일 크기 문제가 아니었다(실패 최소 1.8MB, 직전에 240쪽 성공). 일시 장애.

재발 방지(`b41b8fe`): **`ServerGate`** — 연속 3회 실패면 서버 다운으로 보고 최대 15분 복구 대기, 안 돌아오면 정상 종료.
없으면 프록시가 몇 분 삐끗할 때 남은 큐가 통째로 "실패"로 소진된다(1차에서 실제로 그랬다).

## 🔴 조각 유실 사고 (2026-09-08)

서버가 `done_with_errors`로 몇 쪽만 돌려준 걸 클라이언트가 성공으로 받아 **논문 9편이 자기 자신의 2~8%로 덮어씌워졌다**
(Walcott 1916이 694쪽 → 18쪽). 캐시·DB passage·Zotero sibling 세 곳 모두. 유일한 가드가 "텍스트가 하나라도 있나"였는데 조각은 그걸 통과하고,
구조화된 정상 출력이라 재처리 대상으로도 안 보였다.

- `text_extract.MIN_PAGE_COVERAGE`(0.5) + `_reject_incomplete_ocr()` — **아무것도 쓰기 전에** 거부하므로 기존 데이터가 남는다. 더 적은 쪽으로 기존 캐시를 덮는 것도 막는다(`8a9663e`)
- 배치 스크립트의 `is_fragment()` — 이미 조각으로 저장된 것을 다시 대상에 넣는다(문서 크기 기준, `2cc288f`). 별도 리셋 불필요
- 전수 스캔: 조각은 9,832개 중 15개, 그중 9개가 이 사고(나머지 6개는 5~6월 것)

## 2차 완주 후 전수 점검 (2026-09-09)

캐시 9,832건 중 미완결 5건, 본문 없음 3건. 조각 10편은 전부 복구(`Walcott 1916` 694/694 등). 미완결 5건의 서버측 페이지 오류(`/ocr/{job_id}`의 page.error):

- 4건은 인프라 일시 장애 — `404`/`502`/`500` from `http://nginx/v1/chat/completions`. 재실행하면 복구된다
- 1건은 문서 문제 — `Hansen`(5/6): `render failed: code=7: cmsOpenProfileFromMem failed`. 색상 프로파일이 깨진 쪽이라 다시 돌려도 같다. 영구 미완
- 본문 없음 3건 중 2건은 고아 캐시(`Kutscher2008`, `Pillet1972…PLT` — PaperFile 행 없음, 지운 논문의 잔해, 무해)

라이브 DB(08-28): Paper 9,895 / `references_checked` 9,765(98.7%) / `Reference` 511,338행(held 매칭 79,736) / `CitedWork` 264,169.

## 서버 몫 따라가기 (같은 시기, `e7aa04f` 외)

ocrserver는 이 PC 혼자 쓰지 않는다. wrapper 0.2.4부터 클라이언트별로 용량을 나눠 준다.

- **`?client_id=`를 붙여 물어야 한다** — 서버는 "페이지가 처리 중이거나 대기 중인 client_id"만 활성으로 세므로 제출 전 클라이언트는 목록에 없다.
  그냥 물으면 12(서버 전체), 내 id를 주면 6(내 몫). `wrapper_get_stats()`가 기본으로 자기 client_id를 붙인다(전체는 `for_this_client=False`)
- 배치 도구는 서버 답과 `concurrency // (others+1)` 중 **작은 쪽** — client_id를 모르는 옛 wrapper는 조용히 서버 전체를 답한다.
  `others`는 `GET /ocr`의 job별 `client_id`에서 내 것을 빼고 센다
- **concurrency의 단위는 페이지다**(작업 단위는 PDF 한 편). "동시 논문 수"로 조절하면 중앙값 13쪽 × 12편 = 150쪽을 12쪽짜리 서버에 밀어 넣는다(실제로 다른 PC를 굶겼다)
- 그 페이지 수는 **채워 둘 하한**이다 — `inflight + waiting > share`를 유지해야 한 쪽이 끝난 순간 다음이 들어간다. 정확히 share에서 멈추면 논문 경계마다 슬롯이 빈다(실측 inflight 6→5→3).
  여유분은 share의 1.5배 — 논문 한 편의 시간 중 앞의 Zotero 다운로드와 뒤의 JSON 업로드 동안은 서버에서 논다. 스레드 풀도 share보다 넉넉해야 한다. 더 제출해도 다른 클라이언트 몫을 뺏지 않는다(admission이 클라이언트별)
- 누가 붙어 있는지는 `/api/services`의 `scheduler.per_client`

## 남긴 결정

재OCR로 본문이 새로 나왔으므로 **references를 다시 뽑을지**는 보류 — 511k행을 버리는 큰 결정이라 몇 편 비교 후 결정(HANDOFF "결정 대기").
