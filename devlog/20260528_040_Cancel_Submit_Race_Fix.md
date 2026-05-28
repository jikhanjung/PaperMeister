# 20260528_040 — Cancel 직후 다음 파일이 submit되는 race fix

## 컨텍스트

[devlog 039](./20260528_039_OCR_In_Progress_Dedup_Client_Adapt.md) 적용 후 사용자가 라이브 batch 운영하며 발견. 처리 도중 Cancel을 눌렀는데 그 직후 다음 PDF가 한 편 더 submit되는 현상:

```
[21:20:40] [1/140] Stewart - 2011 ... OCR 50/1773 pages
[21:20:45] [1/140] Stewart - 2011 ... OCR 52/1773 pages
[21:20:50] [1/140] Stewart - 2011 ... OCR 57/1773 pages
[21:20:53] Cancelling — waiting for in-progress files to finish...
[21:20:55] [2/140] Space, time, form ... → submitting…
[21:20:55] [2/140] Space, time, form ... → queued (923 pages)
[21:20:55] === Cancelled: 0 processed, 0 failed ===
```

Cancel 시그널이 21:20:53에 들어왔는데 21:20:55에 새 PDF가 큐잉. 사용자 경험상 "Cancel 무시" 처럼 보임.

## 원인

`papermeister/ui/process_window.py::_run_wrapper_pipeline`의 메인 루프 구조:

```python
while True:
    if self._cancelled:          # ① top-of-loop check
        break

    if not in_flight:
        if submit_idx >= len(self.paper_file_ids):
            break
        # ② new-IDs seed (cancel 체크 없음)
        while submit_idx < ... and _queued_pages() < min_queued_pages:
            _submit_next()
        ...

    time.sleep(5)

    for job_info in in_flight:
        if self._cancelled:      # polling 단계는 cancel 체크 있음
            break
        ...

    in_flight = still_flying

    # ③ end-of-iter refill (cancel 체크 없음)
    while submit_idx < ... and _queued_pages() < min_queued_pages:
        _submit_next()
```

타임라인:
1. `time.sleep(5)` 진입 (21:20:50 직후)
2. 21:20:53 사용자 Cancel 클릭 → `self._cancelled = True`
3. sleep 끝, polling for-loop 진입. **첫 job_info 들어가기 전 `if self._cancelled: break`로 즉시 탈출** — Stewart polling 안 함
4. `in_flight = still_flying` 실행 (Stewart 여전히 들어있음, 직전 iteration에서 인플라이트 상태였으니)

   wait, 다시 봐야 함. polling for-loop이 첫 진입에서 break했으니 `still_flying`은 빈 list. 그러면 `in_flight = []` 됨. 다음 iteration에서 `if not in_flight` 가 참 → new-IDs seed 분기로 들어가서 ② submit. 이게 사용자가 본 거.

   아 잠깐, 그런데 사용자 로그는 같은 5초 sleep cycle 안에서 submit이 일어났음. 다시 시퀀스 재구성:

   - 21:20:50 polling iter 끝, refill ③ 실행 (이 시점 in_flight=[Stewart])
   - 21:20:50 time.sleep(5) 진입
   - 21:20:53 Cancel
   - 21:20:55 sleep 끝, polling for-loop 진입 → 첫 체크에서 break
   - 21:20:55 `still_flying`은 비어있음. `in_flight = []`.
   - 21:20:55 **③ refill 실행 (cancel 체크 없음)** → 다음 PDF submit
   - 21:20:55 while top으로 돌아가서 ① 체크 → break, Cancelled 메시지

그래서 사용자가 본 새 submit은 **end-of-iter refill (③)**의 결과. polling for-loop이 cancel 시 break한 부산물로 still_flying이 비어버렸고, 그래도 refill은 cancel 무시하고 다음 file 가져옴.

원래 polling break는 "남은 polling은 다음 iteration에서" 의도였을 텐데, `still_flying`에 처리 못 한 job들을 다시 넣어주지 않아서 in_flight가 비어버리는 버그도 있음. 다만 outer cancel 체크가 곧장 break하니 실질 영향 없음 (in_flight 정보 손실은 있지만 어차피 종료할 거라). 핵심은 refill 가드 누락.

## 수정

세 군데 모두 `and not self._cancelled` 추가:

1. **Initial seed** (main while True 진입 전) — 시작 직후 빠른 Cancel도 대응
2. **New-IDs seed** (in_flight 비었을 때 enqueue로 들어온 신규 ID 처리 분기)
3. **End-of-iter refill** — 사용자가 본 그 케이스

세 군데 모두 동일한 조건문 확장:

```python
while (
    submit_idx < len(self.paper_file_ids)
    and _queued_pages() < min_queued_pages
    and not self._cancelled
):
    _submit_next()
```

(이전 한 줄 표현은 길이가 ~90 char 넘기 시작해서 자연스럽게 multi-line으로.)

## Cancel 의미론 재정리

수정 후:
- **신규 submission 즉시 중단**: Cancel 누른 순간부터 `wrapper_submit` 호출 0건.
- **In-flight job은 서버에서 계속 처리됨**: 클라이언트는 cancel 신호를 서버에 전달하지 않음. 즉 Cancel = "더 보내지 마, 그리고 결과 안 받을게" 이지 "서버 멈춰" 가 아님.
- **다음 실행 시 자연 resume**: in-flight였던 job들은 서버에 그대로 남아있다가, 사용자가 다음에 같은 PDF를 다시 Process에 넣으면 [devlog 039](./20260528_039_OCR_In_Progress_Dedup_Client_Adapt.md)의 `in_progress=true` 경로로 resume polling. OCR 작업이 낭비되지 않음.

따라서 Cancel은 "지금 멈추고 나중에 이어서" 의 안전한 시그널이 됨. 이번 fix 전엔 "Cancel 직후 새 job 하나 더 들어가서 그것도 서버에서 처리됨" 이라 사용자가 "어? Cancel인데 작업 늘었네?" 느낌이 들 수 있었음.

## 영향 범위

- `_run_wrapper_pipeline`만 수정. 단순 RunPod parallel path (`_run_parallel`)는 ThreadPoolExecutor를 쓰는데 거기 cancel 처리는 별도 로직 (`pool.shutdown(wait=False, cancel_futures=True)`) 이라 무관.
- 이미 in-flight인 job들의 final state(processed/failed) 마킹은 어차피 못 함 — cancel로 polling을 끊었으니. 이 부분은 다음 실행에서 `in_progress` resume + polling 끝나면 정상 처리됨. PaperFile.status는 `'pending'` 그대로 유지되어 다음 batch에 자연 포함.
- UI 측 Cancel 버튼은 그대로 — `_cancelled` 플래그 set + 사용자에게 "waiting for in-progress files to finish..." 안내. 메시지 자체는 부정확함 (실제로는 polling을 중단하고 종료) 이지만 본 fix의 범위 밖.

## 미해결 / 다음

- 서버에 Cancel 시그널을 전달하는 옵션 — 의도적으로 "이 작업 진짜 중단" 이 필요하면. 현재는 클라이언트만 종료, 서버는 계속. GPU 시간 절약이 필요한 시나리오에서 고려.
- "waiting for in-progress files to finish" 메시지가 실제 동작과 차이남 — polling을 끊으니 wait이 아니라 abandon. 메시지 정정 또는 진짜로 in-flight 끝까지 polling 하고 끄는 옵션 추가 후보.
