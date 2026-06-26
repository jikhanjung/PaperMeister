# 066 — references 추출: 배치 실패 시 부분 저장 (all-or-nothing 제거)

> 세션 (2026-06-26). 대량 재추출(`--scope all`) 중, 한 배치의 LLM JSON이 깨지면
> **논문 전체가 버려지던** 문제. 진행 로그에서 `1510 … refs 13/14` 까지 갔다가
> 마지막 배치 `Expecting ',' delimiter` 하나로 13개를 통째로 날리는 게 보여 수정.

## 배경

`extract_references_llm`은 references를 배치로 쪼개 Qwen에 보낸다. 기존엔:
- 배치 JSON 파싱 실패(`_parse_llm_json_array` → `json.JSONDecodeError`/`ValueError`)가
  **함수 밖으로 전파** → 스크립트 `_extract`가 `except`로 잡아 논문을 통째 skip.
- 플로어에서 타임아웃도 `raise` → 동일하게 논문 전체 폐기.

즉 250개짜리 references 중 240개를 파싱했어도 마지막 배치 하나가 깨지면 0개 저장.
LLM 출력이 max_tokens에서 잘리거나 모델이 콤마를 빠뜨리면 발생(temperature 0.1이라
재시도해도 같은 곳에서 깨지기 쉬움).

## 수정

### `papermeister/biblio.py`
- 루프에 `complete = True` 플래그.
- **배치 JSON 파싱**을 `try/except (json.JSONDecodeError, ValueError)`로 감쌈 →
  실패 시 그 배치만 skip(그 N개만 손실), `complete=False`, 로그
  `bad JSON for batch … → skipping N refs`, 계속 진행.
- **플로어 타임아웃**: `raise` → skip-and-continue(`complete=False`)로 변경. 일시적
  서버 부하로 한 배치 못 받아도 나머지는 살린다.
- 반환 시그니처 `(entries, source, model_version)` → **`(…, complete)`** 4-튜플.
  `tag`(로그 prefix)를 backend 분기 위로 올려 claude 경로에서도 정의되게.

### `scripts/extract_references.py`
- 4-튜플 언팩. **항상 저장**(부분이라도), `references_checked`는 `complete`일 때만 set.
  → 부분 결과는 지금 저장돼 즉시 사용 가능하고, 미완(complete=False) 논문은
  unchecked로 남아 **다음 `--scope all`이 재파싱**(save_references는 source 단위
  delete-and-replace라 부분→완전으로 자연히 교체됨).
- 로그: 완전=`ok | N refs`, 부분=`ok | N refs PARTIAL — some batches skipped, will retry`.

### `desktop/windows/main_window.py`
- 단일 추출 호출부 4-튜플 언팩(`…, _complete`). 동작 동일(부분이라도 저장).

## 검증

- `py_compile` 3개 파일 통과.
- 실제 로그의 깨진 JSON 3종(콤마 누락 `Expecting ',' delimiter`, 잘린 배열,
  배열 없음) 모두 `(JSONDecodeError, ValueError)`로 잡힘 확인(`JSONDecodeError`는
  `ValueError` 서브클래스).

## 적용 메모

- 현재 돌고 있는 프로세스엔 영향 없음(구 코드 이미 로드). **다음 런부터** 적용.
- 이번 런에서 ERR로 skip된 논문(예: 1508, 1510)은 checked가 안 켜졌으므로 다음
  `--scope all` 때 새 코드로 재시도되어 부분이라도 저장됨.
- 거대 ref 블록(예: 3000개+) 가드는 별도 과제로 보류.
