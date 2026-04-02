# CLI 버그 수정 및 다중 컬렉션 선택 지원

**날짜:** 2026-04-02
**유형:** 버그 수정 + 기능 추가

## 변경 사항

### 1. 병렬 OCR 진행 번호 버그 수정

**문제:** 병렬 OCR 처리 시 여러 파일이 모두 `[1/39]`로 표시됨.

**원인:** `process_one()`에서 `idx`를 `done + failed + 1`로 계산했는데, 병렬 실행 시 여러 스레드가 완료 전에 시작되므로 모두 같은 번호를 받음.

**수정:** `started` 카운터를 추가하여 각 스레드 시작 시 원자적으로 증가시킴.

```python
# Before
counter = {'done': 0, 'failed': 0}
def process_one(pf):
    with counter_lock:
        idx = counter['done'] + counter['failed'] + 1

# After
counter = {'started': 0, 'done': 0, 'failed': 0}
def process_one(pf):
    with counter_lock:
        counter['started'] += 1
        idx = counter['started']
```

### 2. 인터랙티브 모드 다중 컬렉션 선택

**변경:** `<number>`, `f <number>`, `p <number>` 커맨드에서 다중 선택 지원.

- 콤마 구분: `1,3,7`
- 범위: `1-5`
- 혼합: `1-3,7,10-12`

**구현:** `_parse_indices(text, max_idx)` 헬퍼 함수 추가. 선택 문자열을 파싱하여 0-based 인덱스 리스트 반환.

## 수정 파일

- `cli.py` — `_run_process()`, `_parse_indices()`, `cmd_interactive()`
