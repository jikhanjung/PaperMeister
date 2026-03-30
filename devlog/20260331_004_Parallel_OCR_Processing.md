# 004: Parallel OCR Processing 구현

**작성일:** 2026-03-31
**계획 문서:** `20260331_P03_Parallel_OCR_Processing.md`

---

## 완료 작업

### `papermeister/ocr.py`
- `get_worker_status()` 함수 추가
  - RunPod `/health` API → `{idle, running, throttled, ready}` 반환
  - 병렬 처리 수 결정에 사용

### `papermeister/ui/process_window.py`
- `ProcessWorker` 병렬화 구현
  - 시작 시 `ensure_workers_ready()` → `get_worker_status()`로 idle worker 수 확인
  - `concurrent.futures.ThreadPoolExecutor(max_workers=idle)` 사용
  - `_process_one(pf_id)` — 개별 파일 처리 (thread pool thread에서 실행)
  - `_next_index()` — thread-safe 카운터 (Lock 사용)
  - 로그에 `[idx/total]` 접두사로 어떤 파일의 상태인지 구분
  - 시작 시 `"RunPod workers: N idle, M running → parallel: N"` 로그 출력
  - 동시 처리 수: `max(1, min(idle, 10))`

## Thread Safety
- DB: `db.atomic()` + SQLite WAL 모드
- Qt signal: cross-thread emit 지원
- Zotero 다운로드: `{attachment_key}.pdf`로 파일명 고유
- `_ensure_config()`: 초기화 후 read-only
- 카운터: `threading.Lock` 사용
