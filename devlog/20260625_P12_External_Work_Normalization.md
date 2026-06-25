# P11 Phase 2 — External Work Normalization (CitedWork 노드)

> 계획 문서. P11 Phase 1(`20260625_P11_References_Extraction_Citation_Network.md`)의 후속.
> Phase 1은 `Reference`(엣지)와 보유 논문(`Paper`) 해소까지 완료. 이 문서는 **외부(cited-only)
> 문헌에 canonical 노드를 부여**해서 진짜 citation network를 완성하는 설계.

## 1. 문제 (Phase 1의 비대칭)

Phase 1에서 `Reference` 한 행 = "X가 Z를 인용한다"는 **엣지**다.

- 보유 논문 Z → `Reference.resolved_paper`로 해소됨. `Paper` 테이블이 canonical **노드** 역할.
- 외부 문헌 Z(우리가 PDF를 안 가진) → `resolved_paper`가 null. **canonical 노드가 없음.**

결과적으로 같은 외부 논문 Z를 W와 X가 둘 다 인용하면 **서로 다른 두 Reference 행으로 흩어진다.**
- "Z를 인용한 우리 논문이 몇 편?" → title/DOI로 매번 group-by 해야 함
- co-citation("우리 라이브러리에서 자주 같이 인용되는 외부 논문") 질의 불가
- "우리가 자주 인용하지만 아직 보유하지 않은 논문 top-N"(수집 후보 발굴) 불가

## 2. 설계 결정

### 결정 1 — 통합 `Work` 테이블이 아니라 외부 전용 `CitedWork` 테이블

두 가지 안:
- **(2A) 통합 Work 테이블**: 보유+외부 모든 노드를 Work에 담고 Paper와 1:1 링크. 그래프상 가장
  "정석"이지만, 기존 Paper/Author/PaperBiblio를 Work로 미러링·동기화하는 부담이 큼. 모든 기존
  쿼리가 Work를 거쳐야 함.
- **(2B, 채택) 외부 전용 CitedWork**: 보유 논문은 이미 권위 있는 노드(Paper)가 있으니 **없는 것만
  추가**한다. 외부 문헌만 CitedWork에 정규화. "통일된 노드 뷰"는 물리적 병합 대신
  `Paper ∪ CitedWork` **뷰/얇은 API**로 제공.

→ 프로젝트 철학("store first, understand later", PaperBiblio식 비파괴 파생 레이어, 점진적 추가)에
   부합하는 **(2B)** 채택. 보유 논문이 권위(authoritative), 외부는 파생.

### 결정 2 — `Reference.resolved_work` FK 추가

각 Reference의 해소 결과는 정확히 셋 중 하나:

| 상태 | resolved_paper | resolved_work | 의미 |
|------|----------------|---------------|------|
| held | set            | null          | 보유 논문 (in library) |
| external | null        | set           | 외부 canonical 노드 |
| junk | null            | null          | 파싱 불가/문헌 아님 (type=unknown & title·doi 둘다 없음) |

**불변식: resolved_paper와 resolved_work를 동시에 set 하지 않는다.** 보유가 우선(authoritative).

### 결정 3 — dedup: exact는 deterministic 자동 수락, 나머지는 **LLM 판정** (fuzzy는 후보 생성 전용)

dedup/resolve 품질이 이 설계의 전부다. OCR 변이("같은 논문인가?")는 fuzzy 임계값보다 LLM이
훨씬 신뢰성 있게 판단한다. 단, ref마다 기존 work 전체와 LLM 비교 = 수백만 호출(폭발)이므로
**fuzzy는 결정에서 빼고 "값싼 후보 추리기(recall)"로만 쓰고, LLM이 최종 판정(precision)** 한다.

3단 계층:
1. **DOI exact** — well-formed(`^10\.\d{4,9}/`)만 신뢰. 일치 → 즉시 병합. (LLM 없음)
2. **title_key exact** — 정규화 지문(소문자화, CJK 유지, 스톱워드 제거, 토큰 정렬 후 join) +year
   일치 → 즉시 병합. (LLM 없음)
3. **그 외(exact 안 됨)** — fuzzy/blocking이 후보 3~5개만 추려 **LLM에게 판정 위임**:
   "이 항목들 중 같은 논문은? 묶어줘 / 다 다름". 후보가 0개면 LLM 없이 새 노드.

> fuzzy(`_score_title`: 토큰 containment + year + 제1저자 surname)는 **결정을 하지 않는다.**
> LLM에 보여줄 후보를 고르고 순위만 매긴다. `title_key`도 버리지 않고 **blocking 키**로 쓴다.

**under-merge > over-merge** 원칙은 유지: 애매하면 LLM이 "다름"으로 가도록 프롬프트를 보수적으로.
중복 노드는 후속 merge 툴로 합치면 되지만, 오병합은 두 논문 정체성을 영구히 섞어 복구가 어렵다.

### 결정 4 — 2-패스: exact dedup(빠름) → LLM 병합(충돌 클러스터에만)

LLM을 ref마다 inline으로 돌리지 않는다. **충돌이 실제로 생긴 클러스터에만** 돌려 호출 수를
"ref 수"가 아니라 "잠재 중복 클러스터 수"에 비례시킨다.

**패스 1 — exact dedup (deterministic, LLM 없음, 빠름)**
보유 논문 resolve(기존 `resolve_one`: DOI/title score) 실패 시 외부로 canonicalize:
- DOI exact 일치하는 CitedWork → 링크 (`work-doi`)
- title_key(+year) exact 일치 → 링크 (`work-title`)
- 둘 다 없으면 → 일단 **새 CitedWork 생성** (`work-new`) — OCR 변이로 갈라진 중복은 이 시점엔
  별개 노드로 남는다(의도된 상태)
- junk(title·doi 둘다 없음) → 둘 다 null (`none`)

in-memory 인덱스(doi→work_id, title_key→work_id)에 **배치 중 새로 만든 work도 즉시 반영**해
같은 배치 내 후속 ref의 중복 생성 방지. CitedWork 생성은 **메인/DB 스레드**(워커는 LLM 전용).

**패스 2 — LLM 병합 (충돌 클러스터에만)**
- CitedWork를 **blocking 키로 그룹핑**: `(제1저자 surname, year)` 또는 제목 토큰 겹침
- **후보 ≥2개인 그룹에만** LLM 질의 → 같은 work끼리 병합. 노드 하나뿐(대부분)인 그룹은 **LLM 0회**
- 한 프롬프트에 클러스터 여러 개 묶고 `--workers`로 병렬(서버가 concurrent 배치) — 추출 패턴 그대로

**LLM 판정 영속화(필수)** — `match_method='work-llm'` + 점수/판정을 저장. 재실행 시 이미 판정된
건 재질의 안 함 → **idempotent·resumable** (LLM은 비결정적이라 이게 없으면 재실행마다 결과 흔들림).

> **확장(선택, 후속)**: 패스 2의 후보군에 보유 `Paper` + 기존 `CitedWork`를 함께 넣으면
> resolve(ref↔보유)와 dedup(ref↔외부)이 **하나의 LLM 판정기**로 통합된다. 범위가 커지니 외부
> dedup부터 검증 후 확장한다.

### 결정 5 — 보유 논문 획득 시 promotion (reconcile)

나중에 외부 CitedWork와 동일한 논문을 import하면:
- 그 work의 incoming Reference들을 `resolved_paper`로 repoint, `resolved_work` 클리어
- `CitedWork.merged_into_paper` 설정(tombstone로 남겨 과거 링크 추적 가능, 노드 뷰에서 제외)

Phase 2 초기엔 배치 reconcile 스크립트로 충분. 추후 import 훅에 연결.

### 결정 6 — `cite_count` 비정규화

CitedWork에 "우리 라이브러리에서 이 work를 인용한 distinct 논문 수"를 저장(재계산 가능).
top-cited 외부 논문 질의를 싸게. resolve/reconcile/backfill 시 갱신.

## 3. 스키마

```python
class CitedWork(BaseModel):
    """A canonical external work — cited by ≥1 of our papers but NOT held.
    Derived/normalized layer over Reference rows; rebuildable from them."""
    # canonical identity
    doi           = peewee.TextField(default='')      # normalized; indexed
    title         = peewee.TextField(default='')      # representative
    title_key     = peewee.TextField(default='')      # normalized fingerprint; indexed
    year          = peewee.IntegerField(null=True)
    authors_json  = peewee.TextField(default='[]')
    container     = peewee.TextField(default='')
    first_surname = peewee.TextField(default='')
    # denormalized
    cite_count    = peewee.IntegerField(default=0)    # distinct citing held papers
    # lifecycle
    merged_into_paper = peewee.ForeignKeyField(
        Paper, null=True, backref='absorbed_works', on_delete='SET NULL')
    created_at    = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        indexes = ((('title_key', 'year'), False), (('doi',), False))
```

`Reference`에 추가:

```python
    resolved_work = peewee.ForeignKeyField(
        CitedWork, null=True, backref='citations', on_delete='SET NULL')
    # match_method 확장: '' | 'doi' | 'title'                       (→ 보유 Paper)
    #                    | 'work-doi' | 'work-title' | 'work-new'    (패스1 exact/신규 → CitedWork)
    #                    | 'work-llm'                                (패스2 LLM 병합 판정)
    #                    | 'none'                                    (junk)
```

**representative 메타데이터**: 한 work에 여러 Reference가 매핑될 때 필드가 다르면 "더 나은" 것으로
갱신 — DOI 있음 > parse_confidence 높음 > title 더 김.

## 4. 코드 변경

| 파일 | 변경 |
|------|------|
| `papermeister/models.py` | `CitedWork` 모델, `Reference.resolved_work` FK |
| `papermeister/database.py` | `ALL_TABLES`에 `CitedWork`(자동 생성); `_migrate`에 `reference.resolved_work_id` 컬럼 + 인덱스 추가 |
| `papermeister/references.py` | **패스1**: `work_title_key()`, `build_work_index()`(또는 기존 index 확장), `canonicalize_reference()`(exact dedup), `resolve_one`/`resolve_paper_references` 확장. **패스2**: `cluster_works_by_block()`, `llm_merge_clusters()`(LLM 판정 + 영속화), `merge_works(keep, dups)`. 공용: `recompute_cite_counts()`, `reconcile_works_with_papers()` |
| `papermeister/biblio.py` | 패스2용 LLM 병합 프롬프트(`_call_qwen` 재사용, "후보 중 동일 work 묶기/다름" JSON 응답) |
| `scripts/normalize_works.py` (신규) | 백필: 패스1(exact canonicalize) → 패스2(LLM 병합, `--workers`, 영속화로 resumable) → cite_count 재계산 → reconcile (`--execute`) |
| `scripts/extract_references.py` | 추출 직후 auto-resolve 패스에 **canonicalize 단계 추가**(공유 인덱스에 새 work 누적) |
| `desktop/.../main_window.py` | `_run_references_extraction_silent`의 auto-resolve를 canonicalize까지 확장 |
| `desktop/services/paper_service.py` | 노드 API: `load_work(work_id)`, `load_work_citations(work_id)`(공동 인용 논문), `top_cited_works(limit)` |
| `desktop/views/detail_panel.py` (선택) | 외부 카드 클릭 → "라이브러리 내 N편이 함께 인용" 표시 |

## 5. 통일 노드 뷰 (uniformity)

(2B)에서도 "모든 work를 한 종류 노드로" 보는 경험은 뷰/API로 제공:

```sql
-- 선택: SQL 뷰 (peewee create_tables 비관리 → _migrate에서 raw로 생성, 또는 Python에서 계산)
CREATE VIEW citation_node AS
  SELECT 'paper' AS kind, id, title, year FROM paper      WHERE trashed_at IS NULL
  UNION ALL
  SELECT 'work'  AS kind, id, title, year FROM citedwork  WHERE merged_into_paper_id IS NULL;
```

그래프 질의:
- **out-edges(논문 X)**: `Reference(citing=X)` → 타깃 = `resolved_paper`(paper 노드) / `resolved_work`(work 노드) / dangling
- **in-edges(보유 X) = cited-by**: `Reference(resolved_paper=X)` — 기존 `load_cited_by`
- **in-edges(외부 W)**: `Reference(resolved_work=W)` → W를 인용한 보유 논문들(co-citation 집합)

마이그레이션 단순화를 위해 초기엔 **Python 계산** 권장, SQL 뷰는 선택.

## 6. 백필 / 마이그레이션

- 비파괴·additive. `resolved_work` nullable. `CitedWork`는 신규 테이블(자동 생성).
- `scripts/normalize_works.py --execute` 재실행 가능(idempotent): canonicalize는 doi/title_key
  키 기반, cite_count는 매번 0에서 재계산.
- 규모(9823 papers, Reference ~수십만~백만 행): `build_work_index`는 CitedWork의 doi_map/
  title_key_map만 메모리 적재(수십만 행 × 소형 OK). 백필은 chunk 순회 + `insert_many` 배치.
  cite_count는 `GROUP BY resolved_work`로 일괄.

## 7. UI (Phase 2 범위 — 선택/후속)

- References 탭 외부 카드: 클릭 시 "라이브러리 내 N편이 함께 인용"(co-citation, `resolved_work.citations`)
- 신규 발굴 화면: **Top cited external works**(`CitedWork` cite_count desc) — "자주 인용하지만 미보유"
  논문 = 수집 후보. 보유 promotion 워크플로와 연결 가능.
- 계획상 UI는 최소로, 발굴 화면은 후속(2.1)로 분리.

## 8. 리스크 / 엣지케이스

- **OCR 제목 변이** → 패스1 exact는 못 잡고 별개 노드로 남음 → **패스2 LLM 병합**이 정리. LLM도
  애매하면 "다름"으로(under-merge > over-merge). 남는 중복은 보조 merge 툴(2.1).
- **LLM 비결정성** → 판정 영속화(`work-llm`)로 idempotent. 재실행 시 미판정 클러스터만 질의.
- **패스2 비용** → blocking으로 후보 ≥2 클러스터에만 호출, 클러스터 묶음 배치 + workers 병렬.
  9823 papers 백필은 시간 소요 → Windows Anaconda에서 resumable하게(`--execute`, Ctrl-C 안전).
- **OCR DOI 오염** → 오병합 위험. well-formed DOI(`10.\d{4,9}/…`)만 신뢰.
- **year 결측** → title_key 단독. 동명 다른 연도 병합 위험(허용, 명시).
- **representative 갱신** 규칙: DOI > confidence > 더 긴 title.
- **promotion tombstone**: merged_into_paper 설정 후에도 row 유지(과거 resolved_work 추적), 노드 뷰 제외.
- **현재 논문/self-citation 무관**: 보유 논문은 절대 CitedWork가 되지 않음(외부 전용).

## 9. 단계

1. 스키마(`CitedWork` + `resolved_work`) + 마이그레이션
2. `references.py` 패스1(exact canonicalize/index) + `recompute_cite_counts`/`reconcile` + 단위 동작 확인
3. 패스2 LLM 병합(`cluster_works_by_block` + `llm_merge_clusters` + 영속화) + 병합 프롬프트
4. `scripts/normalize_works.py` 백필 — 패스1→패스2 (Windows Anaconda, `--execute`, resumable)
5. 추출 파이프라인(CLI+desktop) auto-canonicalize(패스1) 연결, 패스2는 주기적/수동 배치
6. (선택) desktop 노드 API + 외부 카드 co-citation, Top-cited 화면

## 10. 구현

구현 기록(파일·동작·검증·실행 절차)은 별도 문서로 분리:
**[20260625_064 External Work Normalization Implementation](./20260625_064_External_Work_Normalization_Implementation.md)**.
