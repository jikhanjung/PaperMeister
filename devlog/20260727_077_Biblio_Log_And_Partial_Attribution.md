# 077 — biblio 파일 로그 + PARTIAL 사유 표면화

> 구현 기록 (2026-07-27). 진단은 [076](./20260727_076_References_Partial_Cause_Diagnosis.md).

076에서 PARTIAL의 원인이 A(타임아웃)/B(깨진 JSON) 둘 중 하나인데 **desktop에서는 어느
쪽인지 알 방법이 없다**는 게 드러났다. 그걸 볼 수 있게 만든다.

## 1. `biblio` 로거에 파일 핸들러

`logging.basicConfig`는 CLI 스크립트에만 있고 desktop 앱은 `biblio` 로거를 아예 설정하지
않았다. 핸들러도 레벨도 없으니 **INFO는 전부 폐기**되고 WARNING/ERROR만
`logging.lastResort`로 stderr에 나갔다. 그래서 `Qwen 502:`는 보이는데
`refs N/M: bad JSON for batch …`는 한 줄도 안 보였던 것.

`ocr.py`와 **같은 패턴**으로 `~/.papermeister/logs/biblio.log`(DEBUG, 즉시 flush)를 붙였다.
로거별 파일 분리는 이 리포의 기존 관례(`ocr.log`, `zotero_sync.log`)를 따른 것.

## 2. 사유를 결과에 실어 보낸다

로그 파일만으로도 진단은 되지만, 매번 파일을 열어야 원인을 안다. 그래서 집계를 반환값에
포함시켰다.

`extract_references_llm` 반환을 4-tuple → **5-tuple**로:
```
(entries, source, model_version, complete, skipped)
skipped = {'timeout': n, 'bad_json': n, 'refs_lost': n}
```
`complete`가 True면 전부 0. 호출자 2곳(desktop 워커, `scripts/extract_references.py`)
모두 갱신. `describe_skips()` 헬퍼가 `bad JSON x2, 17 refs lost` 형태로 렌더한다
(스킵 없으면 빈 문자열 — 호출자가 조건 없이 붙일 수 있게).

진행창 메시지가 이렇게 바뀐다:
```
before:  34 refs PARTIAL (server?), left to retry
after:   34 refs PARTIAL (bad JSON x2, 17 refs lost), left to retry
```

**왜 5-tuple인가**: `complete`는 bool이라 여기에 정보를 더 실을 수 없고, 모듈 전역에
"마지막 스킵 상태"를 두는 건 스레드/재진입 관점에서 더 나쁘다. 호출자가 2개뿐이라
arity 변경 비용이 작다.

## 3. 잘렸는지 보려면 본문이 필요하다

예외 메시지(`Unterminated string …`)만으로는 **"모델이 딴소리를 했다"** 와
**"응답이 중간에 잘렸다"** 를 구분할 수 없다. 076의 유력 가설이 후자라 확인이 필요하다.
파싱 실패 시 응답 본문의 **head/tail 400자와 `max_tokens`**를 DEBUG로 남긴다 — 잘린
응답은 닫는 대괄호 없이 토큰 중간에서 끝나므로 tail만 봐도 판정된다.

부수적으로 두 스킵 로그를 INFO → **WARNING**으로 올렸다. desktop에서 stderr로도
보이게 하려는 것(파일 로그가 없던 환경에서도 최소한 사유는 보이도록). 정상 배치 진행
로그는 INFO 그대로 둬서 콘솔이 시끄러워지지 않게 했다.

## 재현 조건이 이미 갖춰져 있다

076에서 확인했듯 PARTIAL 논문은 `references_checked`가 안 찍혀 **다음 배치 맨 앞에서
다시 시도**된다(`_refs_targets`의 `paper.desc()` 정렬). 즉 **로그를 켜둔 채 다음 배치를
돌리면 같은 논문들이 선두에서 바로 재현**되어 원인이 확정된다. 별도 재현 절차가 필요 없다.

## 검증

`tests/test_refs_partial_reporting.py` 5케이스 — `describe_skips` 렌더링(빈/단일/복합) /
파싱 불가 응답이 `bad_json` 2건·`refs_lost` 2로 집계되고 `complete=False` /
정상 응답은 스킵 0 / **references 섹션 없음 조기 반환도 같은 5-tuple 형태**(호출자가
짧은 튜플을 언팩하지 않도록).

`ruff` clean, `mypy`(게이트 3모듈) clean, 전체 **92 passed**, headless desktop import OK,
`biblio.log` 실제 기록 확인.

## 남은 것

076이 지적한 **재시도 give-up 조건 없음**은 이번 범위 밖. 원인이 확정된 뒤에 다룬다
(구조적으로 파싱 불가한 논문이면 give-up이 필요하고, 서버 문제면 필요 없다).
