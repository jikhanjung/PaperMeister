# P03: Parallel OCR Processing 계획

**작성일:** 2026-03-31
**상태:** 계획 (구현 전)

---

## 목표

RunPod health check로 가용 worker 수를 파악하고, 그만큼 OCR 작업을 병렬 처리하여 속도 향상.

## 현재 문제

- OCR 처리가 완전 순차적 — 한 번에 하나의 PDF만 처리
- RunPod에 idle worker가 여러 개 있어도 하나만 사용
- 82개 파일 처리 시 불필요하게 느림

## 핵심 결정 사항

| 항목 | 결정 | 이유 |
|------|------|------|
| 병렬화 단위 | 파일(PDF) 수준 | 가장 큰 효과, 구현 단순 |
| 동시 처리 수 | RunPod idle worker 수 기반 | health check로 동적 결정 |
| 병렬화 방식 | `ThreadPoolExecutor` | Python 표준, signal emit 호환 |
| 최대 동시 | 10 | 과부하 방지 상한선 |

## 설계

### 동시성 결정 로직
```
health = check_health()
idle = workers.idle
max_concurrent = max(1, min(idle, 10))
```

### ProcessWorker 변경
기존: `for pf in files: process_paper_file(pf)` (순차)

변경: `ThreadPoolExecutor(max_workers=N)`으로 N개 파일 동시 처리

### Thread Safety
- DB 쓰기: `db.atomic()` + SQLite WAL 모드 → 안전
- Qt signal emit: cross-thread safe
- Zotero 다운로드: 파일명이 `{attachment_key}.pdf`로 고유 → 충돌 없음
- `_ensure_config()`: 한 번 설정 후 read-only → safe

## 변경 파일

### 1. `papermeister/ocr.py`
- `get_worker_count()` 함수 추가: health → idle worker 수 반환

### 2. `papermeister/ui/process_window.py`
- `ProcessWorker`: ThreadPoolExecutor 기반 병렬 처리
- `ProcessWindow`: 시작 시 worker 상태 로그 표시

## 로그 출력 예시
```
[00:15:30] === Starting: 82 files ===
[00:15:30] RunPod workers: 3 idle, 0 running → parallel: 3
[00:15:30] [1/82] Downloading PDF from Zotero...
[00:15:30] [2/82] Downloading PDF from Zotero...
[00:15:30] [3/82] Downloading PDF from Zotero...
[00:15:33] [1/82] Running OCR...
[00:15:35]   Done: paper_a.pdf
[00:15:35] [4/82] Downloading PDF from Zotero...
```

## 검증 방법
1. Process Pending 실행 → 로그에 worker 수와 병렬 처리 현황 확인
2. 여러 파일이 동시에 처리되는지 타임스탬프로 확인
3. 모든 파일 정상 처리/실패 처리 확인
