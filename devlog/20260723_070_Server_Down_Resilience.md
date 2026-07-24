# 070 — 서버 다운 복원력: references / biblio / OCR pause→복구

> 구현 기록 (2026-07-23). 무인 장시간 배치가 LLM/OCR 서버 죽음에 견디도록. 사용자 지적에서 출발.

## 1. 선결 버그: 부분 파싱을 checked로 찍던 것 (`8c15cdc`)

데스크톱 references 워커가 `extract_references_llm`의 `complete` 플래그를 **무시**하고
`references_checked=True`를 무조건 stamp. 서버가 죽어 부분/빈 결과가 나와도 done 처리 →
정상 배치 재실행에서 **영영 재파싱 안 됨(조용한 데이터 유실)**. 아웃티지 동안 큐를 소진하며
논문들을 checked-empty로 오염. CLI(`extract_references.py`)는 원래 `if complete:`만 stamp라
정상 — 데스크톱을 여기에 맞춤(부분결과는 unchecked 유지, `save_references`가 delete-and-replace라
재파싱 시 깨끗이 교체).

## 2. auto-stop → auto-pause → `ServerGuard` 추출

- 초기: 연속 실패 3회 시 서버 핑 → 죽었으면 큐 비우고 **정지**(`f12b03c`).
- 사용자 지적("정지하면 사람이 봐야 조치") → **일시정지 + 60초 백그라운드 폴링 + 자동 재개**로
  진화(`bb1d7b1`). 큐 유지, Cancel은 pause 중에도 동작.
- 3곳 중복 방지 위해 상태머신을 재사용 컨트롤러 **`desktop/workers/server_guard.py`**로 추출
  (`31c6e35`): streak + 확인핑 + 복구폴링 + pause/resume 콜백. 큐는 호출자 소유, guard는 "언제
  멈출지/복구됐는지"만. references 이관(behavior-preserving) + 유닛 테스트.
- **biblio 적용**(`0859040`): BiblioWindow에 Cancel + pause/resume. `biblio_server_alive()`는
  **qwen 백엔드만 폴링**(claude는 폴링할 서버 없어 True 반환 → pause 안 함). 유효 pred=record_ok,
  추출 err/task.failed=record_fail.

## 3. 502 판정 (설계 검증)

실장애가 **502**("upstream: All connection attempts failed" — 게이트웨이 살아있고 GPU만 죽음)로
나타남. 세 헬스체크(`references_server_alive`/`biblio_server_alive`/`ocr.is_ready`) 전부
**"정확히 200일 때만 alive"** 로 짜서 502를 올바르게 다운으로 판정 — 우연이 아닌 설계.

## 4. OCR (`papermeister/ui/process_window.py`, `fe4e691`)

OCR은 **동결 ProcessWindow + 병렬 ThreadPoolExecutor**라 `ServerGuard`(메인스레드 QTimer 전제)를
못 얹음. 대신 워커가 자체 QThread 루프라 **인라인 `sleep(30s)+is_ready()` 폴링**이 더 단순:
연속 실패 3회 → `ocr.is_ready()` 확인 → 죽었으면 루프 안에서 대기, 복구 시 resume, Cancel 시 탈출.
`_run_parallel`·`_run_wrapper_pipeline` 두 모드 모두. "동결"은 신규 UI 금지지, 활성 유지 OCR 엔진에
resilience 추가는 일관(사용자 승인).

## 5. Qwen read timeout 240→360 (pref) (`f8c33b7`)

간헐 read timeout = 바쁜 GPU가 정상 ~130s 배치를 240s 하드컷 너머로 밀어낸 것. 하드 타임아웃만
360s로(배처 TARGET_HI=130 유지 → 정상 배치 크기 불변, 여유분이 스파이크만 흡수), `qwen_read_timeout`
pref로 튜닝 가능.

## 결과
서버가 죽어도 파일을 줄줄이 failed/checked-empty로 태우지 않고 **멈췄다가 복구 시 자동 재개**.
라이브에서 502 아웃티지로 검증됨(수정 전 인스턴스가 502 다수 churn한 것으로 필요성 확인).
