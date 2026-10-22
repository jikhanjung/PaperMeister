# 115 — P16 도판 무인 운영: 1차 완주까지 (2026-09-23 ~ 10-21)

[113](./20260922_113_Link_Reading_Set.md) 뒤 한 달의 기록. 그동안 HANDOFF에만 쌓여 있던 운영 메모·사고·고친 것을 2026-10-22 정리 때 옮겼다.
설계와 교훈은 [`docs/figure_pipeline_guide.md`](../docs/figure_pipeline_guide.md)(특히 §9), 날짜·시간별 처리량은
[`docs/figure_runner_processing_log.md`](../docs/figure_runner_processing_log.md), 릴리스별 변경은 `CHANGELOG.md` [0.2.0]~[0.2.3].

## 결과 (2026-10-21 05:05)

러너가 **551개 배치 전부**를 물었다(마지막은 `한국`과 그 하위). 05:20 마지막 수거 뒤 05:24부터 틱마다 `nothing to do; queue 0 item(s)`.
최종(DB, ≤200쪽): 파일 **9,554/9,554**, 도판 **99,041장**, 캡션 **88,762**(89.6%) · 못 찾음 8,334 · 미질문 22(보낸 적 없는 잔여 행) ·
설계상 안 묻는 행 1,774, 분할 **35,181**.

- ~111k로 잡았던 추정은 과대(89%) — 10-07 뒤 파일의 그림 블록 수는 맞았지만(11.5만, 추정 11.2만) 도판 하나가 묶는 블록이 1.21 → 1.38개로 늘어
  환산비가 0.84가 아니라 0.69였다. 블록은 모두 도판 안(109,364)이거나 일부러 버린 것(작은 그림 4,391 · 머리글 등 1,203)
- 진행률을 셀 때 **미질문**에서 `assembly='page'` 자리표시 행과 `captioned_plate`(link가 일부러 안 묻는다, `link_targets`)는 빼야 한다 — ~1,000행이 늘 "안 물음"으로 남는다
- 범위 밖: **200쪽 초과 ~379파일**(초록집·합본, 블록 73,225 ≈ 도판 6만) — 결정 대기

## 그 전에 정한 것 (HANDOFF에만 있던 결정)

- **OCR 본문이 OpenAI로 간다(2026-09-17, 사용자 결정)** — link·detect는 논문의 OCR 텍스트 전체가 ocrserver 작업 폴더에 올라가고, Astra가 여는 만큼 OpenAI로 간다.
  PDF를 보내 도판을 찾게 하는 것과 정보량이 같으므로 받아들인다. PDF 파일 자체는 가지 않는다(detect 쪽 이미지·panels 크롭만).
  워커가 로그인한 ChatGPT 계정의 **"Improve the model for everyone" 토글을 껐다**(09-17) — 그 전에 나간 것은 664 + 파일럿 앞 몇 편
- 호출 간격 `FIGURES_MIN_INTERVAL=120`(09-18, D8의 300에서 하향). 그 뒤 워커 풀이 생기며 간격은 서버가 조절한다(아래 표)
- 1191 Barrande: p.4와 p.10의 플레이트가 같은 설명(p.7–8)을 받았다 — p.4가 Pl. 1의 부분 교정쇄인지 사람이 볼 것(09-21, 미확인)

## 운영 형태

- 09-23 오래 사는 러너(`figure_queue.py --days N --execute`)로 시작 → **10-07 20:29 5분 틱으로 전환**(fsis P47 `pipeline_tick.py`에서 가져옴):
  작업 스케줄러 `PaperMeister Figure Queue`가 `figure_queue.py --tick --execute`(pythonw, 한 패스 후 종료), OS 파일 잠금, 틱 예산 240초,
  `<data>/figure_queue.stop` = 일시정지. 러너가 죽어 몇 시간 멈추는 일이 구조적으로 없어졌다. 첫 틱이 러너가 멈춘 자리(paper 6339 다음)부터 이어감
- Zotero 컬렉션을 트리 순서로 배치 하나씩, 서버 큐를 ~120항목 근처로. 200쪽 초과 제외. SQLite `busy_timeout=15s`로 앱과 겹쳐도 바로 실패하지 않음
- `--status`(10-08)는 완료 배치 한 줄 요약 + 진행 중 배치(link 진행/대기/분할 due) + 다음 3개

## 사고와 고친 것

- **09-23 첫 무인 실행이 4시간 만에 죽음** — `figure_queue.py`가 `install_system_trust()`를 안 불러, 첫 수거 뒤 Zotero sibling 푸시에서 기관망 TLS
  `CERTIFICATE_VERIFY_FAILED` → 미처리 예외(stderr 미리다이렉트라 로그에도 없음). 고침: 트러스트 설치 + 패스 단위 예외 격리, `write_to_cache`는 푸시 실패를 경고만
- **09-25 휴일 러너가 이틀간 거의 멈춤** — 서버 큐에서 기다리는 패널 2장이 DB에선 계속 "due"라 5분마다 재제출 → 50잡이 큐를 채워 "가득 참".
  panels 후보가 러너가 link한 논문뿐이라 파일럿 재link 결과(3,106장)의 panels는 아예 안 나감. 고침(`1e622d7`): 서버에 이미 있는 키는 재제출 안 함,
  panels 후보 = 캡션 있고 미분할인 모든 파일, settled 잡 기억, 클라이언트 `cancel`
- **09-30 실패한 link 항목을 같은 크기로 재제출**(서버 지적, stall 10건) — `figure_link.item_limits()`: 시도 횟수만큼 무게·도판 수 상한을 절반씩(80/30 → 40/15 → 20/7), 항목당 30장 상한.
  소진 행은 `link_figures.py --retry-errors`로 작은 항목으로. 같은 날 앱 Process Figures가 러너와 겹쳐도 안전(서버의 열린 잡에 같은 키가 있으면 기다림),
  워커 풀 응답 모양(`workers` 리스트, 죽은 워커 `alive:false`)을 `worker_summary()`가 요약
- **10-04 paper 2388 해시 불일치** — DB 해시가 Zotero의 PDF와 달라 서버가 "다른 판본"으로 거부. OCR은 지금 파일을 읽은 것(쪽별 텍스트 일치 0.95) →
  `scripts/rehash_file.py`(해시·도판 행·키·캐시 이름·사이블링 경로/Zotero 파일명) 새로 만듦. OCR이 파일과 안 맞으면 거부
- **10-06 서버 잡 목록 100개 창** — `/figures/jobs`가 기본 100개만 돌려줘 앞선 잡이 목록 밖으로 밀림 → 답 미수거 + 배치 조기 완료, 2,502장 미반영.
  고침: `limit=1000`(`abe736a`), 낸 잡 ID를 `state['open_jobs']`에 기억해 직접 조회(`TrackedClient`, `c0e038c`). 회수 잡 329개·캡션 2,163장.
  같은 날 3854(Craw 1999)는 OCR 상자 `x1=7080` 하나로 서버가 논문 전체를 400 → `ocr_layout._read_attrs`가 축마다 0..1000으로 자름
- **10-09 배치 경계에서 큐가 빔** — 다 넣고 캡션 답만 기다리는 배치가 다음 배치 link를 막아 작은 배치마다 큐가 0. 이제 그런 배치는 막지 않는다(가이드 §9-7).
  같은 날: 앞질러 나간 작은 배치의 link는 대개 이미 처리된 파일의 남은 재시도라 수율이 낮다 → 수거 줄에 `N figure(s) the reply gave no caption for`;
  `settled_jobs` 5,000개 자르기가 id 철자순이던 것 고침; 돌고 있는 큰 panels 잡의 끝난 도판을 다시 내던 것 고침(안 끝난 잡의 항목은 모두 대기로 셈)
- **10-09 Zotero 장애(503)로 도판 JSON 102건이 사이블링에 안 올라감** → 10-13 그 뒤 실패(502·500·S3 타임아웃·DNS)까지 해시 116개 → 118논문 123파일을
  `figure_share.py --export --paper-ids … --execute`로 재업로드(전부 `sibling updated`). 방법: `grep -oh 'not pushed to the Zotero sibling for [0-9a-f]*' logs/figure_queue*`
  → `paperfile.hash LIKE '<접두>%'`. (예외 없이 거부된 업로드는 10-22까지 로그에 안 남았다 — [116](./20261022_116_Library_Copy_Backup_And_Zotero_Cleanup.md))
- **10-10 `not_a_figure`는 한 번만 묻는다** — 서버 이력 35시간: 첫 답이 not_a_figure였던 244장을 다시 물어 캡션이 나온 건 1장. `explanation_not_found`는 31장 중 11장이 재시도로 찾아 3회 유지.
  이미 1~2회째인 1,134장은 손대지 않음(같은 파일이 뒤 컬렉션에 또 나올 때만 한 번 더 묻고 끝남)
- **10-14 끝난 panels 잡을 매 틱 다시 읽음**(`4c6eec8`) — 서버 600초 한도로 실패한 도판 하나(45467)는 digest가 없어 잡이 "안 읽힘"으로 남았고 39시간 동안 시도 477회 +
  Zotero 푸시 ~477회. 이제 panels 잡은 한 번 읽으면 settled. 45467의 시도를 1로 되돌림
- **10-20 수거 줄이 쌍둥이 복사를 안 셈**(`6c6b8c9`) — `propagate_link`의 반환값(같은 PDF를 가진 다른 항목에 복사한 캡션 수)을 버려 로그와 DB가 어긋나 보였다. 이제 `; N caption(s) copied to …`

## link 답 형식: segs (09-30 ~ 10-01)

ocrserver P03 제안(캡션 구간 형식, 출력 55–65%·시간 65–75%·stall 0). `figure_segs.py` 복원기가 지금 스키마로 되돌리므로 저장·검증은 그대로.
결정(09-30, 사용자): 라벨 없는 단일 그림은 **항목 0개**. 파일럿(79편 2,297장, 146항목, 실패 0, 항목당 평균 276 s): 라벨 1,477/1,514 동일, 진짜 손실 12장,
표본번호 95%, 캡션 유사도 0.94. 자기 번호 항목은 모델 판정이 범위 묶음 규칙과 87% 일치. 10-01 **기본 형식 segs**(`link-v1-8d37240149cd`, 옛 결과는 linked 유지)
+ 파일럿 답 DB 반영(2,285장 written, 사전 스냅숏 `<data>/tmp/before_segs_apply.db`). 휴리스틱 정리 스크립트는 만들지 않음.

## 서버 워커 수와 속도

처리량은 워커 수에 거의 비례했다(10-08 워커 2→4에서 시간당 수거가 정확히 2배). 실제 상한은 워커 수가 아니라 **Codex 사용량**이다 —
워커를 늘리면 같은 사용량을 더 빨리 쓸 뿐. 러너는 손댈 것이 없었다(상한 120은 워커 2 기준이었지만 그대로 둬도 됨).

| 시점 | 서버 상태 | 비고 |
|---|---|---|
| 09-30 | 워커 2(wrapper 0.3.7) | |
| 10-08 | 4 | 캡션 ~470장/h |
| 10-11 | 5(0.3.10) | 하루 캡션 ~5,700 |
| 10-12 | 8(리셋 쿠폰) | |
| 10-13 | 10 | 하루 파일 ~860 · 도판 ~12.6k |
| 10-14 14:38 | 1(사용량 리셋 전까지) | |
| 10-16 | `max_workers: 5` | |
| 10-17 ~ 10-20 | `max_workers: 1` + `min_interval_s` 150~3600 오르내림 | FIFO라 캡션·분할 레인이 한쪽씩 몇 시간 0건 — 러너 고장 아님 |
| 10-20 17시 | `max_workers: 10` | 완주까지 |

10-07에는 무사고 ~65일(12월 중순)로 추정했으나 워커 증설로 10-21에 끝났다.

## 같은 시기 앱 쪽 (09-22)

SourceNav `refresh()`가 펼침·선택을 보존, `QThread: Destroyed while thread … is still running`(숨은 탭 페이지의 렌더 스레드 누수 → `DetailPanel._dispose_tabs()`),
프레임리스 메인 창(`window_chrome.py`, `"native_title_bar": true`로 복귀). 릴리스 v0.2.0(09-22), v0.2.2(09-30), v0.2.3(10-07).

## 남긴 것

- 200쪽 초과 ~379파일 처리 여부
- panels 레인이 같은 PDF 형제를 해시로 합치지 않는다(link의 `propagate_link` 같은 처리 필요, 10-20 Kaseki/72-에서 쌍둥이 양쪽이 따로 받음)
- reading set 확장 방아쇠에 "얇은 답"(`plate_no_entries`·`caption_shared`·`entries_shrank`) 추가 여부
- 항목 설명에 산지·층준 포함(권고: 포함), 무게 상한 상향
- **이미 끝난 컬렉션에 새로 넣은 PDF는 러너가 안 잡는다** — 배치 파일 목록을 `files_cache`에 얼려 두고 `done_batches`로 건너뛰기 때문. 앱 우클릭 Process Figures로 처리하거나 그 키를 두 곳에서 지울 것
