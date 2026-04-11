# 021: P08 반영 러너 end-to-end 검증 + curated_author_shortfall 규칙 추가

[019](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md)에서 작성한 `biblio_reflect.py` 러너를 같은 날(2026-04-11) 이어진 후속 세션에서 실제 DB에 대해 처음으로 돌려봤다. single-paper, batch, manual override 세 가지 경로를 모두 실행하면서 정책의 빈틈 하나를 발견하고 P08에 `curated_author_shortfall` 규칙을 추가했다.

## 동기

러너는 019 세션 말미에 코드가 들어갔지만, 아무 Paper에도 실제로 반영해본 적이 없었다. Apply Biblio 버튼이 GUI에서 눌리기 전에 백엔드가 의도대로 도는지 CLI로 검증하는 게 목적. 결론적으로는 정책을 다시 다듬을 만큼의 반례도 하나 찾았다.

## 1. 단일 paper apply 검증 (paper 4)

### 1.1 후보 고르기

먼저 DB에 어떤 후보가 있는지 훑었다. 기대: "stub Paper + high-confidence biblio"가 정책의 주 타겟. 실제로는:

```
stub paper (year=None AND no authors) + high-conf biblio : 0건
curated paper + high-conf biblio                         : 66건
```

**stub이 0건이라는 게 이 DB의 현실**이었다. Zotero가 유일한 source라 모든 Paper가 import 시점부터 title/authors를 갖고 들어온다. P08 §2.3이 상정한 "stub → full overwrite" 경로는 지금 DB에서는 전혀 활성화되지 않는다. 나중에 1960s standalone 컬렉션이 OCR → reflect로 넘어오면 그때 커버된다.

대신 거의 항상 타는 경로는 **"curated Paper에 year만 빠져있음 → biblio의 year로 채움"** 이라는 얄팍한 빈 slot fill이었다. 표본:

```
--- paper 4 (biblio 1) ---
  title   동일
  year    None → 2017        ← 채울 것
  journal 동일
  doi     동일
  authors 동일
```

paper 4를 첫 희생자로 선정.

### 1.2 dry-run → real apply

```python
decision = biblio_reflect.evaluate(b, p)
# → action='auto_commit' reason=''

biblio_reflect.apply(b, p, dry_run=True)  # would_change=True, DB 무변경 확인
```

그 다음 CLI:

```bash
$ python scripts/reflect_biblio.py --paper 4
paper=4 decision=auto_commit reason='' changed=True
```

검증:

```
year: None → 2017
biblio 1.status: extracted → applied   ← 'auto_committed'가 아니라 'applied'
```

**`apply_single`이 `applied`로 마킹하는 게 맞는지** 가장 걱정했는데, P08 §3이 "manual confirmation이 auto를 이긴다"고 명시했고 구현도 그렇다. GUI의 Apply Biblio 버튼은 결국 이 경로를 탈 것이므로 "사용자가 직접 누른 건 auto_committed가 아니라 applied"가 맞다. batch 경로(`reflect_all`)는 `auto_committed`를 찍고, 둘이 의미론적으로 구분된다.

## 2. Batch dry-run — 반례 발견 (paper 9)

전체 dry-run:

```
[DRY RUN] scanned:        97
[DRY RUN] auto_committed: 6
[DRY RUN] needs_review:   31
[DRY RUN] skipped:        60    (59 journal_issue + 1 already_applied)
reasons:
  journal_issue            59
  override_conflict        21
  missing_authors           5
  missing_year              2
  low_confidence            2
  missing_title             1
```

6건의 auto_commit 후보를 파헤쳐 보니 5건은 전부 "year만 채움" 깔끔한 케이스. 그런데 **paper 9는 달랐다**:

```
--- paper 9 (biblio 9) ---
  P.year=1997         B.year=1997         (동일, no-op)
  P.journal=''        B.journal='Transactions of the Royal Society of South Australia'
  P.authors = ['Jago James B.']                              (1명)
  B.authors = ['James B. Jago', 'Lin Tian-Rui', 'G. Davidson',
               'Brian P. J. Stevens', 'C. Bentley']          (5명)
```

현재 P08 §4.2 "curated엔 빈 slot만 채움" 규칙을 그대로 따르면:

- `journal`: 빈 slot → **채움**
- `authors`: count≥1이라 "빈 slot 아님" → **건드리지 않음**
- 결과: journal만 바뀌고 authors는 1명인 반쪽 업데이트

정책대로 도는 건데, 이게 **curated 데이터가 실제로 망가진 경우**의 실패 모드다. Zotero import 시점에 한 명만 제대로 들어오고 나머지 4명이 드롭된 상황. "curated = 신뢰할 수 있다"는 P08의 기본 가정이 여기서 깨진다.

## 3. P08 §4.2.1 추가 — curated_author_shortfall

### 3.1 문제 정의

정확히: **curated Paper의 author 수 < biblio의 author 수** 이면 curated 데이터가 불완전하다는 강한 신호. 이때 빈 slot fill을 계속 진행하면 author 목록은 반쪽인 채로 다른 필드만 업데이트되어 "반쯤 맞는 Paper"를 만든다. 더 나쁜 상태.

역방향(P.authors > B.authors)은 단순히 biblio 추출이 덜 정확한 것. 기존 empty-slot 규칙대로 author 안 건드리고 진행하면 되므로 문제 없음.

### 3.2 구현

`papermeister/biblio_reflect.py::evaluate()`의 curated branch 맨 앞에 short-circuit 추가:

```python
# P08 §4.2.1: curated Paper whose author list is strictly shorter than
# the biblio's is a strong signal that the curated data is incomplete.
# Kick the whole decision to needs_review instead of half-filling other
# slots while leaving authors untouched.
existing_author_count = Author.select().where(Author.paper == paper).count()
if existing_author_count > 0 and len(authors) > existing_author_count:
    return Decision('needs_review', 'curated_author_shortfall', biblio.id)
```

P08 문서의 §4.2.1을 신설하고 §5의 reason 테이블에도 `curated_author_shortfall` 행 추가. desktop의 `biblio_service.py::_REASON_BLURB`에도 사용자용 tooltip 문구 등록.

### 3.3 재검증

```
auto_committed: 6 → 5         (paper 9 빠짐)
needs_review:  31 → 32        (+curated_author_shortfall: 1)
```

paper 9 단독으로 확인:

```python
>>> br.evaluate(biblio_9, paper_9)
Decision(action='needs_review', reason='curated_author_shortfall')
```

## 4. 깔끔한 5편 batch apply

```bash
$ python scripts/reflect_biblio.py --paper-ids 5,12,13,16,21
scanned:        5
auto_committed: 5
needs_review:   0
skipped:        0
errors:         0
```

| paper | 변경된 slot | biblio.status |
|---|---|---|
| 5  | year: None → 2006 | auto_committed |
| 12 | year: None → 2019 | auto_committed |
| 13 | year: None → 1999 | auto_committed |
| 16 | year: None → 2018 | auto_committed |
| 21 | year: None → 2014 | auto_committed |

모두 transaction atomic, 다른 필드 불변, author count 동일. 정확히 `apply_single`과 달리 batch path는 `auto_committed`로 마킹되는 것도 확인.

## 5. Paper 9 수동 해결

paper 9는 정책이 의도적으로 auto를 막은 케이스라서 수동 개입이 필요했다. 먼저 biblio를 풀로 확인:

- biblio 8, 9 두 개 존재. 내용 거의 동일 (llm-haiku, high, 5 authors).
- biblio 9가 약간 더 clean한 표기 ("James B. Jago", "Brian P. J. Stevens") → `select_best_biblio`가 9를 선택.

수동 수정 범위는 가장 보수적으로 고정:

| 필드 | 처리 |
|---|---|
| `title` | 그대로 (대소문자 스타일 차이뿐, 이 작업 범위 아님) |
| `year` | 그대로 (이미 같음) |
| `journal` | `''` → biblio 9의 값으로 채움 |
| `doi` | 그대로 (biblio도 빔) |
| `authors` | **biblio 9의 5명으로 replace-all** |
| `biblio 9.status` | `extracted` → `applied` |
| `biblio 8.status` | 그대로 (중복, 굳이 rejected로 낮출 이유 없음; applied biblio가 있으면 tie-break에서 자연스레 밀림) |

전부 `db.atomic()` 하나에 묶어 실행. 결과:

```
Paper 9 after manual fix:
  journal = 'Transactions of the Royal Society of South Australia'
  authors: James B. Jago / Lin Tian-Rui / G. Davidson / Brian P. J. Stevens / C. Bentley

biblio 9.status = applied
biblio 8.status = extracted (untouched)
```

## 6. 최종 상태

재실행한 dry-run:

```
scanned:        97
auto_committed: 0    ← 더 돌릴 게 없음
needs_review:  31
skipped:       66    (59 journal_issue + 5 already_committed + 2 already_applied)
```

오늘 세션에서 상태가 바뀐 7편:

- **applied × 2** — paper 4 (CLI single), paper 9 (manual DB)
- **auto_committed × 5** — paper 5, 12, 13, 16, 21 (batch)

남은 needs_review 31편은 성격별로:

- `override_conflict × 21` — 완전 curated, 할 일 없음
- `missing_authors × 5` — 추출 품질 이슈 (예: 18번 Paper가 title에 journal 이름을 집어넣은 케이스). Haiku 재추출 또는 vision pass가 해결책
- `missing_year × 2` — 파일명에 year가 있는 경우(`das2020.pdf`)는 filename heuristic으로 구제 가능
- `low_confidence × 2` — 책 챕터, 한국어 보고서. 일반 article 파이프라인 범위 밖
- `missing_title × 1` — "Reviewer 2 response" 문서. 논문 아님, 노이즈

## 배운 점

### "stub Paper 0건"은 이 corpus의 정체성이다

P08을 쓸 때 Zotero / filesystem 두 경우를 모두 포괄하게 설계했는데, 현재 DB에서는 filesystem 경로가 사실상 죽어 있다. 즉 P08의 stub 경로는 당분간 **dead code**다. 1960s standalone 컬렉션이 OCR → reflect로 들어오기 전까지는 테스트 커버리지가 0에 가깝다. 이걸 모르면 "러너 잘 돌아가네"라고 오판할 수 있다.

실제로 지배적인 경로는 P08 §4.2의 "curated, 빈 slot 채움"뿐이고, 그 안에서도 실질적으로 채워지는 건 거의 `year` 하나였다. Zotero 메타데이터가 그만큼 깔끔한 것.

### 정책의 실패 모드는 "반쯤 맞는 결과"를 만들 때 드러난다

paper 9 같은 케이스가 중요했던 건, 완전히 틀린 결과가 아니라 "journal은 채우는데 authors는 반쪽인 채로 두는" **부분 성공**을 만들기 때문이다. 완전 실패는 노이즈로 쉽게 발견되지만, 반쯤 맞는 결과는 더 많은 데이터에 묻혀서 눈에 띄지 않는다. `curated_author_shortfall`은 "author 배열의 길이를 curated 품질의 체크섬으로 쓰자"는 휴리스틱이다.

후속 단계: count 말고도 "제1저자 이름의 token overlap" 같은 더 섬세한 체크도 가능하지만, 당장은 count 규칙 하나로 paper 9를 잡았으니 오버엔지니어링할 필요는 없다.

### `applied` vs `auto_committed` 구분을 현장에서 쓰게 됐다

019에서 작성할 때는 "이 두 상태를 굳이 나눌 필요가 있나" 싶었는데, 오늘 실제로 single-paper(CLI) / batch / manual 세 경로를 돌려보니 구분이 즉각적으로 유용했다:

- `applied` = 사람이 명시적으로 결정한 결과. 향후 재평가에서 건드리지 않아야 함.
- `auto_committed` = 정책이 통과시킨 결과. 정책이 바뀌면 재평가 대상이 될 수 있음.

P08 §1의 tie-break에서 `applied`가 최상위로 오는 게 이 구분의 실용적 의미다. paper 9의 biblio 9가 `applied`로 찍혀 있으면, 다음에 더 나은 모델이 나와서 biblio 10이 생겨도 select가 9를 고른다 — 사람이 이미 승인한 결과를 뒤에서 덮지 않는다.

### CLI가 GUI 검증의 선행 경로가 된다

GUI 없이 `scripts/reflect_biblio.py` 하나로 전체 정책을 end-to-end 확인할 수 있었던 게 오늘 작업을 빠르게 만든 핵심이었다. 백엔드 검증을 UI 검증 앞에 놓으면 UI 버그와 정책 버그를 섞어서 디버깅하지 않게 된다. Phase 4의 `Apply Biblio` 버튼은 이제 "내부적으로 같은 `apply_single`을 부른다"는 신뢰를 갖고 구현/검증할 수 있다.

## P07 매트릭스 갱신 포인트 (다음 세션용)

[P07](./20260410_P07_Desktop_Software_Implementation_Plan.md) line 58의

```
| high-confidence auto-commit 러너 | ❌ 없음 | Phase 2의 실제 착수 지점 |
```

은 더 이상 맞지 않는다. 다음과 같이 갱신되어야 함:

- `high-confidence auto-commit 러너` → ✅ `papermeister/biblio_reflect.py` + `scripts/reflect_biblio.py`
- `PaperBiblio → Paper 반영 정책` → ✅ P08 (+ §4.2.1 `curated_author_shortfall`)
- Phase 2 완료 기준 중 "P08 정책에 따라 high-confidence 값이 Paper에 일괄 반영" → ✅

Phase 2의 진짜 남은 작업은 `list_by_library('needs_review')` 쿼리 정합성 하나뿐이다. Phase 2는 실질적으로 닫을 수 있다.

## 관련 문서

- [019 새 데스크탑 앱 스캐폴드 + P08 러너](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md) — 러너 본체 최초 작성
- [P08 반영 정책](./20260411_P08_PaperBiblio_Reflection_Policy.md) — §4.2.1 추가됨
- [P07 구현 계획](./20260410_P07_Desktop_Software_Implementation_Plan.md) — 매트릭스가 이 세션 기준으로 stale
