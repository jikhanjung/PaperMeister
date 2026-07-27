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

---

# 후속 — 같은 세션에서 이어진 두 건

## (a) 가드가 실제로 작동함 + 회복 확인 (라이브)

리셋 후 새 런의 진행창:

```
[7/6090] Major Transitions in Evolution - Course Guidebook
         — 0 refs PARTIAL (model returned nothing for a located section), left to retry
[8/6090] STRATIFICATION OF COMMUNITY BY MEANS OF "COMMUNITY COEF — 38 references, 0 in library
```

- **[7]**: 새 가드가 정확히 의도대로 발동 — 섹션을 찾았는데 모델이 빈손 → checked 안 하고 재시도로 남김
- **[8]**: 이전 런에서 **`0 refs PARTIAL`** 이던 논문이 **38 references**로 회복

## (b) 축소 재시도가 진전을 못 내는 경우 (낭비 버그)

사용자가 서버 통계에서 발견:
```
17:38:29  9517 tok  369.4s  ok
17:32:29  9517 tok  369.3s  ok
17:26:29  9517 tok  368.4s  ok
```
(그 뒤 17:44:29에 네 번째가 더 붙었다.)

**6분 간격 = 360초 = 우리 read timeout.** 클라이언트가 360초에 포기하고, 서버는 369초에
완성해서 버리고, 다시 같은 요청. **토큰 수가 동일**하다는 게 핵심 — 요청이 전혀 안 줄었다.

원인: 타임아웃 재시도 조건이 `_refs_batcher.size > MIN` 이었고, 축소가 **컨트롤러 자기
숫자 기준**이었다.

> **정정** — 처음엔 "엔트리 1개짜리 blob이라 축소해도 안 줄어든다"고 적었으나 **틀렸다**.
> 나중에 확보한 `biblio.log`가 실제를 보여준다:
> ```
> 17:50:44 refs 4/5: timeout at batch 4 → shrink to 5, retrying
> 17:56:44 refs 4/5: timeout at batch 4 → shrink to 2, retrying
> 18:00:50 refs 2/5: 2 in 245.3s → next batch 1
> ```
> **`batch 4`** — 배치는 4개짜리였다.

실제 메커니즘은 이렇다. 이 논문은 총 5개 엔트리이고, 첫 배치가 `MAX_CHARS`(5000자)에 걸려
**4개로 잘렸다**. 그런데 컨트롤러 size는 20 근처였고 `BACKOFF_STEP=3`씩만 내려간다 —
**20 → 17 → 14 → 11 → 8 → 5**. 이 구간 내내 size가 배치 길이 4보다 크므로 재구성해도
**똑같은 4개 배치**가 나온다(chars 상한이 실제 제약이므로). 그래서 9517 토큰 요청이 다섯 번
반복됐고, size가 **2로 떨어져 4 미만이 된 순간**에야 배치가 2개로 줄어 245.3초에 성공했다.

즉 "축소가 불가능했다"가 아니라 **"컨트롤러가 배치 길이보다 한참 위에서 3칸씩 내려오느라
6번을 헛돌았다"**. 5~6 × 369초 ≈ **30분**을 태웠다.

### 수정

핵심은 `shrink_below(n)`이다 — **실패한 배치 길이 아래로 한 번에** 내린다. `MAX_CHARS`로
잘린 배치는 컨트롤러 size보다 짧을 수 있고, 그러면 컨트롤러 자기 숫자에서 3칸씩 물러나 봐야
배치가 안 줄어든다. `shrink_below(4)` → size 3 → **첫 재시도부터** 배치가 짧아진다.
아울러 조건을 `len(batch) > 1`로 바꿔, 진짜로 엔트리 1개인 배치는 재시도 없이 즉시 skip한다
(그 경우엔 어떤 축소도 요청을 줄이지 못한다).

```python
def shrink_below(self, n):
    self.ceiling = max(self.MIN, min(self.size - self.BACKOFF_STEP, n - 1))
```

엔트리 1개가 시간 안에 안 끝나면 **즉시 skip**한다. 재시도해봐야 같은 것을 보내고 같은
타임아웃을 기다릴 뿐이다. 타임아웃/절단 두 경로 모두 동일하게 적용.

**효과**: 관측된 케이스에서 5~6회 → 1~2회. 480초 타임아웃과 합치면 369초짜리는 애초에 첫 시도에 성공한다. 손실되는 레퍼런스 수는 동일하다 —
어차피 skip될 배치였고, 다만 **느리게 실패하던 것을 빠르게 실패**하게 만든 것.

### 곁들여: 타임아웃 기본값 360 → 480초

같은 숫자가 하나 더 알려준다. **서버는 369.4초에 매번 일을 끝냈다.** 우리 컷오프가
360초라 **9초 차이로 완성된 결과를 네 번 버린 것**이다. 타임아웃이 조금만 길었으면 첫
시도에 성공했을 작업이다.

기본값을 `_REFS_READ_TIMEOUT = 480`으로 올렸다(`qwen_read_timeout` pref로 여전히 override
가능). 위 수정으로 **쪼갤 수 없는 배치는 한 번만 시도**하게 됐으니 관대해지는 비용도 같이
싸졌다 — 배치당 최악이 `4 × 369초`에서 **단일 480초**로 오히려 크게 줄었다. 정상 배치
(15~60초)는 컷오프에 닿지 않으므로 영향 없다.

**남는 한계**: 혼자서도 타임아웃을 내는 거대 blob은 여전히 skip → PARTIAL → 재시도 →
같은 실패. blob 텍스트 자체를 쪼개는 방법이 있지만 이음매에서 서지 항목이 깨질 위험이
있어 이번 범위에서 제외했다. 빈도를 로그로 보고 판단할 것.

## (c) 아직 남은 구멍 — `low` confidence 오판

같은 런에서 이런 것들이 여전히 `no references section`으로 확정된다:
```
[2/6090] 88서울올림픽을 위한 도시 경관 조작과 도시 이미지 구축 전략 — no references section
[3/6090] Anatomy of the Mollusca: Sepia esculenta — no references section
[5/6090] canadiannaturali07natu.pdf — no references section
```
리셋 대상이었는데 재시도 후 **같은 판정을 다시 받았다**. 새 가드는 `high` confidence에만
걸리므로, **헤딩 탐지가 실패해 `low`로 떨어진 논문**은 여전히 모델의 "없다"를 그대로
받아들인다. 즉 이제 문제는 `[]` 탈출구가 아니라 **참고문헌 헤딩 탐지 실패**다
(한국어·일본어 학술지, 스캔된 합본 저널).

다음 작업 후보: `low` 블록에서 `split_reference_entries`가 많은 엔트리를 만들어냈다면
(= 블록이 목록처럼 생겼다면) `[]`를 믿지 않는 추가 가드, 또는 헤딩 사전 확장.
