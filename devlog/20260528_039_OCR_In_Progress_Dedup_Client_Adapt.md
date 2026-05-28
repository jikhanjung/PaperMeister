# 20260528_039 — 서버 in-progress dedup 도입에 맞춰 client 적응

## 컨텍스트

[devlog 037](./20260528_037_Lazy_PDF_Render_Tab_Build_OCR_Submit_Hint.md) 의 OCR submit `total_pages` hint 작업 직후 관측: 직전 세션이 burst-submit해놓은 11편이 서버에서 모두 `failed`로 표시되어 있고, Stewart 2011 (1773p) 한 편만 살아서 1379/1773 진행 중. 사용자 정리 — "서버에 남아있던 job들은 클라이언트 종료 시 housekeeping으로 force-fail 처리한 것, 진짜 OCR 실패 아님". 이어서 사용자가 알려준 서버 측 정책 보강:

> 기존 서버 dedup은 `WHERE file_hash=? AND client_id IS ? AND status='done'` 한 줄. 즉 **완료된 job만** dedup 대상 → 처리 중인 같은 파일은 매번 새 job 생성. Stewart 사고가 정확히 그 case로, mid-flight 잡이 dedup 안 되어 한 PDF에 더블 잡이 만들어졌음.

서버 patch:
- `db_find_done_by_hash` → `db_find_existing_by_hash` 로 개명, `status IN ('done','processing','queued')` 로 확장.
- ORDER `(status='done') DESC, submitted_at DESC` 로 done 우선.
- 응답에 `in_progress: bool` 추가 — `cached=true` + `in_progress=true` 면 "이미 진행 중이니 polling 이어가라".
- `failed`, `done_with_errors` 는 여전히 dedup 안 함 (재시도 가능해야 함).

이로써 클라이언트가 mid-run 종료 후 재시작해서 같은 PDF를 다시 보내면 새 job을 만드는 대신 기존 in-flight job을 그대로 polling. 더블 OCR 사라짐.

## 변경 사항

`papermeister/ocr.py::wrapper_submit`:

반환 시그니처 확장 `(job_id, total_pages)` → `(job_id, total_pages, in_progress)`. 응답에 `in_progress` 필드 없으면 `.get(...)` → `None` → `bool()` → `False` 로 기본값 잡혀서 **older server backwards-compat**. 클라이언트가 서버보다 먼저 배포되어도 작동.

기존 cached 로그 라인 분기:
```python
if cached:
    state = 'in-progress' if in_progress else 'completed'
    logger.info('Wrapper returned cached %s job %s for %s', ...)
```

`_wrapper_ocr_pdf` (단일 파일 헬퍼):
- `job_id, total_pages, _in_progress = wrapper_submit(pdf_path)` — discard. 단발성 OCR 경로라 polling 이어가는 거 외에는 처리할 게 없음.

`papermeister/ui/process_window.py::_submit_next`:

`in_progress=True` 케이스에 사용자에게 보이는 progress 메시지 분기:
```python
if in_progress:
    self.progress.emit(
        f'{prefix} {name} → resumed in-flight job {job_id[:8]} ({tp} pages)'
    )
else:
    self.progress.emit(f'{prefix} {name} → queued ({tp} pages)')
```

`job_id[:8]` 단축 — 서버 admin UI 가 8-char prefix 로 잡을 식별하니 일관성. 풀 job_id 는 `logger.info` 로 파일 로그에 남음.

## 폴리시 결정

**왜 signature를 확장 (반환 튜플 3-원소화)?**
대안:
- (a) `wrapper_submit` 내부에서 로깅만 하고 propagate 안 함 — 작업 visible 안 됨. ProcessWindow 로그가 진단의 1차 surface 라 보이지 않으면 "왜 78%부터 시작하지?" 같은 혼란 발생 가능.
- (b) dict 반환 — type 안전성 좋지만 콜러 둘 다 같은 리포 안이라 메리트 적음.
- (c) namedtuple — 가독성 좋지만 콜러 둘이라 과한 추상화.

3-tuple + `_in_progress` discard 패턴이 변경 최소. 콜러 2개 (`process_window._submit_next`, `_wrapper_ocr_pdf`) 모두 같은 리포라 grep 으로 한 번에 확인됨.

**왜 ProcessWindow 메시지에 노출?**
"resumed" 정보가 OCR 로그에 안 보이면 디버깅 거의 불가. 같은 install 의 cross-restart 시나리오(Stewart 1773p 가 78% 에서 이어짐) + 두 PaperMeister 인스턴스가 같은 파일 동시 제출 시나리오 모두 이 메시지 한 줄이 "왜 진행 % 가 0이 아닌가" 의 답이 됨.

**race condition 우려?**
같은 hash 를 두 인스턴스(A, B) 가 거의 동시에 제출:
- A: 새 job 생성, B: A 의 job id 받음 (`cached=true, in_progress=true`)
- 둘 다 같은 job_id 로 polling
- terminal `done` 도달 시 둘 다 `wrapper_collect` 호출 → OCR JSON 두 번 save
- `_save_ocr_json` 은 atomic write (tmp → rename) 이고 내용 동일 → 결과적으로 무해
- 둘 다 `PaperFile.status='processed'` 로 마킹 — 동일 paper_file_id 라면 last-write-wins, 다른 paper_file_id (각자 다른 PaperFile 이 같은 hash) 라면 둘 다 정상

별도 lock/coordination 안 함. duplicate work 비용은 polling 두 번 + JSON 한 번 더 쓰기 정도라 무시 가능.

## 영향 범위

- **즉시**: 사용자가 서버 job 테이블 비웠다고 알려줘서 (`이미 영향 없어`) 140편 batch 는 전부 fresh submit 으로 진행. 새 코드의 `in_progress=True` 경로는 발동 안 함.
- **다음 mid-run 중단 시점부터 의미 생김**: 사용자가 PaperMeister 종료 후 재시작 → 140편 중 처리 중이던 PDF 들이 `in_progress=true` 로 resume. OCR 로그에서 `resumed in-flight job XXXXXXXX (N pages)` 라인 확인 가능.
- **두 PaperMeister 인스턴스 (예: NAS 와 워크스테이션)**: 같은 Zotero 컬렉션을 두 곳에서 Process Folder 돌리면 서버가 dedup 해줘서 OCR 중복 안 함. 다만 client_id 가 다르면 dedup 안 됨 — 서버는 `(file_hash, client_id)` 페어로 매칭하므로 같은 client_id 를 두 머신이 공유하지 않는 한.

## 미해결 / 다음

- 서버 측에 `in_progress` 필드가 실제로 deploy 되어 도착하는지 라이브 확인 (`failed` reset 직후 batch 가 한 번 끝나면 자연스럽게 검증되지는 않음 — fresh submit 만이라 `in_progress` 경로 미발동. 다음 의도적 mid-run restart 가 첫 검증 기회).
- `client_id` 가 두 머신 간 같아야 하는 use-case 가 생기면 export/import 메커니즘 필요. 현재는 install 별 ID 라 cross-machine dedup 안 됨 — 의도적 설계 (각 머신을 독립으로 보기). 사용자가 같은 라이브러리를 NAS+워크스테이션에서 병렬 처리하려면 `preferences.json` 의 `client_id` 를 수동 동기화 가능.
- `done_with_errors` 잡은 dedup 대상 아님 → 재제출 시 새 OCR. 부분 성공한 page set 을 살릴 수 있다면 향후 best-effort merge 도 가능하지만, 지금은 단순화 우선.
