# 20260515_034 — Auto queue depth from /api/stats (mode-aware throughput)

## 컨텍스트

세션 18에서 wrapper 파이프라인의 `min_queued_pages`를 `ocr_min_queued_pages` pref(기본 6)로 박아두는 방식이었음. 그런데 서버 운영상 GPU 모드 두 가지가 있음:

- **`llm+ocr` 모드** (기본, `mode-llm.sh`): GPU 0=OCR, GPU 1=Qwen3 → OCR 백엔드 1개 → 적정 in-flight 6
- **`2ocr` 모드** (`mode-ocr.sh`): GPU 0+1 모두 OCR → OCR 백엔드 2개 → 적정 in-flight 12

`llm+ocr`에서 12로 잡으면 큐가 너무 쌓이고, `2ocr`에서 6으로 잡으면 12-slot 백엔드의 절반이 놀게 됨. 모드 전환 시 사용자가 매번 pref를 손으로 바꿔야 하는 게 불편.

## 서버 측 변경 (사용자가 먼저 처리)

세션 18 종료 시점에 client_id 헤더 제안 → 그 다음 사용자가 서버에 capacity 노출 추가:

**`GET /api/stats`** (`WRAPPER_API.md` §api/stats):
```json
{
  "counts": {"total": 143, "queued": 0, "processing": 2, ...},
  "ocr_backends_alive": 1,
  "ocr_backends_total": 2,
  "recommended_concurrency": 6,
  "mode": "llm+ocr",
  "uptime_s": 14,
  "concurrency": 6,
  "vllm_url": "http://nginx:80"
}
```

- `recommended_concurrency = alive_backends × OCR_PER_BACKEND_CONCURRENCY` — 모드 자동 반영 (2ocr=12, llm+ocr=6)
- `mode` 값: `2ocr` / `llm+ocr` / `1ocr` / `llm` / `down`
- 5초 캐시 (probe 부담 최소화)

`GET /api/services`는 백엔드별 상세 헬스 (per_backend `chandra-a`/`chandra-b` 개별 상태).

## 클라이언트 변경

### `papermeister/ocr.py::wrapper_get_stats()`

```python
def wrapper_get_stats() -> dict:
    """Fetch /api/stats — counts + OCR backend capacity / mode.
    Returns {} on failure."""
    _ensure_config()
    try:
        resp = requests.get(f'{_WRAPPER_URL}/api/stats', timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning('wrapper_get_stats failed: %s', exc)
        return {}
```

서버 5초 캐시라 매 호출 부담 없음.

### `process_window.run()` — 큐 깊이 자동 결정

```python
configured = get_pref('ocr_min_queued_pages', None)  # 기본을 None으로 (auto)
if configured is not None:
    min_queued = max(1, int(configured))
    self.progress.emit(f'Queue depth target: {min_queued} pages (pref override)')
else:
    stats = wrapper_get_stats()
    rec = int(stats.get('recommended_concurrency') or 0)
    if rec > 0:
        min_queued = rec
        mode = stats.get('mode', '?')
        alive = stats.get('ocr_backends_alive', '?')
        total = stats.get('ocr_backends_total', '?')
        self.progress.emit(
            f'Queue depth target: {min_queued} pages '
            f'(mode={mode}, OCR backends {alive}/{total})'
        )
    else:
        min_queued = 6
        self.progress.emit(
            f'Queue depth target: {min_queued} pages (stats unavailable, default)'
        )
```

### Pref semantics 변경 (호환 유지)

| `ocr_min_queued_pages` pref | 동작 |
|---|---|
| 미설정 (default = None) | **auto** — 서버 `recommended_concurrency` 따라감 |
| 명시적 숫자 (e.g. 8) | override — 그 값 사용 (`max(1, int(...))`) |

기존에 `preferences.json`에 6이 박혀있는 사용자는 그대로 6 유지 (의도된 override로 해석). 그게 디폴트가 아니었던 게 핵심.

## 동작 시나리오

**시작 시 status bar** (세 가지):

```
Queue depth target: 12 pages (mode=2ocr, OCR backends 2/2)
Queue depth target: 6 pages (mode=llm+ocr, OCR backends 1/2)
Queue depth target: 6 pages (pref override)
Queue depth target: 6 pages (stats unavailable, default)
```

이후 seed loop + refill loop 모두 이 값 기준으로 동작.

## 결정사항

### One-shot vs 주기적 재조회

처음엔 매 refill iteration마다 stats 재조회를 고려했음 — 서버 5초 캐시라 부담 없고 mode 전환 mid-batch 대응 가능. 하지만 두 가지 이유로 one-shot 선택:

1. 모드 전환은 사용자가 의도적으로 하는 행위 (`mode-llm.sh`/`mode-ocr.sh` 실행). mid-batch 시점에 일어날 일은 거의 없음
2. 큐 깊이가 mid-run에 바뀌면 비교 가능한 처리량 측정이 흔들림

필요해지면 나중에 주기적 재조회로 바꿈. 비용은 거의 0.

### `ocr_backends_alive == 0` 케이스

현재 코드는 fallback 6 페이지로 진행. `ensure_workers_ready()`가 진입 직전에 이미 health 체크해서 통과했으니, stats 호출 시점에 alive=0인 케이스는 race window일 가능성. 처음 submit에서 자연스럽게 실패하면 사용자에게 표시됨. 별도 가드 안 둠.

## 파일

```
papermeister/ocr.py                — wrapper_get_stats() 신설
papermeister/ui/process_window.py  — run()의 min_queued_pages 결정 로직 교체
docs/WRAPPER_API.md, docs/ENDPOINTS.md — /api/stats, /api/services 명세 (서버 측 작업 결과 반영)
```

## 미정

- **mode 라벨을 status bar에 영구 표시**할지 — 지금은 Process 시작 시 한 번만 출력. 항상 표시해두면 사용자가 서버 상태 한눈에 보기 좋지만, 화면 공간 차지. 다음 세션에서 결정
- **주기적 재조회**: mode 전환 mid-batch 시나리오. 한 사이클이라도 모드 바꿔서 돌리는 일 생기면 추가
- **`/api/services`의 백엔드별 alive 정보** 활용: 한쪽 백엔드만 죽었을 때(`mode=1ocr`) 별도 메시지 등. 지금은 그냥 `recommended_concurrency`만 사용
