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

## 4. (추가) 레퍼런스가 없는 문서의 영구 PARTIAL 루프

로그가 더 나오면서 **`0 refs PARTIAL`** 이 두 건 관측됐다.

```
[15:06:12] [7/6027] STRATIFICATION OF COMMUNITY ... — 0 refs PARTIAL   (88초)
[15:10:29] [9/6027] SVP-Letter-to-Editors-FINAL.pdf — 0 refs PARTIAL   (243초)
```

**타임아웃일 수 없다** — floor 타임아웃은 1건당 360초인데 둘 다 그보다 빨리 끝났다.
즉 응답은 빠르게 받았고 파싱에서 전부 실패했다.

문서 종류가 답이다. `SVP-Letter-to-Editors`는 **편집자에게 보내는 편지**로 참고문헌이
애초에 없다. 이때 벌어지는 일:

1. `extract_references_block`이 헤딩을 못 찾음 → **마지막 2페이지 fallback**(confidence=`low`)
2. 그 산문을 레퍼런스라며 LLM에 넘김
3. `_REFS_PROMPT`에 **"없으면 빈 배열"** 지시가 없었음 → 모델이 산문으로 답함
4. `_parse_llm_json_array` → `ValueError: No JSON array found` → skip → PARTIAL
5. checked가 안 찍히고 `paper.desc()` 정렬이라 **다음 배치 선두에 영구 재등장**

서버가 아무리 건강해도 결과가 동일하므로 **영원히 수렴하지 않는다**. 076의 "give-up
조건 없음"이 이 형태로 실현된 것 — 정상적인 `checked-empty`로 끝났어야 할 문서다.

### 수정 3건

**(1) 프롬프트**: "참고문헌이 전혀 없으면(본문 산문·편지·초록·감사의 글 등) 빈 배열 `[]`을
출력하고 산문으로 답하지 말 것" 한 줄 추가. 모델이 파싱 가능한 답을 내놓게 한다.

**(2) 두 파싱 실패를 분리**: `no_array`(배열이 아예 없음) vs `bad_json`(배열이 잘림).
**`json.JSONDecodeError`가 `ValueError`의 서브클래스**라 except 절 순서에 기대지 않고
`isinstance`로 명시 판별한다. 의미가 정반대다 — 잘린 건 응답을 잃은 진짜 실패(재시도 대상),
배열 부재는 대개 "이건 서지가 아니다"라는 신호.

**(3) fallback 블록 + 배열 부재 + 파싱된 것 0 + 타임아웃/절단 없음 → `complete=True`(checked-empty)**.
네 조건을 모두 요구하는 **보수적** 판정이다:
- `confidence == 'low'`(헤딩을 못 찾은 fallback)일 때만 — 진짜 레퍼런스 섹션을 찾았는데
  파싱 실패한 건 여전히 PARTIAL
- 일부라도 파싱됐으면 PARTIAL (혼재 신호)
- 타임아웃/절단이 하나라도 있으면 PARTIAL (응답을 못 받은 건 아무것도 증명하지 못함)

## 검증 (최종)

`tests/test_refs_partial_reporting.py` **8케이스** — `describe_skips` 렌더링 /
**잘린 배열은 `bad_json`, 산문은 `no_array`로 분리 집계** / 헤딩을 찾은(high) 문서의 산문
응답은 **PARTIAL 유지** / fallback(low)+배열부재는 **checked-empty** / fallback이어도
**타임아웃이면 checked-empty 아님** / 정상 응답 / 섹션 없음 조기 반환.

`ruff` clean, `mypy`(게이트 3모듈) clean, 전체 **95 passed**, headless desktop import OK,
`biblio.log` 실제 기록 확인.

## 남은 것

구조적으로 파싱 불가한 논문에 대한 일반적 **give-up 카운터**는 여전히 없다. 다만 위 (3)이
가장 큰 원인(레퍼런스 없는 문서)을 제거하므로, 나머지 잔류분의 실제 규모를 새 로그로 본 뒤에
필요성을 판단한다.
