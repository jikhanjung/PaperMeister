# 088 — 502가 났으면 났다고 보여준다

> 구현 기록 (2026-07-29). 계기: 사용자 요청 — "502 에러가 나면 났다는 건 보여주면 좋겠어."

## 문제

083에서 502의 정체를 "컨테이너 재기동"으로 확정하고 **재시도 대신 복구를 기다리는** 쪽으로
바꿨다. 그 판단은 그대로 옳다 — 논문 하나에서 이미 파싱한 배치를 지켜준다.

문제는 **그 기다림이 화면에 하나도 안 나온다**는 것이었다. 502가 나면

- `_wait_for_server`가 최대 900초(기본값) 동안 15초 간격으로 헬스체크를 돈다
- 그 동안 References 창은 `Parsing: <title>` 그대로다. 논문이 안 끝났으니 `record()`도 안 불리고,
  배치는 멈춘 게 아니니 `mark_paused()`도 안 불린다
- 즉 **"멈춘 것"과 "기다리는 것"이 화면상 완전히 동일하다.** 최대 15분간

로그(`logs/biblio_YYYYMMDD.log`)에는 `Qwen 502:` 와 `waiting for the server to come back`이
남는다. 하지만 무인 배치를 지켜보는 사람에게 "로그를 열어보라"는 답은 답이 아니다.
ServerGuard의 pause는 **논문 사이**에서만 걸린다 — 논문 **안에서** 나는 502는 거기 안 걸린다.

## 한 일

`extract_references_llm`에 진행률(`on_progress`)과 같은 결의 통보 채널 `on_notice(kind, message)`를
추가했다. `kind`는 세 가지뿐이다.

| kind | 언제 | 화면 |
|------|------|------|
| `server_down` | 게이트웨이가 5xx로 답함 (502/503/504) | 라벨 → "LLM server down — waiting…", 로그 빨강 |
| `server_up` | 헬스체크가 다시 200 | 라벨 → 원래 `Parsing: <title>`, 로그 파랑 |
| `server_gone` | 대기 상한 소진 → 이 논문 포기 | 라벨 복구 + 로그 빨강 (뒤이어 실패가 `record()`된다) |

셋 다 **논문을 끝내지 않는** 사건이라 반환값으로는 전달할 수 없다. 반환값은 논문이 끝나야
돌아오고, 이 사건들은 그 전에 알려야 의미가 있다.

배선은 진행률과 같은 길을 탄다: `BackgroundTask.notice = pyqtSignal(str, str)` → 워커 스레드에서
emit → 큐드 커넥션으로 메인 스레드 → `_on_refs_notice` → `ReferencesWindow` + status bar.
위젯을 워커 스레드에서 직접 건드리지 않기 위한 기존 규약 그대로다.

### 라벨 복구가 핵심

`mark_paused`/`mark_resumed`(배치 단위)와 달리 이 대기는 **논문 안에서** 끝난다. 복구 후에
`set_current()`가 다시 불릴 일이 없으므로, 창이 스스로 직전 텍스트(`_current_text`)를 기억했다가
되돌린다. 안 그러면 복구된 뒤에도 남은 파싱 내내 "server down" 배너가 걸려 있다.
그리고 이 대기 중에는 **진행바를 건드리지 않는다** — 논문은 아직 안 끝났고, 여기서 세면 실제로
끝날 때 이중으로 센다.

## 덤으로 고친 것

`extract_references_llm`의 `on_progress`는 있었고 `ReferencesWindow.set_item_progress`도 있었고
`BackgroundTask.progress` → `_on_refs_item_progress` 연결도 있었는데, **정작 desktop이
`on_progress=`를 넘기지 않았다.** 그래서 논문 내 진행바(두 번째 바)는 한 번도 뜬 적이 없다.
"긴 논문과 멈춘 논문을 구분한다"는 그 바의 존재 이유가 지금 문제와 정확히 같은 것이라 같이 물렸다.

## 검증

- `tests/test_refs_partial_reporting.py` — 502가 `server_down`+`server_up` 순서로 통보되는지,
  메시지에 상태 코드 `502`가 실제로 들어 있는지(“서버 오류”가 아니라). `_wait_for_server`가
  복구/포기 양쪽을 스스로 보고하는지
- `tests/test_references_window.py` (신규, `ui` 마커) — 라벨이 복구되는지, 대기가 진행바를
  전진시키지 않는지
- 전체 151 passed / ruff / mypy clean
- 기존 502 스텁 2개는 `_wait_for_server` 시그니처가 늘어 `notify=None`을 받도록 수정

## 남은 것

- OCR·biblio 경로에는 손대지 않았다. biblio는 502가 `HTTPError`로 그대로 올라가
  `task.failed` → 창에 `failed: …`로 이미 **보인다**. 조용한 건 references의 인-페이퍼 대기뿐이었다
- 서버 측 근본 원인(OOM 유력)은 여전히 미확정 — 이건 가시성 작업이지 원인 규명이 아니다
