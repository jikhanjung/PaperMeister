# P08: PaperBiblio → Paper 반영 정책

## 문서 역할

[P07](./20260410_P07_Desktop_Software_Implementation_Plan.md) Phase 2의 **선행 조건 정책 문서**.

다음을 정한다.

- 어떤 조건에서 PaperBiblio 값을 Paper에 자동 반영하는가
- 여러 PaperBiblio row가 있을 때 어떤 것을 선택하는가
- Paper에 이미 값이 있을 때 override 규칙은 어떻게 되는가
- auto-commit 대상이 아닌 건들을 review 큐로 어떻게 분류하는가

구현은 Phase 2의 `papermeister/biblio_reflect.py` + `scripts/reflect_biblio.py`에서 이 문서를 따른다.

## 배경: Paper 정체성 비대칭

[P07 "Paper 정체성 비대칭" 섹션 참고](./20260410_P07_Desktop_Software_Implementation_Plan.md)

- **Zotero import**: Paper는 처음부터 API 기반 curated 상태 → PaperBiblio는 override용
- **Filesystem import**: Paper는 stub (`title = filename stem`) → PaperBiblio는 채움용

정책은 두 경우를 모두 포괄해야 한다.

## 전제

- `PaperBiblio.status` 컬럼을 신설한다 (extracted / needs_review / auto_committed / applied / rejected)
- 본 정책은 row-level이며, 한 Paper에 여러 PaperBiblio가 달릴 수 있다 (서로 다른 model/version)
- 본 정책은 **비파괴**를 유지한다. Paper 업데이트는 있어도, PaperBiblio는 수정/삭제하지 않는다.

## 1. PaperBiblio 선택 규칙 (여러 row 중 하나 고르기)

한 Paper에 여러 추출 결과가 있을 때 우선순위:

1. `status = applied` (사용자가 직접 승인한 것이 있으면 그게 최우선 — 단, 이 row는 이미 반영되어 있으므로 재반영 대상 아님)
2. `source = llm-sonnet-vision` > `llm-haiku-vision` > `llm-sonnet` > `llm-haiku` > `llm-*-baseline`
3. `confidence = high` > `medium` > `low`
4. `extracted_at` 최신

이 순서로 **tie-break**한다. vision pass는 CJK/표지 케이스에서 텍스트 패스보다 신뢰하므로 source가 confidence보다 먼저 온다.

구현: `biblio_reflect.select_best_biblio(paper_id) -> PaperBiblio | None`

## 2. Auto-commit 조건

선택된 PaperBiblio가 Paper에 **자동 반영**되려면 모두 만족해야 한다.

### 2.1 필수 필드 존재

- `title` 비어 있지 않음
- `authors_json` 길이 ≥ 1 (파싱 시 유효한 이름 하나 이상)
- `year` not null **또는** `doc_type in ('book', 'chapter', 'report')` — 단행본은 연도 누락 허용

### 2.2 confidence / doc_type

- `confidence = high`
- `doc_type != 'unknown'`
- `needs_visual_review = false`
- `doc_type != 'journal_issue'` — journal issue는 표지 스캔이라 파일 단위 논문이 아님. promote 플로우로 보낸다.

### 2.3 Paper 현재 상태

- `Paper`가 **stub** (P07 정의) — 자유롭게 override
- **또는** `Paper`가 curated인데 doi/zotero_key로 확실히 같은 work이고 override policy가 허용 (아래 4절)

위 조건 중 하나라도 실패하면 auto-commit 대상이 아니다. `status = needs_review`로 분류.

## 3. 반영 필드 매핑

PaperBiblio → Paper 매핑 (auto-commit 시):

| PaperBiblio 필드 | Paper 필드 | 처리 |
|------------------|-----------|------|
| `title` | `title` | 그대로 |
| `authors_json` | `Author` 테이블 전량 교체 | `order` = JSON 인덱스 |
| `year` | `year` | null이면 기존 유지 |
| `journal` | `journal` | 그대로 (빈 문자열이면 기존 유지) |
| `doi` | `doi` | 그대로 |
| `doc_type` | 반영 안 함 | Paper에 컬럼 없음, PaperBiblio에서만 조회 |
| `abstract` | 반영 안 함 | MVP에서 Paper.abstract 없음 |
| `language` | 반영 안 함 | 동일 |

반영 후 `PaperBiblio.status = auto_committed`로 업데이트 (row 자체는 수정하지 않고 status만).

## 3.5 Write path: Zotero-sourced vs filesystem-sourced

§3의 "매핑"이 **어디에 쓰는가**는 Paper의 출처에 따라 다르다. 이 구분이 빠지면 local SQLite와 Zotero 서버 사이에 드리프트가 생긴다.

### 3.5.1 원칙: Zotero가 유일한 source of truth

- Zotero-sourced Paper (`Paper.zotero_key`가 비어 있지 않음)는 local DB가 **derivative**다. 언제든 Zotero에서 재생성 가능한 mirror로 취급한다.
- 쓰기 방향은 **한 방향**: `PaperBiblio → Zotero API → Zotero 서버 → (pull) → local Paper`. 양방향 sync는 충돌 해결 로직이 필요해 본 MVP의 목표가 아니다.
- filesystem-sourced stub Paper는 Zotero가 없으므로 local 직접 write. promote 이후에는 Zotero-sourced로 승격되어 이 분기의 Zotero 경로를 탄다.

### 3.5.2 apply() 경로 분기

```
if paper.zotero_key:
    # Zotero-sourced: 한 방향 sync
    updated_item = zotero_writeback(biblio, paper)   # API write, fail → raise
    refresh_paper_from_zotero_item(paper, updated_item['data'])  # inline pull
else:
    # filesystem-sourced (현재 DB에서는 0건, standalone 경로 전용)
    _local_apply(biblio, paper)
```

- API write 실패 시 local은 일절 건드리지 않는다 (network-atomic).
- 성공 시 pyzotero 응답에 들어온 최신 item data를 사용해 local Paper/Author를 갱신한다. 별도 re-fetch 없음.
- 두 경로 모두 마지막에 `PaperBiblio.status`를 `auto_committed`/`applied`로 바꾸고, 이 상태 변경은 write 경로와 무관하게 항상 local-only.

### 3.5.3 Zotero write-back 구현이 다루어야 할 것

다음은 P08의 정책 범위 밖이지만 `papermeister/zotero_writeback.py`가 지켜야 한다.

- **Version concurrency**: update 직전에 item을 fresh fetch해서 `version`을 받고, 그 version으로 update한다. stale mirror로 쏘면 409.
- **Creator schema**: biblio의 full-name string을 Zotero creator 배열로 변환. first/last 분리는 위험하므로 MVP에서는 `{"creatorType": "author", "name": ...}` 단일 필드 사용. Zotero UI에서 정상 표시됨.
- **Date 필드**: biblio.year → Zotero `date` 필드 (문자열, "2017" 같은 연도-only 허용됨).
- **DOI 대문자**: Zotero 필드명은 `DOI` (대문자).
- **Rate limit**: pyzotero는 기본 무제한 호출. batch 수천 건은 throttle 필요하지만 MVP 후순위.
- **실패 시 로깅**: 어떤 paper가 어떤 reason으로 실패했는지 호출자에게 raise로 돌려준다.

### 3.5.4 오늘(2026-04-11) 드리프트 이슈

이 §3.5가 추가되기 전, `biblio_reflect.apply()`는 무조건 local만 썼다. 그 결과 2026-04-11 세션에서 paper 4/5/9/12/13/16/21 총 7편이 **local에서만 수정되고 Zotero 서버는 그대로**인 드리프트 상태를 만들었다. `resync_zotero.py`가 돌면 해당 변경이 전부 revert될 위험이 있어 같은 세션에서 pull-back으로 되돌린 뒤, 이 §3.5 정책을 따라 재구현했다.

교훈: "local에 먼저 쓰고 나중에 sync"는 직관적이지만 derivative 관계를 뒤집는 함정이다. Zotero-sourced Paper에 대해서는 Zotero write가 **선행 조건**이지 후속 작업이 아니다.

## 4. Override 정책 (Paper가 이미 curated인 경우)

### 4.1 기본 원칙: conservative

curated Paper는 **덮어쓰지 않는다**. Zotero에서 온 값은 사용자가 의도적으로 넣은 것으로 간주.

### 4.2 예외: 명시적으로 더 나은 소스

다음 조건이 모두 만족되면 **필드 단위로** override 허용:

- 해당 필드가 Paper에서 비어 있음 (title='', year is null, Author 없음 등)
- PaperBiblio의 해당 필드가 비어 있지 않음
- confidence = high

즉, **빈 슬롯 채우기만** auto. 비어 있지 않은 값 교체는 항상 manual review.

### 4.2.1 Author count shortfall (curated 신뢰 깨짐 감지)

curated Paper의 author 수가 biblio의 author 수보다 **엄격히 적으면** (`len(P.authors) > 0 AND len(B.authors) > len(P.authors)`) auto-commit을 전면 중단하고 `needs_review`로 분류한다.

이유: curated 데이터가 불완전하다는 강한 신호. 빈 슬롯 채우기 규칙만으로는 journal/doi 같은 다른 필드만 채워지고 author 목록은 부분 상태로 남아 반쯤 업데이트된 Paper를 만들게 된다. 전체 상태를 사람에게 넘기는 편이 안전.

역방향(P.authors 수 > B.authors 수)은 단순히 biblio 추출이 나쁜 것이므로 기존 empty-slot 규칙대로 author는 건드리지 않고 진행.

### 4.3 DOI 기반 강제 override

추출된 DOI와 Paper.doi가 일치하고 confidence=high인 경우, 나머지 필드도 덮어쓴다.
**단, MVP에서는 이 경로를 꺼둔다** (설정으로 opt-in). 이유: DOI 인식 자체의 false positive가 있을 수 있음.

## 5. needs_review 분류 규칙

auto-commit 실패 사유를 구체화한다. review queue에서 필터링에 쓴다.

| 실패 사유 코드 | 조건 |
|---------------|------|
| `low_confidence` | `confidence != high` |
| `visual_review_flag` | `needs_visual_review = true` |
| `missing_title` | `title == ''` |
| `missing_authors` | authors 비어 있음 |
| `missing_year` | `year is null` AND doc_type가 허용 예외 아님 |
| `unknown_doctype` | `doc_type in ('unknown', '')` |
| `journal_issue` | `doc_type = 'journal_issue'` (promote 플로우로 이관) |
| `override_conflict` | Paper가 curated이고 빈 슬롯만으로 채울 수 없음 |
| `curated_author_shortfall` | Paper가 curated인데 author 수가 biblio보다 적음 (§4.2.1) |

구현: `biblio_reflect.evaluate(biblio, paper) -> Decision` 에서 반환.
`Decision`은 `auto_commit | needs_review(reason) | skip(reason)`.

## 6. 실행 모델

### 6.1 함수 시그니처 (초안)

```python
# papermeister/biblio_reflect.py

@dataclass
class Decision:
    action: Literal['auto_commit', 'needs_review', 'skip']
    reason: str = ''
    target_biblio_id: int | None = None

def select_best_biblio(paper: Paper) -> PaperBiblio | None: ...

def evaluate(biblio: PaperBiblio, paper: Paper) -> Decision: ...

def apply(biblio: PaperBiblio, paper: Paper, *, dry_run: bool = False) -> bool:
    """Apply biblio to paper per this policy. Returns True if changes made."""
    ...

def reflect_all(
    *,
    source_id: int | None = None,
    folder_id: int | None = None,
    dry_run: bool = False,
) -> ReflectStats:
    """Iterate papers in scope, apply decisions."""
    ...
```

### 6.2 Batch runner

`scripts/reflect_biblio.py`:

```bash
# Dry-run: show what would be applied
python scripts/reflect_biblio.py --source 3 --dry-run

# Apply
python scripts/reflect_biblio.py --source 3

# Single paper (for GUI "Apply Biblio" button)
python scripts/reflect_biblio.py --paper 1234
```

GUI의 "Apply Biblio" 버튼은 `apply(biblio, paper, dry_run=False)`를 single-paper로 호출.

### 6.3 멱등성

- `PaperBiblio.status = auto_committed` 이후에는 같은 row가 다시 선택되지 않음
- 같은 Paper에 새 PaperBiblio가 생기면 다시 평가 가능
- Paper 업데이트는 트랜잭션, 실패 시 전체 롤백

## 7. UI와의 인터랙션

### 7.1 한 건 반영 (detail panel)

- 우측 detail panel에서 Paper vs 최신 PaperBiblio diff 표시
- "Apply Biblio" 버튼:
  - Decision이 `auto_commit`이면 즉시 실행
  - `needs_review`면 reason을 툴팁에 표시하되 버튼은 활성 (manual override)
  - `skip`이면 버튼 disabled + 이유 표시

### 7.2 일괄 반영 (source/folder)

- source tree 오른쪽 클릭 → "Reflect Biblio (dry-run)"
- 결과 다이얼로그: auto_commit N건, needs_review M건, skip K건
- "Apply" 클릭 시 트랜잭션으로 일괄 실행

### 7.3 Review queue

- Library의 "Needs Review" 폴더는 `PaperBiblio.status = needs_review` + stub Paper 조합
- reason별 그룹 표시 (missing_title, low_confidence 등)

## 8. 미정 / 뒤로 미루는 것

- 여러 Paper 병합 (DOI-based dedup) — Phase 6+
- user edit 흐름에서 edit 값을 PaperBiblio로 저장할지 Paper에 직접 쓸지 — Phase 6 review queue 설계 시
- ~~Paper → Zotero write-back 시 applied PaperBiblio 추적~~ → §3.5로 흡수됨 (2026-04-11). write-back은 apply()의 필수 경로이며 별도 문서로 분리하지 않는다.

## 9. 결론

P08의 핵심은 두 가지 판단이다.

1. **Auto-commit은 high-confidence + 필수 필드 + stub Paper일 때만** — 나머지는 전부 review 큐로
2. **curated Paper는 빈 슬롯 채우기만 허용** — 적극적 override는 Phase 6의 수동 승인 흐름으로

이 두 가지가 정해지면 Phase 2 러너 구현과 Phase 4 "Apply Biblio" 버튼이 모두 결정론적으로 동작할 수 있다.
