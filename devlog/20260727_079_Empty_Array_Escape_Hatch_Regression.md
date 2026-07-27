# 079 — `[]` 탈출구 역효과: "no references section" 오판 회귀

> 2026-07-27. [077 §4](./20260727_077_Biblio_Log_And_Partial_Attribution.md)에서 넣은
> 프롬프트 한 줄이 만든 회귀. **내가 만든 버그를 내가 잡은 기록.**

## 계기

사용자 질문: "이런 경우는 어떻게 처리하고 있어? 완료로 처리하나?"

```
[16:58:47] [9/6023]  Treatise on Invertebrate Paleontology - Part R - Arthro — no references section
[16:58:52] [10/6023] 곡산통(쉴루르기 하세-상세초)동물군에 대하여 — no references section
```

Treatise는 무척추고생물학 **논저(monograph)** 이고, 두 번째는 한국어 고생물 논문이다.
둘 다 참고문헌이 없을 리가 없다. 로그를 봤다.

## 로그가 말한 것

```
16:58:47 INFO refs 5/10:  5 in 3.1s → next batch 5     ← Treatise, 엔트리 10개
16:58:47 INFO refs 10/10: 5 in 0.5s
16:58:48 INFO refs 5/47:  5 in 0.4s → next batch 6     ← 한국어 논문, 엔트리 47개
16:58:48 INFO refs 11/47: 6 in 0.6s
16:58:50 INFO refs 17/47: 6 in 1.0s
16:58:50 INFO refs 23/47: 6 in 0.3s
...
```

같은 런의 정상 배치는 **엔트리당 3.7~6.0초**(중앙값 4.4초)다. 위는 **엔트리당 0.05초**.
레퍼런스 1건 출력이 ~107토큰이고 서버가 ~20 tok/s이므로, 6건을 0.3초에 생성하는 건
물리적으로 불가능하다. 즉 **모델이 `[]`만 돌려줬다.**

구조적으로도 확정된다. 화면의 `no references section`은 `complete=True and n==0`일 때만
뜬다. `complete=True`는 **어떤 배치도 skip되지 않았다**는 뜻이므로 모든 배치가 정상
파싱됐고, 그런데 결과 객체가 0개다 — 파싱되면서 0개를 주는 응답은 `[]`뿐이다.

**그리고 47개 엔트리.** `split_reference_entries`가 47개로 쪼갰다는 건 블록이 번호형/
문단 구분이 뚜렷한 **실제 참고문헌 목록**이었다는 뜻이다. 산문이 그렇게 쪼개지지 않는다.

## 원인: 내가 준 탈출구

077 §4에서 편지·초록류를 처리하려고 프롬프트에 넣은 줄:

> "If the text contains NO bibliographic references at all … output an empty array []"

CJK 서지처럼 파싱이 까다로운 입력에서 모델이 **이 탈출구를 남용**했다. 그리고 그 결과가
`complete=True` → `references_checked=True` → **해당 논문은 레퍼런스 0건으로 영구 확정**,
이후 어떤 배치에도 다시 안 잡힌다.

**교환비가 최악이다.** 이전 상태는 PARTIAL 무한 재시도(성가시지만 **복구 가능**)였는데,
바꾼 결과가 **조용한 영구 유실**이 됐다. 회귀의 방향이 정확히 반대로 잘못됐다.

## 수정

### 1. 프롬프트 조건 강화
`[]`를 "명백히 서지가 아닐 때"로 좁히고, **포기 사유가 될 수 없는 것**을 명시했다 —
OCR 잡음, 낯선 언어·문자(한국어/일본어/중국어/러시아어…), 축약 저널명, 특이 포맷.
"읽을 수 있는 것만 채우고 나머지는 비워라."

### 2. 코드 가드 (진짜 안전망 — 프롬프트는 보장이 아니다)

```python
if complete and not parsed and confidence != 'low':
    complete = False        # UNCHECKED로 남겨 재시도
    skipped['empty_result'] += 1
```

**참고문헌 섹션을 실제로 찾아냈는데(`high`) 아무것도 못 뽑았다면 그건 발견이 아니라
모순**이다. 블록 탐지를 믿고 모델을 의심한다.

비대칭이 판단 근거다:
- 잘못 checked → **레퍼런스 0건으로 영구 확정, 아무도 다시 안 봄** (조용한 유실)
- 잘못 unchecked → **재시도 한 번** (비용 거의 0)

fallback(`low`) 블록의 `[]`는 **그대로 checked-empty 유지** — 편지·초록 케이스가 계속
동작해야 하고, 거기선 `[]`가 실제로 "서지가 아니다"라는 신호다.

### 3. 진단 정보 추가
`refs: block confidence=high, 47 entries` 를 추출 시작 시 로깅. 이번 조사에서 confidence와
엔트리 수를 로그에서 못 읽어 추론에 의존해야 했다. 다음엔 바로 보인다.

### 4. 이미 잘못 찍힌 논문 복구
`scripts/reset_references.py --scope empty-checked` 추가 — `references_checked=True`인데
`Reference` 0건인 논문을 찾아 플래그를 해제한다. 지울 데이터가 없으므로(0건) **안전**하고,
진짜로 참고문헌이 없는 논문은 재시도해도 같은 판정을 다시 받을 뿐이다. 기존 `--execute`
관례 그대로 dry-run이 기본.

## 검증

`tests/test_refs_partial_reporting.py` **12케이스**(+2):
- 찾아낸 섹션(`high`)에 `[]` 응답 → **checked 안 함**, `empty_result` 집계, 사유 문구 노출
- fallback(`low`)에 `[]` 응답 → **checked-empty 유지**(편지 케이스 회귀 방지)

`ruff` clean, `mypy`(게이트 3모듈) clean, 전체 **105 passed**.

## 남은 판단

`high` 블록에서 `[]`가 반복되면 그 논문은 다시 "매 배치 선두에서 영원히 재시도"가 된다.
프롬프트 수정이 먹히면 해소되지만, 안 먹히면 give-up 카운터가 그때는 정말 필요하다.
**다음 런의 로그로 확인할 것** — 새로 추가한 `block confidence=…, N entries` 줄과
`model returned nothing for a located section` 경고가 그 신호다.

## 교훈

LLM에게 "모르겠으면 빈 값을 내라"는 탈출구를 줄 때는, **그 빈 값이 최종 상태로 굳는
경로가 있는지** 먼저 봐야 한다. 여기서는 `[]` → `checked` → 재조회 불가였다. 탈출구는
되돌릴 수 있는 상태로만 이어져야 한다.
