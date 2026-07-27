# 076 — references PARTIAL의 원인 규명 (진단 기록, 코드 변경 없음)

> 2026-07-27. 후속: [075](./20260727_075_Qwen_5xx_Transient_Retry.md)
> 앱 재시작 + 서버 crash 대비 조치 직후의 배치에서 PARTIAL이 급증한 건에 대한 진단.

## 관측

재시작 후 새 배치(6,027편)의 첫 5편 중 **4편이 PARTIAL**:

```
[14:37:38] [1/6027] End-to-End Object Detection with Transformers — 34 refs PARTIAL
[14:40:47] [2/6027] Fragment, travelling and confusion of the Recent malaco — 14 refs PARTIAL
[14:45:55] [3/6027] History of the Palaeontological Society of Japan, 1995- — 95 references, 1 in library
[14:50:16] [4/6027] In Defense of the Triplet Loss for Person Re-Identifica — 24 refs PARTIAL
[14:57:55] [5/6027] PHYLOGENIE UND EVOLUTIONSÖKOLOGIE DER HEXACTINELLIDA — 102 refs PARTIAL
```

직전 세션 표본(11편 중 2편, 18%)보다 훨씬 높다.

### ⚠️ 정정 — 이 5편은 무작위 표본이 아니다 (사용자 지적)

"급증"으로 읽으면 안 된다. **새 배치의 앞부분은 지난 런의 재시도 큐**다.

`_refs_targets`는 `Paper.references_checked == False`만 고르고
**`.order_by(PaperFile.paper.desc())`** 로 내림차순 처리한다. 지난 런도 같은 코드라
높은 id부터 훑고 내려갔고, 그 구간에서 **checked를 못 받은 것 = PARTIAL/실패분**만
남는다. 새 배치를 다시 desc로 시작하면 그것들이 **맨 앞에 그대로 다시 온다**.

즉 첫 5편이 4편 PARTIAL인 건 예상된 결과다. **이미 한 번 깨끗이 파싱 안 된 논문들만
모아놓은 자리**이기 때문이다. 비율을 직전 표본과 비교하는 것 자체가 무의미하다.
(실제로 3번 `History of the Palaeontological Society of Japan`은 이번에 95건으로
**성공** — 재시도가 먹히는 케이스.)

### 덤: 모집단 PARTIAL 비율의 더 나은 추정치

배치 크기 변화로 역산할 수 있다.

- 지난 배치 대상 **8,036**편, 12:17 시점 카운터 **2,188**편 시도
- 새 배치 대상 **6,027**편
- 손 안 댄 잔여 = 8,036 − 2,188 = 5,848 → **잔류분 = 6,027 − 5,848 ≈ 179편**

시도분 2,188편 중 약 179편이 unchecked로 남았으니 **PARTIAL+실패 합계 ≈ 8%**.
(12:17 이후 재시작 전까지 더 처리됐을 테니 실제로는 ~9% 안팎.) 11편 표본에서 나온
18%보다 낮고, 이쪽이 모집단 추정치로 훨씬 믿을 만하다.

### 그래서 남는 구조적 문제

**재시도 포기 조건이 없다.** PARTIAL은 unchecked로 남고 다음 배치 맨 앞에서 다시
시도된다. 어떤 논문의 references 블록이 구조적으로 파싱 불가라면 그 논문은 **매 배치마다
선두에서 영원히 재시도**되며, 매번 앞자리를 차지한다. 재시도 횟수 카운터나 give-up
조건이 없다. (지금 규모에선 ~180편이라 무시할 만하지만, 원인이 안 잡히면 누적된다.)

## PARTIAL의 정의 — 발생 지점은 정확히 두 곳

`extract_references_llm`이 `complete=False`를 반환하는 경로는 둘뿐이다.

| | 조건 | **서버가 실제로 준 것** | 처리 |
|---|------|------------------------|------|
| **A** | 배치가 이미 floor(1건)인데 read timeout | **아무 응답 없음** (360초 초과) | 그 배치 버림 |
| **B** | `_parse_llm_json_array` 실패 | **HTTP 200 + 본문** — 다만 JSON 배열로 파싱 불가 (잘린 출력 `Unterminated string`, 배열 부재 등) | 그 배치 버림 |

둘 다 **나머지 배치는 살려서 저장**하고 `complete=False`만 세운다. 그래서 "34 refs
PARTIAL"처럼 건수가 붙는다. 논문은 `references_checked`가 안 찍혀 나중에 재파싱된다.

**5xx는 PARTIAL 원인이 아니다.** 075의 재시도 후에도 5xx가 지속되면 예외가 올라가
`_on_refs_failed` → 논문 전체 실패로 잡히고, 진행창엔 `— failed:` 로 표시된다.
즉 위 5편은 502/500 때문이 **아니다**.

## 판정: **B (깨진/잘린 JSON)**

A와 B는 코드가 이미 구분해서 로깅한다:

```
refs 12/34: timeout at batch 1 (already at floor) → skipping 1 refs
refs 12/34: bad JSON for batch 8 (Unterminated string ...) → skipping 8 refs
```

그런데 **desktop 앱에서는 이 줄이 어디에도 안 남는다.** `logging.basicConfig`는 CLI
스크립트(`extract_references.py`, `normalize_works.py`)에만 있고, `logging.getLogger('biblio')`에는
핸들러도 레벨도 붙지 않는다(파일 핸들러가 있는 건 `ocr` 로거뿐 — `~/.papermeister/logs/ocr.log`).
결과적으로 desktop에서는:

- INFO(배치별 PARTIAL 사유) → **폐기**
- WARNING/ERROR(`Qwen 502:`, `Qwen attempt 1/1 failed: … Read timed out`) → `logging.lastResort`로 stderr만

이 비대칭이 판정의 근거가 된다. **타임아웃은 WARNING이라 반드시 콘솔에 찍히는데, 해당
시간대 콘솔에 `Read timed out`이 한 줄도 없었다**(사용자 확인). A였다면 보였어야 한다.
→ 소거법으로 **B**.

## 가설: 엔진 크래시와 B가 같은 사건일 수 있다

`max_tokens` 산식(`min(8192, max(len(batch)*256, in_chars//2) + 1024)`)으로는 20건 배치가
6,144 토큰을 받는데 실제 출력은 entry당 80~130토큰 × 20 ≈ 2,600 토큰이라 **정상 상황에서
잘릴 여유가 크다**. 즉 단순 토큰 초과로는 설명이 약하다.

더 그럴듯한 쪽은 **생성 도중 엔진이 죽는 경우**다. vLLM 워커가 중간에 사망하면 앞단
프록시가 그때까지 생성된 부분을 **200으로 반환**할 수 있고, 그러면 잘린 JSON =
정확히 B가 된다. 075에서 본 크래시 루프와 동일 사건의 다른 얼굴일 수 있다.

다만 위 정정 이후 **이 가설의 근거는 약해졌다.** 원래는 "PARTIAL 급증 + 502 소멸"이
동시에 일어난 걸 서버 crash 대비 조치가 502를 부분응답 200으로 바꾼 것으로 설명하려
했는데, 급증 자체가 표본 편향이라 설명할 현상이 없다. 이 5편은 **예전에도 PARTIAL이던
바로 그 논문들**이므로, 서버 동작 변화가 아니라 **그 논문들 고유의 성질**(레퍼런스 블록
구조, 언어, OCR 품질)이 더 유력한 원인이다. 실제로 목록에 독일어 대문자 제목,
합자(ﬁ/ﬂ) 섞인 제목 등 OCR이 거친 흔적이 보인다.

**미확정이다.** 확정하려면 실제로 반환된 본문을 봐야 한다.

## 다음 (미실행 — 별도 승인 필요)

1. `biblio` 로거에 `ocr.py`와 동일한 파일 핸들러(`~/.papermeister/logs/biblio.log`, DEBUG)
   → 배치별 사유 + 파싱 실패 시 응답 앞부분이 남는다
2. PARTIAL 진행창 메시지에 사유·건수 실어 표시 — 예: `34 refs PARTIAL (bad JSON ×2)`
3. 위 로그로 잘린 지점을 확인 → 서버 부분응답 가설 검증

지금 상태로는 **데이터 유실은 없다**(PARTIAL은 unchecked로 남아 재파싱 대상). 다만
버려진 배치만큼 재작업이 쌓이고 있어, 원인 확정 전까지 실질 처리율은 표시된 것보다 낮다.
