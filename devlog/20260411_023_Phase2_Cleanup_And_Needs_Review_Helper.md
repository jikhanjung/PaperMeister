# 023: Phase 2 뒷정리 — `needs_review` 쿼리 헬퍼 통합 + P07 매트릭스 갱신

[022](./20260411_022_Zotero_Writeback_And_Date_Parser.md)에서 Zotero write-back까지 끝낸 후, P07 Phase 2의 마지막 잔여 항목을 정리하고 매트릭스를 실제 상태에 맞춰 갱신한 짧은 세션 기록.

## 동기

HANDOFF에 "`list_by_library('needs_review')` 쿼리 수정 (현재 count와 list 불일치)"이 Phase 2의 마지막 ❌로 남아 있었다. 이것만 닫으면 Phase 2가 완전히 종료되어 작업 범위가 Phase 4 hookup으로 옮겨갈 수 있는 상태였다.

## 1. 측정 — 현재 mismatch는 보이지 않지만 구조적으로 취약

먼저 양쪽 쿼리를 동시에 돌려서 차이를 재현하려 했다.

```
library._count_needs_review():        0
paper_service.list_by_library():      0
raw SELECT COUNT(DISTINCT paper_id):  0
```

전부 0. 일치하긴 하지만, "비어있으니 일치"는 쓸모 없는 정보.

이유는 세션 9(022)가 dry-run만 돌렸기 때문이다. `reflect_all`은 non-dry 경로에서만 `PaperBiblio.status = 'needs_review'`를 persist한다. dry-run은 `evaluate()` 결과만 집계하고 DB 쓰지 않음. 오늘 세션 동안 non-dry batch를 한 번도 돌린 적이 없어서 실제로 DB에는 `status='needs_review'` 레코드가 0건이었다.

실제 상태를 만들기 위해 한 번 real batch:

```
$ python scripts/reflect_biblio.py
scanned:        97
auto_committed: 0
needs_review:   31
skipped:        66
```

이제 DB에 31편이 `needs_review` 상태로 스탬프됨. 다시 측정:

```
_count_needs_review():    31
list_by_library():        31
match: True
```

31/31로 일치. 하지만 이건 **"현재 데이터에서 운 좋게 일치"**일 뿐이다. 두 쿼리가 독립적으로 쓰여 있는 한, 한 paper에 `needs_review` 상태인 biblio가 여러 개 달리면 peewee의 `.distinct()` 렌더링 차이에 따라 count와 list가 다르게 나올 수 있다. 지금 그런 케이스가 없는 건 행운이지 보장이 아니다.

## 2. 수정 — 공유 헬퍼로 구조적 일치 강제

`desktop/services/library.py`에 단일 소스 헬퍼를 만들고, count와 list가 모두 호출하게 바꿨다.

```python
def needs_review_paper_ids() -> list[int]:
    """Paper ids whose best biblio is flagged needs_review (P08 §5).

    Single source of truth for both the count in the Library tree and the
    list shown by `paper_service.list_by_library('needs_review')` — sharing
    this helper makes it structurally impossible for the two to diverge.
    """
    seen: list[int] = []
    in_set: set[int] = set()
    for b in (
        PaperBiblio
        .select(PaperBiblio.paper)
        .where(PaperBiblio.status == 'needs_review')
    ):
        pid = b.paper_id
        if pid not in in_set:
            in_set.add(pid)
            seen.append(pid)
    return seen
```

SQL `DISTINCT` 대신 **Python 레벨에서 dedupe**한 이유:

- peewee의 `.distinct()`는 쿼리 컨텍스트에 따라 다르게 렌더된다 (`SELECT DISTINCT`, 서브쿼리 래핑, count 시 `COUNT(DISTINCT col)` vs `COUNT(*) FROM (subquery)` 등). 버전과 쓰임에 따라 달라짐.
- Python 이터레이션은 결과 집합이 **정확히 어떤 행이 들어왔는지** 투명하게 보여준다. "count()는 이 값, iter는 저 값"이 생길 수 없음.
- `needs_review`는 어차피 크지 않은 집합 (현재 31편, 앞으로 몇 천 수준). 31편 페치의 오버헤드는 무시 가능.

그 다음 기존 count 함수를 단순화:

```python
def _count_needs_review() -> int:
    return len(needs_review_paper_ids())
```

`paper_service.list_by_library('needs_review')`도 같은 헬퍼 호출:

```python
elif key == 'needs_review':
    from .library import needs_review_paper_ids
    biblio_paper_ids = needs_review_paper_ids()
    ...
```

검증:

```
needs_review_paper_ids(): 31
_count_needs_review():    31
list_by_library():        31
match: ids==count==list → True
paper_id sets: identical (31)
```

더 이상 두 경로가 서로 다른 SQL을 내지 않는다. 구조적 일치.

## 3. P07 매트릭스 갱신 — Phase 2 완전 종료 선언

021/022 이후 P07의 "현재 구현 상태" 매트릭스가 stale해졌다 (line 57 `반영 정책` ❌, line 58 `러너` ❌ 등). 실제 상태와 맞추는 작업.

### 매트릭스 변경

- `PaperBiblio → Paper 반영 정책`: ❌ → ✅ (P08 + §3.5 + §4.2.1)
- `high-confidence auto-commit 러너`: ❌ → ✅ (`biblio_reflect.py`, `reflect_biblio.py`)
- `Review 대상 식별 쿼리`: ❌ → ✅ (`needs_review_paper_ids()`)
- `Zotero write-back`: 🟡 → ✅ (`zotero_writeback.py`, network-atomic)
- `3-pane GUI (기존)`: 🟡 존재 → 🟡 **동결**
- `새 GUI`: ❌ → 🟡 **스캐폴드** (desktop 패키지, Apply Biblio 백엔드 연결됨)
- `Library/Sources 이중 네비`: ❌ → ✅

추가된 행:
- `Paper.date` 컬럼 (Zotero round-trip 무손실)
- Zotero 날짜 파서 버그 수정 (backfill로 1,671편 year 복구)

### Phase 2 섹션 재작성

**before**: "(부분 완료)" — 상태 5줄 중 3개 ❌

**after**: "✅ (완료)" — 상태 6줄 모두 ✅, 작업 항목 7개 모두 strikethrough, 완료 기준 5개 모두 체크

완료 기준에 Zotero write-back 기준 추가:

> Zotero-sourced Paper의 write-back이 drift-free로 동작한다 ✅ (devlog 022)

### "바로 해야 할 일" 재작성

Phase 2 관련 항목(P08 작성, 러너 구현)을 모두 ✅로 닫고, 남은 목록을 **Phase 4 hookup + Phase D**로 재구성:

- desktop GUI 실제 실행 + Apply Biblio 버튼 클릭 실증
- desktop batch Reflect 트리거 UI + 결과 다이얼로그
- desktop background worker
- desktop PaperList StatusBadge delegate
- desktop OCR 미리보기 카드
- Phase D (대량 Haiku 추출)

"뒤로 미루는 것" 목록의 `Zotero write-back 정책 문서 → Phase 6`은 "P08 §3.5로 흡수됨"으로 표시.

## 배운 점

### dry-run은 상태가 없다

세션 9 동안 "needs_review 쿼리가 0을 반환하는데 이게 count/list 버그인가?"를 혼동할 뻔했다. 실체는 단순했다 — **persistence가 안 일어났을 뿐**. dry-run은 `evaluate()` 결과만 집계하고 biblio status는 건드리지 않는다. UI가 Library 트리에서 "Needs Review"를 표시하려면 **반드시 한 번은 non-dry batch가 돌아야** 한다.

이건 P07/P08 어디에도 명시돼 있지 않은 암묵적 의존성이다. 향후 Phase D에서 `extract_biblio.py`로 새 biblio가 들어올 때마다 non-dry reflect도 같이 돌려야 UI가 최신 상태를 반영한다. 이걸 놓치면 "어제 추출했는데 Library에 안 보이네" 버그가 생긴다.

대안으로 생각해 본 것:
- UI 쿼리가 `evaluate()`를 직접 호출해서 on-the-fly 판정 → 성능 문제
- `extract_biblio.py` 자체가 reflect dry-run을 포함해서 status 스탬프 → 관심사 혼합
- `PaperBiblio` insert 시 trigger로 자동 평가 → DB 계층에 정책 두면 복잡도 폭발

가장 단순한 해결은 **기록만 해두고 사용자가 운영 루틴으로 지키는 것**. "biblio 추출 후 → non-dry reflect 한 번" 이 워크플로우를 HANDOFF와 Phase D 계획에 명시할 것.

### 구조적 일치 vs 행운의 일치

이번 count/list mismatch는 "현재 데이터에서는 우연히 일치"라는 상태였다. 그대로 두어도 당장 증상은 없었을 것이다. 하지만 한 paper에 여러 needs_review biblio가 달리는 케이스는 실제로 발생할 수 있다 — 예를 들어 Haiku와 Sonnet이 같은 paper에 각자 `needs_review` 판정을 내리면 2개 row가 된다. 그 시점에 peewee의 distinct 렌더링이 count와 iter에서 다르게 나오면 UI가 "count=2, list=1"을 보여주는 난감한 상태가 된다.

구조적 일치 보장이 중요한 건 **이런 잠재 버그가 장기간 숨어있다가 데이터 특성이 바뀌는 순간 터진다**는 점 때문이다. "현재 통과하니까 괜찮다"는 regression만 방어하고, 아직 오지 않은 edge case는 방어하지 못한다. 공유 헬퍼로 리팩터링하는 건 15분이지만, 이후 모든 비슷한 엣지 케이스를 한 번에 처리한다.

### P07을 살아있는 문서로 유지하기

매트릭스를 갱신하면서 느낀 점: P07은 `가설 + 현재 상태`를 한 문서에 담는 구조인데, 현재 상태는 세션마다 바뀐다. 매 세션 끝에 매트릭스를 touch하지 않으면 금방 stale해진다. 021 이후 ❌ 두 줄을 며칠 방치한 결과, 오늘 "이미 다 된 걸 ❌로 기억하고 있는" 상태가 됐다.

운영 규칙: **HANDOFF에 "갱신해야 할 P07 라인"을 bullet으로 적어두고, 세션 마무리 때 반드시 지나가기**. 세션 9에서 이걸 했는데, 세션 10 초입에 바로 소비됐다. 패턴으로 굳히면 좋겠다.

## 관련 문서

- [022 Zotero write-back + 날짜 파서 수정](./20260411_022_Zotero_Writeback_And_Date_Parser.md) — 세션 9, 오늘의 본편
- [021 P08 러너 검증](./20260411_021_P08_Reflection_Runner_Verification.md) — 세션 8
- [P07 구현 계획](./20260410_P07_Desktop_Software_Implementation_Plan.md) — 매트릭스 + Phase 2 종료 상태로 갱신됨
- [P08 반영 정책](./20260411_P08_PaperBiblio_Reflection_Policy.md) — §3.5 + §4.2.1 추가된 상태
