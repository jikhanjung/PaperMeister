# 075 — Qwen 5xx(엔진 재시작)에 짧은 재시도 추가

> 구현 기록 (2026-07-27). 계기: references 대량 추출 중 사용자가 보고한 502 반복

## 관측된 로그

```
Qwen 500: {"error":{"message":"EngineCore encountered an issue. See stack trace (above) ...
Qwen 502: {"detail":"upstream: All connection attempts failed"}
Qwen 502: {"detail":"upstream: All connection attempts failed"}
Qwen attempt 1/1 failed: HTTPConnectionPool(...:8080): Read timed out. (read timeout=240)
```
이 3~4줄이 계속 반복.

## 읽는 법 — 502는 증상, 500이 사건

- `EngineCore encountered an issue` = **vLLM v1의 엔진 워커 프로세스가 죽음**
- 뒤따르는 502 `upstream: All connection attempts failed` = 앞단 프록시(wrapper :8080)는
  살아서 응답하는데 **뒤의 vLLM에 TCP 연결 자체가 안 됨**. 엔진이 죽어 포트를 안 열고 있어서
- `500 → 502 → 502` 가 반복 = **죽고 → 재시작하고 → 요청 하나 받고 또 죽는 크래시 루프**.
  3개씩 묶이는 주기는 `ServerGuard`의 3연속 실패 → pause → 60초 폴링 → resume 과 일치

즉 원인은 서버 측(GPU/엔진). 유력 후보는 CUDA OOM — `llm+ocr` 모드에서 OCR과 GPU를
나눠 쓰는 데다 references 배치가 이 파이프라인에서 가장 긴 컨텍스트 요청(MAX_CHARS 입력,
max_tokens 최대 8192)이다. **확정은 서버 vLLM 로그의 스택 트레이스에서** 해야 한다.

부수 발견: 로그의 `read timeout=240`은 옛 값이다. `f8c33b7`(7/24)에서 360초 + pref로
올렸으므로 **실행 중인 앱이 7/24 이전 코드**라는 뜻 — 재시작 필요.

## 클라이언트 쪽 빈틈

`_call_qwen`은 `Timeout`/`ConnectionError`만 잡아 재시도했다. 502/500은 **정상 HTTP
응답**이라 `raise_for_status()` → `HTTPError`로 나가고, references 배치 루프의
`except (Timeout, ConnectionError)`에도 안 걸린다. 결과:

| 실패 | 처리 |
|------|------|
| 타임아웃 | 배치 축소 재시도 → 최악에도 PARTIAL로 부분 보존 |
| **5xx** | **논문 하나가 통째로 실패** → 3연속이면 pause |

엔진 재시작은 수십 초짜리 일시적 상태이고 요청은 멱등이라, 그냥 기다렸다 다시 쏘면
대부분 통과할 것들이었다.

## 수정

`_call_qwen`에 **5xx 전용 재시도 예산**(`server_retries=2`, backoff 5s → 15s)을 추가.
기존 `retries`(타임아웃용)와 **분리**했다. 두 실패가 정반대의 대응을 원하기 때문:

- **타임아웃** = 배치가 너무 큼 → 호출자가 **줄여서** 재시도해야 함
- **5xx** = 엔진이 재시작 중 → **같은 배치**를 그대로 **기다렸다** 다시 보내면 됨

한 예산으로 묶었으면 refs 경로(`retries=0`, 축소 재시도를 배치 루프가 직접 함)가 5xx
재시도를 하나도 못 받았을 것이다. 4xx는 재시도하지 않는다 — 우리 요청이 잘못된 것이라
저절로 낫지 않는다.

## 왜 backoff를 짧게 두었나 (설계 판단)

**진짜로 죽은 서버는 여기서 흡수하면 안 된다.** `main_window._on_refs_extracted`는
`complete=True`일 때만 `record_ok()`를 부르고, 예외는 `_on_refs_failed` → `record_fail()`로
간다. 즉 5xx를 우아한 부분 성공(`complete=False` + record_ok)으로 바꿔버리면 스트릭이
리셋되어 **ServerGuard가 영영 pause하지 않고**, 엔진이 죽은 채로 남은 5,800편을 헛도는
최악의 시나리오가 된다.

그래서 역할을 나눴다 — **짧은 blip은 `_call_qwen`이 흡수, 지속적 장애는 그대로 raise해서
ServerGuard가 pause + 60초 폴링 + 자동 복구**를 담당. 총 추가 지연은 호출당 최대 20초.

## 검증

`tests/test_qwen_retry.py` 6케이스: 502 blip 통과 / 500 EngineCore도 transient 취급 /
**지속 5xx는 여전히 raise**(guard가 pause할 수 있게) / 4xx는 재시도 없이 즉시 실패 /
`retries=0`이어도 5xx 예산은 살아있음 / 기존 타임아웃 재시도 횟수 불변.

`ruff` clean, `mypy`(CI 게이트 3모듈) clean, 전체 **87 passed**.
