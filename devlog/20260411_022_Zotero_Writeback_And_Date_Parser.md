# 022: Zotero write-back + `Paper.date` 추가 + 날짜 파서 버그 수정

[021](./20260411_021_P08_Reflection_Runner_Verification.md)에서 7편을 local DB에 반영한 직후, "Zotero 서버는 여전히 옛 상태"라는 드리프트가 드러났다. 이 문서는 그 드리프트를 되돌리고, 원인을 추적하다 발견한 더 큰 버그(날짜 파서)를 고치고, 올바른 write-back 경로를 새로 지은 작업 기록이다.

## 동기 — drift가 만든 재구조화 기회

021까지 `biblio_reflect.apply()`는 무조건 local SQLite에만 썼다. Zotero-sourced Paper에 이걸 쓰면 두 가지 문제가 동시에 터진다.

1. **Drift**: local.year='2017'인데 Zotero는 여전히 year가 없음 → `resync_zotero.py`가 돌면 local 변경이 전부 revert됨.
2. **가정 오류**: "local이 source of truth이면 local 쓰기로 충분"이 아니라 "local은 Zotero의 derivative"라는 실제 관계와 정반대.

사용자 제안: **한 방향 sync**. `PaperBiblio → Zotero API → Zotero 서버 → (pull) → local`. 양방향 sync의 충돌 해결 없이 단순하게.

이 단순한 방향 결정이 오늘 세션의 중심축이 됐다.

## 1. Drift pull-back (복구 먼저)

021에서 수정한 7편(4, 5, 9, 12, 13, 16, 21)을 Zotero의 현재 상태로 되돌린다. 주의사항:

- `resync_zotero.py`는 **destructive** (Paper drop → PaperBiblio cascade 삭제). 오늘 PaperBiblio 추출 결과를 잃을 수 없으므로 **사용 금지**.
- 대신 타겟 7편만 in-place refresh하는 one-off 스크립트를 작성.

로직:

```python
for pid, biblio_ids in TARGETS:
    p = Paper.get(Paper.id == pid)
    item = client._zot.item(p.zotero_key)
    parsed = client._parse_item_metadata(item['data'])
    with db.atomic():
        p.title, p.year, p.journal, p.doi = parsed[...]
        p.save()
        Author.delete().where(Author.paper == p).execute()
        for i, name in enumerate(parsed['authors']):
            Author.create(paper=p, name=name, order=i)
        PaperBiblio.update(status='extracted', review_reason='').where(
            PaperBiblio.id.in_(biblio_ids)
        ).execute()
```

결과: 7편 모두 Zotero 상태로 복원, PaperBiblio 상태는 `applied`/`auto_committed` → `extracted`로 reset (재평가 대상으로 돌림).

Zotero version 기록 (write-back 후 증가 확인용):
- paper 4: 26116, paper 5: 26116, paper 9: 25612, paper 12: 25615, paper 13: 25897, paper 16: 25966, paper 21: 25933

## 2. 파서 버그 발견 (중간에 터진 더 큰 이야기)

Zotero write-back 모듈을 만들기 전에 pyzotero `update_item` 시그니처를 probe하다가 우연히 발견했다.

```
paper 4 zotero.data.date = '08/2017'
```

그런데 021에서 "paper 4는 year가 비어 있어서 biblio로 채울 값이 있음"이라고 결론 내렸다. **Zotero에는 이미 2017이 있었는데 local.year=None**? 원인은 `zotero_client.py::_parse_item_metadata`의 이 줄:

```python
year = int(date_str[:4])   # int('08/2') → ValueError
if not (1900 <= year <= 2100):
    year = None
```

두 개의 실질 버그:

1. **first-4-chars 슬라이스가 M/YYYY 형식을 못 먹음.** Zotero `data.date` 필드는 free-form 문자열이고 `"08/2017"`, `"8/2006"`, `"September 2018"` 같은 형식이 정상 패턴. 첫 4글자 = `"08/2"` → int 변환 실패 → year None.

2. **1900-2100 범위 필터가 pre-1900 고전 문헌을 탈락시킴.** 이 corpus는 고생물 논문이고 `"1865"`, `"1889"` 같은 19세기 고전 인용이 있다. 실제로 샘플에서 paper 3462=1865, paper 3541=1889가 확인됨.

### 전체 영향

```
전체 Paper:                9,783
year = NULL:               4,615 (47.2%)
```

랜덤 20편 샘플링해서 Zotero 상태 비교:

| 상태 | n | 비율 |
|---|---:|---:|
| Zotero.date 존재 + 파싱 가능 | 11 | 55% |
| Zotero.date도 진짜 비어있음 | 9 | 45% |

즉 **절반 정도가 파서 버그에 의한 false null**. 47.2% × ~55% ≈ 2,500편이 복구 가능.

### Zotero가 이미 normalize해 줌 — `meta.parsedDate`

probe 중 발견: Zotero 서버는 free-form `data.date`를 자체 파싱해서 `meta.parsedDate`에 ISO 형식으로 제공한다.

```
data.date='08/2017'     meta.parsedDate='2017'
data.date='2022-12-16'  meta.parsedDate='2022-12-16'
data.date='1865'        meta.parsedDate='1865'
```

**regex 쓸 필요 없음, 서버가 파싱해 준 값을 그대로 쓰면 됨.** Fallback regex는 `meta.parsedDate`가 없을 희귀 케이스용 안전망으로만 둠.

## 3. 아키텍처 결정: `Paper.date` 컬럼 추가 (Option B)

파서만 고치는 것(Option A) vs `Paper.year`를 `Paper.date`로 완전 교체(Option C) 사이에서 **Option B = 둘 다 두기**로 결정:

```python
class Paper:
    date = TextField(default='')      # Zotero data.date 원본 ('08/2017', '2022-12-16', '1865')
    year = IntegerField(null=True)    # meta.parsedDate에서 뽑은 int (인덱스용 파생 필드)
```

결정 근거:

1. **Round-trip 무손실**: write-back 시 `date`를 그대로 push → Zotero의 `"08/2017"`을 `"2017"`로 덮는 실수 없음.
2. **기존 consumer 전부 그대로 작동**: P08, 검색, UI가 모두 `year`만 보면 됨. `date`는 ingestion/writeback만 의식.
3. **biblio.year(int)와 Paper.year(int) 일치**: 비교/변환 브릿지 불필요.
4. **비용 최소**: 컬럼 하나 + 파서 한 줄 + backfill 한 번.

Option C(완전 교체)는 모든 consumer를 고쳐야 해서 세션 예산을 초과할 위험 + biblio.year와 Paper.date 간 타입 불일치가 오히려 커졌을 것.

## 4. 구현 — 파서 수정 + 컬럼 + backfill

### 4.1 `papermeister/zotero_client.py`

- 모듈 레벨 `_YEAR_RE` + `extract_year_from_date()` 헬퍼 추가 (fallback 전용)
- `_parse_item_metadata(data, meta=None)` 시그니처 확장 — `meta.parsedDate` 우선, 없으면 regex fallback, `date`(원본)도 반환 필드에 포함
- `get_collection_items()` — parent items를 `data`만이 아니라 full `{data, meta}` 구조로 저장해 `meta`도 파서로 넘김

### 4.2 `papermeister/models.py` + `database.py`

- `Paper.date = TextField(default='')`
- migration: `ALTER TABLE paper ADD COLUMN date TEXT DEFAULT ''` (paper.zotero_key 바로 뒤에)

### 4.3 `papermeister/ingestion.py`

- `fetch_zotero_collection_items()`에서 Paper 생성 시 `date=item.get('date', '')` 전달

### 4.4 Bulk backfill

```python
# ~99 API calls instead of 4,615
all_items = c._zot.everything(c._zot.top(limit=100))   # top-level only
```

9,871 parent items를 7분에 받아옴 (411s). 로컬 매칭:

```
total_matched:     9783
unmatched:         0
date_changed:      6841  (로컬 date 컬럼이 비어있었으므로 대부분 변경)
year_changed:      1671  (bug로 None이던 year가 복구)
year_newly_set:    1671
year_cleared:      0     (regression 없음)
```

**1,671편 year 복구**. 샘플 기준 예상치(~2,500)보다 보수적이지만 유의미한 양. NULL year는 4,615 → 2,944로 감소.

## 5. Zotero write-back 모듈

`papermeister/zotero_writeback.py` 신설. 핵심 함수:

```python
def writeback_biblio(biblio, paper, *, client, dry_run, force_override) -> WritebackResult:
    item = client._zot.item(paper.zotero_key)     # fresh fetch (version + state)
    data, meta = item['data'], item.get('meta')
    patch = _compute_patch(biblio, data, force_override=force_override)

    if not patch:
        # Case A: Zotero already complete. Local may still be stale; refresh.
        _refresh_local_paper(paper, data, meta, client)
        return WritebackResult(action='noop', reason='zotero_already_complete')

    # Case B: real patch
    payload = dict(data); payload.update(patch)
    client._zot.update_item(payload)              # returns True, raises on HTTP error
    fresh = client._zot.item(paper.zotero_key)    # re-fetch for new version
    _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)
    return WritebackResult(action='wrote', patch=patch)
```

### 5.1 Patch 계산 — `_compute_patch`

**Zotero의 현재 상태 대비** empty-slot 계산 (local이 아니라). 이게 이중 방어의 핵심: local parser가 버그로 "year=None"이라고 해도 Zotero의 fresh data에 year가 있으면 patch에 포함되지 않음.

```python
if not data.get('title','').strip() and biblio.title: patch['title'] = ...
if not data.get('date','').strip() and biblio.year:   patch['date'] = str(biblio.year)
if not data.get('publicationTitle','').strip() and biblio.journal: patch['publicationTitle'] = ...
if not data.get('DOI','').strip() and biblio.doi:     patch['DOI'] = ...

existing_count = sum(1 for c in data.get('creators',[]) if c.get('creatorType')=='author')
if existing_count == 0 and biblio_authors:
    patch['creators'] = [{'creatorType':'author','name':n} for n in biblio_authors]
elif force_override and biblio_authors and len(biblio_authors) > existing_count:
    patch['creators'] = [{'creatorType':'author','name':n} for n in biblio_authors]  # §4.2.1 escape hatch
```

Creator schema는 MVP에서 **single-field `name`** 사용. first/last 분리는 `"Brian P. J. Stevens"`, `"林天瑞"` 같은 케이스에서 위험해서 의도적으로 회피. Zotero UI에서도 single-name이 정상 표시됨.

### 5.2 `biblio_reflect.apply()` 분기

```python
def apply(biblio, paper, *, dry_run=False, force_override=False) -> bool:
    if paper.zotero_key:
        # Zotero-sourced — upstream first, then mirror
        client = ZoteroClient(...)
        result = zotero_writeback.writeback_biblio(
            biblio, paper, client=client,
            dry_run=dry_run, force_override=force_override,
        )
        if not dry_run:
            biblio.status = 'auto_committed'
            biblio.review_reason = result.reason   # 'zotero_already_complete' for Case A
            biblio.save()
        return result.changed
    return _local_apply(biblio, paper, dry_run=dry_run)
```

기존 local-only 로직은 `_local_apply()`로 그대로 떼어냄 (filesystem stub용, 현재 DB에서는 0건).

### 5.3 pyzotero 계약 확인

`update_item(payload)`은 payload가 **flat data dict** (key, version, itemType, title, ... 모두 top-level). nested `{data: {...}}` 아님. 그리고 `backoff_check` decorator가 response.raise_for_status() 후 **True를 리턴**하므로 업데이트된 item을 돌려주지 않음 → 성공 후 명시적으로 re-fetch 필요.

`check_items`가 payload의 field name을 Zotero template과 대조 검증하므로, 우리는 **fresh fetch된 data dict 위에 patch를 overlay**하는 방식으로 안전하게 구성 (모든 field는 이미 Zotero에서 온 valid name).

### 5.4 `force_override` 플래그

`curated_author_shortfall` 같은 "알고도 덮어쓰기" 케이스의 escape hatch. `scripts/reflect_biblio.py`에 `--force` CLI 옵션으로 노출. batch path(`reflect_all`)는 항상 `force_override=False` — escape hatch는 single-paper 경로 전용.

`apply_single(paper_id, *, mark_applied=True, force_override=False)`로 전파되고, `mark_applied`는 Case A no-op도 포함해서 **무조건** applied로 flip (사용자 click = confirmation).

## 6. 검증 — 7편 end-to-end

### 6.1 Paper 5 (Case A no-op)

backfill 이후 local.year=2006, Zotero.date='8/2006'이 이미 채워짐. biblio도 year=2006.

```
Zotero version BEFORE: 26116
$ python scripts/reflect_biblio.py --paper 5
paper=5 decision=needs_review reason='override_conflict' changed=False force=False
Zotero version AFTER:  26116  (unchanged ✓)
biblio 2 status: 'applied'  review_reason: 'zotero_already_complete'
```

- 결정 레벨: `evaluate()`가 이미 override_conflict 판정 (local에 이제 full data 있음)
- apply 레벨: `needs_review`는 apply_single을 통과하므로 writeback이 실제로 호출됨
- writeback 레벨: Zotero fresh fetch → patch 계산 → 비어있음 → Case A
- 결과: **Zotero API write 호출 없음, version 불변**. 이중 방어의 하위 레벨이 정확히 작동.

### 6.2 Paper 9 (Case B write with `--force`)

Zotero는 creators=1명(`Jago James B.`)에 journal 비어있음. biblio는 creators=5명 + journal 있음. 현재 정책은 `curated_author_shortfall` 판정.

```
$ python scripts/reflect_biblio.py --paper 9 --force
paper=9 decision=needs_review reason='curated_author_shortfall' changed=True force=True
```

검증:

```
Zotero version:  25612 → 31052  (변경됨 ✓)
Zotero.creators: [Jago James B.] → [James B. Jago, Lin Tian-Rui, G. Davidson,
                                    Brian P. J. Stevens, C. Bentley]  ✓
Zotero.publicationTitle: '' → 'Transactions of the Royal Society of South Australia' ✓
Zotero.title: unchanged (MT Wright 대소문자 그대로 — 덮어쓰지 않음) ✓

Local Paper 9: creators 5명으로 동기화됨 ✓
PaperBiblio 9 status: 'applied'  review_reason: '' ✓
```

**이 케이스가 오늘 세션에서 유일한 실제 Zotero API write**. 다른 모든 후보는 Case A no-op.

### 6.3 나머지 5편

paper 4, 12, 13, 16, 21 — 전부 Case A no-op. status만 `applied` + `zotero_already_complete`로 마킹.

## 7. 최종 상태

```
$ python scripts/reflect_biblio.py --dry-run
scanned:        97
auto_committed: 0
needs_review:   31
skipped:        66
reasons:
  journal_issue            59
  override_conflict        21
  already_applied           7  ← 오늘 처리한 7편
  missing_authors           5
  missing_year              2
  low_confidence            2
  missing_title             1
```

### 오늘의 7편 biblio status

| biblio | paper | status | reason | 실제 API write |
|---|---|---|---|---|
| 1 | 4 | applied | zotero_already_complete | ❌ |
| 2 | 5 | applied | zotero_already_complete | ❌ |
| 14 | 12 | applied | zotero_already_complete | ❌ |
| 15 | 13 | applied | zotero_already_complete | ❌ |
| 18 | 16 | applied | zotero_already_complete | ❌ |
| 23 | 21 | applied | zotero_already_complete | ❌ |
| **9** | **9** | **applied** | — | **✅ (force)** |

6 noop + 1 real write. 021에서의 "7편 전부 local-only drift" → 오늘 "1편만 실제로 Zotero에 반영할 게 있었음"으로 정정. 나머지 6편은 **파서 버그가 만든 false positive**였다는 게 backfill 후 드러남.

## 배운 점

### "local이 source of truth"와 "local이 derivative"의 차이

021에서 local에 직접 쓰는 apply()를 만들 때, "Paper는 local 테이블"이라는 사실과 "Paper는 Zotero의 mirror"라는 사실이 머릿속에서 같은 것처럼 보였다. 둘은 다르다.

- source of truth가 local이면: 쓰고 끝. sync는 다른 쪽의 책임.
- source of truth가 원격이면: 원격에 먼저 쓰고, local은 그 결과를 반영. sync는 쓰기의 일부.

이 구분이 P08 §3.5에 명시되기 전에는 "이건 단방향이니까 양방향 sync보다 쉽겠지" 같은 막연한 감각만 있었고, 실제로 구현 시 구조를 뒤집어야 한다는 걸 드리프트가 발생해서야 알아챘다. 문서에 명시적 규칙으로 남기는 것과 감각만 있는 것의 차이가 오늘의 수업.

### mirror layer는 상류 버그를 감춘다

파서 버그가 1년 이상 (거의 모든 Zotero sync 세션 동안) 발견되지 않은 이유는 "year가 비어있어도 UI가 깨지지 않는다"는 우아한 degradation이 있었기 때문. 비어있는 year 칸이 UI에 `--`로 표시되고, 사용자는 "아, 이 Paper는 원래 연도가 없나 보다" 하고 넘어간다. mirror의 빈 slot은 상류의 빈 값과 구별되지 않는다.

발견은 엉뚱한 경로에서 일어났다: pyzotero API signature를 probe하다가 `data.date='08/2017'`을 눈으로 봤고, 그 순간 "어 Zotero에 있는데 local엔 왜 없지?"라는 의문이 생겼다. **상류를 직접 보지 않으면 mirror의 false null은 영원히 숨을 수 있다.** 다음에 유사 mirror 레이어를 둘 때는 "mirror와 상류의 필드-단위 정합성 체크" 스크립트를 마일스톤에 박아둘 만함.

### Zotero 서버 파싱을 신뢰해도 됨

`meta.parsedDate`는 Zotero 서버가 `data.date`를 normalize한 결과고, 형식이 `YYYY` 또는 `YYYY-MM-DD`로 안정적. 로컬에서 regex를 다시 짜는 것보다 훨씬 견고하고, `"December 2018"` 같은 영어 자연어도 Zotero는 `"2018"`로 정규화해 준다. 5편 샘플에서 전부 제공되었고, 없는 케이스가 있다면 그때만 fallback regex를 쓰면 된다.

원칙: **상류 서비스가 이미 제공하는 정규화 필드를 먼저 찾아본다.** 재구현하기 전에.

### Case A no-op은 작업을 "없던 일"로 만들지 않는다

paper 4~21의 6편은 실제 API write가 한 번도 일어나지 않았다. 하지만 biblio.status는 `applied`로 바뀌었다. 이건 버그가 아니라 **"이 biblio는 사용자가 확인했고 더 이상 후속 검토가 필요 없다"는 상태 표현**.

이게 가능한 이유는 `review_reason` 필드로 **어떻게 applied 됐는지** 구분할 수 있기 때문. `zotero_already_complete`은 "Zotero가 이미 해당 정보를 가지고 있어서 실제 write 없이 확인만 됨"을 뜻한다. 나중에 감사를 할 때 "실제 Zotero write가 있었던 biblio는 몇 개?" 같은 쿼리가 `WHERE status='applied' AND review_reason=''`로 떨어진다.

상태 필드 하나에 "무엇이 일어났는가"까지 억지로 담으려 하면 상태 가짓수가 폭발한다. reason 필드를 slot으로 두면 상태는 소수로 유지된다.

### force_override는 정책의 탈출구, 기본 경로 아님

`curated_author_shortfall` 규칙은 "curated data가 망가졌음을 감지"하는 데 의미가 있지만, 감지만 하고 해결할 수단이 없으면 반쪽 기능이다. `--force`는 그 해결 수단이고, "사용자가 명시적으로 curated data를 불신한다"는 선언이다.

기본값은 `False`. batch reflect는 절대 force하지 않음. 이 비대칭이 중요한 이유: **automation이 curated data를 덮어쓰는 경로는 있으면 안 된다**. 사람만이 그 결정을 내릴 수 있다.

## P07/P08 반영

### P08 §3.5 추가 (같은 세션, 파일 edit됨)

- §3.5.1 원칙: Zotero가 유일한 source of truth
- §3.5.2 apply() 경로 분기 (zotero_key 유무)
- §3.5.3 Zotero write-back 구현 요구사항 (version concurrency, creator schema, date field, rate limit, 에러 처리)
- §3.5.4 오늘 드리프트 이슈 기록
- §8 미정 리스트의 "write-back은 별도 문서로" bullet을 "§3.5로 흡수됨"으로 해결 표시

### P07 매트릭스 갱신 대상 (다음 세션)

- line 57 `PaperBiblio → Paper 반영 정책`: ❌ → ✅ (P08 + §3.5 + §4.2.1)
- line 58 `high-confidence auto-commit 러너`: ❌ → ✅
- Phase 2 완료 기준의 "high-confidence 값 Paper 일괄 반영": ✅
- **새 항목 추가**: Zotero write-back ✅ (`papermeister/zotero_writeback.py`)
- **새 항목 추가**: `Paper.date` 컬럼 (아키텍처 레벨의 작은 개선)

## 남은 숙제 / 다음 세션 후보

- **desktop Apply Biblio 버튼 실제 GUI 검증** — 백엔드는 end-to-end 검증됨. `python -m desktop` 띄우고 클릭까지 확인.
- **desktop `list_by_library('needs_review')` 쿼리 fix** — Phase 2 잔여 1건.
- **Phase D: 대량 Haiku 추출** — OCR 완료 ~2,000편에 biblio 추출 → 여기서 drift 가능성이 다시 생길 거라 write-back 모듈의 진짜 batch 시험대.
- **Rate limiting in writeback** — batch 수천 건을 돌릴 때 Zotero rate limit handling 필요. 현재는 pyzotero의 자동 backoff에만 의존.
- **Writeback 실패 복구 경로** — 412 version conflict 시 auto-retry (fresh re-fetch 후 patch 재계산). 현재는 pyzotero가 알아서 raise함.

## 관련 문서

- [021 P08 반영 러너 검증 (오늘 전반)](./20260411_021_P08_Reflection_Runner_Verification.md) — drift를 만든 장본인
- [P08 §3.5 추가된 정책](./20260411_P08_PaperBiblio_Reflection_Policy.md)
- [019 새 데스크탑 앱 스캐폴드 + P08 러너 최초 작성](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md)
