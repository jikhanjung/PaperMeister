# P07: 데스크탑 소프트웨어 구현 계획

## 문서 역할

이 문서는 데스크탑 앱의 **구현 계획 문서**다.

즉, 다음을 다룬다.

- `P06`에서 정의한 기능을 어떤 순서로 만들 것인가
- 어떤 레이어와 단계로 나눌 것인가
- 각 단계의 완료 기준은 무엇인가
- 지금 바로 어떤 작업부터 시작해야 하는가

기능 범위와 정책 자체는 `P06`을 기준으로 한다.

## 전제

이 계획은 다음 판단을 전제로 한다.

- searchable corpus는 OCR만으로 충분하지 않다.
- 서지정보는 corpus usability의 핵심 레이어다.
- source provenance를 유지한 UI가 현재 데이터 모델에 더 정직하다.
- vision pass, standalone promote, Zotero write-back은 중요하지만 정책 제어가 필요한 자동화 레이어다.

## 개정 이력

- **2026-04-10**: 초안 작성
- **2026-04-11**: 검토 반영
  - "현재 구현 상태" 섹션 추가 — 이미 돌아가는 코드와 실제 갭 분리
  - 상태 모델을 flat list → `entity × state machine` 매트릭스로 재정리
  - Phase 4(Search)와 Phase 5(Review/Automation) 경계 재검토: high-confidence biblio auto-commit을 Search 앞으로 당김
  - `PaperBiblio → Paper` 반영 정책은 [P08](./20260411_P08_PaperBiblio_Reflection_Policy.md)로 분리
  - 새 GUI 앱의 UI 설계는 [P09](./20260411_P09_New_Desktop_UI_Design.md)로 분리
  - 기존 `papermeister/ui/`는 동결, 새 앱을 별도 패키지로 구현

## 현재 구현 상태 (2026-04-11 기준, 세션 10 갱신)

구현 계획을 실행 가능한 것으로 만들기 위해, 이미 존재하는 자산을 먼저 식별한다.

| 영역 | 상태 | 관련 파일/경로 |
|------|------|----------------|
| Local directory source 스캔 | ✅ 완료 | `papermeister/ingestion.py::import_source_directory` |
| Zotero source / 컬렉션 동기화 | ✅ 완료 | `papermeister/ingestion.py`, `papermeister/zotero_client.py` |
| SHA256 dedup | ✅ 완료 | `ingestion.py` / `scripts/update_hashes.py` |
| OCR 실행 (RunPod serverless) | ✅ 완료 | `papermeister/ocr.py` |
| OCR 병렬 처리 | ✅ 완료 | ThreadPoolExecutor 기반 |
| OCR JSON 캐시 | ✅ 완료 | `~/.papermeister/ocr_json/{hash}.json` |
| `PaperFile.status` 상태 추적 | ✅ 완료 | pending/processed/failed |
| DB 자동 migration | ✅ 완료 | `papermeister/database.py::_migrate` |
| Batch OCR retry/resume | ✅ 완료 | `batch_ocr.py` (Pod 이미지) |
| FTS5 BM25 인덱싱 | ✅ 완료 | `passage_fts` (title×10, authors×5, text×1) |
| **Phase 1 완료 기준** | ✅ **대체로 충족** | 남은 건 "DB 삭제 후 복구 경로" 실증 테스트 |
| LLM 서지 추출 (Haiku 텍스트) | ✅ 완료 | `scripts/extract_biblio.py`, `papermeister/biblio.py` |
| Vision pass (Sonnet) | ✅ 완료 | `scripts/extract_biblio_vision.py` |
| PaperBiblio 저장 | ✅ 완료 | `papermeister/models.py::PaperBiblio` (`status`, `review_reason`, `needs_visual_review` 추가됨) |
| 평가 파이프라인 | ✅ 완료 | `biblio_eval.py`, `run_*eval.py` |
| `PaperBiblio → Paper` 반영 정책 | ✅ 완료 | [P08](./20260411_P08_PaperBiblio_Reflection_Policy.md) + §3.5 (write-back 경로) + §4.2.1 (`curated_author_shortfall`) |
| high-confidence auto-commit 러너 | ✅ 완료 | `papermeister/biblio_reflect.py`, `scripts/reflect_biblio.py` (devlog 021/022 검증) |
| Zotero write-back | ✅ 완료 | `papermeister/zotero_writeback.py` — fresh fetch → empty-slot patch against Zotero → update_item → re-fetch (network-atomic) |
| `Paper.date` 컬럼 | ✅ 완료 | Zotero `data.date` raw string (round-trip 무손실). `Paper.year`는 derived int index |
| Zotero 날짜 파서 버그 수정 | ✅ 완료 | `meta.parsedDate` 우선 사용 + regex fallback. backfill로 1,671편 year 복구 |
| Review 대상 식별 쿼리 | ✅ 완료 | `desktop/services/library.py::needs_review_paper_ids()` — count와 list가 이 헬퍼 공유 |
| standalone PDF promote | ✅ 스크립트 | `scripts/promote_standalone.py` (GUI 통합 ❌) |
| 3-pane GUI (기존) | 🟡 동결 | `papermeister/ui/main_window.py` — 신규 개발 중단 |
| 새 GUI (모던 디자인) | 🟡 스캐폴드 | `desktop/` 패키지, 3-pane + Library/Sources 이중 네비 + 상세 패널. Apply Biblio 버튼은 백엔드 연결됨 (GUI 클릭 실증은 미검증) |
| Library/Sources 이중 네비 | ✅ 완료 | `desktop/views/source_nav.py`, `desktop/services/library.py` |
| Search UI (filter/sort/snippet) | 🟡 부분 | 기존 앱에 검색 입력만. desktop 쪽은 상단 바만 있음 |
| Review queue UI | ❌ 없음 | Phase 5 |
| PDF viewer 최소 기능 | ❌ 없음 | MVP 보강 후보 (본 문서에서 승격) |

요약 (세션 10 기준): **Phase 1·2는 완료**, **Phase 3 스캐폴드 완료 + Phase 4 진행 중** (Apply Biblio 단일 경로 검증됨, batch Reflect UI / background worker / StatusBadge delegate / OCR 미리보기 미완), Phase 5~7 미착수.

## 구현 목표

`P06`의 기능 정의를 구현 가능한 순서로 분해해,
작동하는 데스크탑 앱을 단계적으로 완성한다.

## 구현 전략

### 1. Foundation first

- source 연결
- OCR 캐시
- 상태 모델
- DB 재구성 가능성

이 네 가지를 먼저 안정화한다.

### 2. Bibliographic usability early

서지정보 추출은 뒤로 미루지 않는다.
검색 가능한 corpus의 실질적 가치가 여기서 올라가기 때문이다.

### 3. UI는 source-first

canonical merge가 성숙하기 전까지는 source별 구조와 operational view를 같이 제공한다.

### 4. 자동화는 단계적으로

추출 저장은 먼저 넣고,
promote/write-back/vision은 통제 가능한 흐름으로 뒤에 붙인다.

## 구현 레이어

### Layer 1. Corpus Foundation

- source 등록
- source 스캔/동기화
- PDF hash 계산
- OCR 실행
- OCR JSON 캐시
- 처리 상태 추적

### Layer 2. Bibliographic Layer

- OCR JSON 기반 서지정보 추출
- `PaperBiblio` 저장
- confidence / doc_type / needs_visual_review 처리
- Paper 반영 규칙 정의

### Layer 3. UI Layer

- source-first navigation
- operational views
- paper list
- detail panel
- preferences
- process window

### Layer 4. Search Layer

- FTS5 BM25
- metadata + text 혼합 검색
- filters / sorting / snippet

### Layer 5. Controlled Automation Layer

- review queue
- vision pass
- standalone promote
- Zotero write-back

### Layer 6. Hardening Layer

- retry/resume/concurrency
- failure taxonomy
- backend switching
- encrypted PDF 대응
- 테스트 코드

## 단계별 계획

## Phase 1. Core Corpus Foundation ✅ (대체로 완료)

### 목표

source, OCR, 캐시, 상태 모델을 먼저 안정화한다.

### 상태

기존 `papermeister/` 패키지에 대부분 구현됨. 남은 작업:

- [ ] DB 재구성 경로 실증: DB 삭제 → source + OCR JSON으로 복구되는지 스크립트 확인
- [ ] migration 경로 회귀 테스트 (새 컬럼 추가 시)

### 완료 기준

- ~~source 추가 후 tree/list가 일관되게 생성된다~~ ✅
- ~~동일 PDF는 source와 무관하게 같은 OCR JSON을 재사용한다~~ ✅
- ~~pending/processed/failed 상태가 일관된다~~ ✅
- [ ] DB를 지워도 source와 OCR JSON으로 복구 가능하다 (미실증)

## Phase 2. Bibliographic Corpus Layer ✅ (완료)

### 목표

서지정보를 corpus의 기본 usability 레이어로 구현한다.

### 상태

- ✅ `papermeister/biblio.py` + `scripts/extract_biblio*.py` 로 추출 가능
- ✅ `PaperBiblio` 테이블 + `status` / `review_reason` 컬럼 추가
- ✅ [P08](./20260411_P08_PaperBiblio_Reflection_Policy.md) 정책 확정 (§3.5 write path, §4.2.1 curated_author_shortfall 포함)
- ✅ `papermeister/biblio_reflect.py` + `scripts/reflect_biblio.py` — single/batch/force 모두 검증 (devlog 021/022)
- ✅ `papermeister/zotero_writeback.py` — Zotero-sourced Paper 반영 경로 (network-atomic)
- ✅ `desktop/services/library.py::needs_review_paper_ids()` — count와 list가 공유하는 단일 helper (세션 10)

### 작업 항목 (모두 완료)

- ~~P08 정책 문서 작성~~ ✅
- ~~`papermeister/biblio_reflect.py` 신설~~ ✅
- ~~`scripts/reflect_biblio.py` batch 진입점~~ ✅ (+`--force` 플래그)
- ~~review 대상 조회 helper~~ ✅
- ~~Zotero write-back 경로~~ ✅ (§3.5 구현)
- ~~날짜 파서 버그 수정 + `Paper.date` 컬럼 추가~~ ✅ (세션 9 발견)

### 완료 기준

- ~~processed 문서에 대해 `PaperBiblio` 생성 가능~~ ✅
- ~~title/authors/year/journal/doc_type가 구조적으로 보관된다~~ ✅
- ~~P08 정책에 따라 high-confidence 값이 Paper에 일괄 반영된다~~ ✅ (devlog 021 검증)
- ~~review 대상과 auto-commit 대상이 쿼리 하나로 구분된다~~ ✅ (`needs_review_paper_ids()`)
- ~~Zotero-sourced Paper의 write-back이 drift-free로 동작한다~~ ✅ (devlog 022)

## Phase 3. Desktop UI Foundation (새 앱)

### 목표

[P09](./20260411_P09_New_Desktop_UI_Design.md)에서 정의한 모던 UI를 새 패키지에 스캐폴딩한다.
기존 `papermeister/ui/`는 **동결**, 새 앱은 `desktop/`에 둔다.

### 작업 항목

- `desktop/` 패키지 + `desktop/app.py` 엔트리포인트
- 공통 DB/서비스는 `papermeister.*`에서 재사용 (models, ingestion, ocr, biblio)
- 테마 로딩 (P09에서 선택된 스택)
- 메인 윈도우 shell (3-pane + 상단 검색 바 + 좌측 rail)
- Library/Sources 이중 네비 구조
- 상태/뱃지 시스템 기본 컴포넌트

### 완료 기준

- `python -m desktop` 으로 앱 실행
- 좌측 Library("All / Pending / Processed / Failed / Needs Review") + Sources(Zotero/Local) 둘 다 표시
- 기존 앱과 완전 독립 (import 양방향 금지)

## Phase 4. Paper List + Detail + Biblio Reflection Hookup

### 목표

사용자가 한 source를 열었을 때 paper list → detail → (한 건) biblio 반영까지 할 수 있게 한다.
**Phase 5(검색)보다 먼저**: 서지 반영 없이 FTS 검색은 title 기반이 쓸모 없기 때문.

### 작업 항목

- 중앙 paper list (status badge, title, authors, year, source 컬럼)
- 우측 detail panel: Paper 값 vs 최신 PaperBiblio 값 diff view
- detail panel에서 한 건 "Apply Biblio" 버튼 (P08 정책 위반 시 disable)
- background worker: 선택된 source/folder에 대해 batch 추출 실행
- 최소 process window (OCR/추출 진행률)

### 완료 기준

- 한 paper를 선택하면 Paper/Biblio 값이 나란히 보임
- Apply Biblio 한 번으로 Paper가 업데이트되고 list가 갱신됨
- 소스별 batch 추출을 GUI에서 트리거 가능

## Phase 5. Search and Retrieval

### 목표

corpus를 다시 찾고 활용하는 경험을 완성한다.
**Phase 4 이후 진행**: Paper 메타데이터가 채워져야 검색이 실사용 가능해짐.

### 작업 항목

- 상단 검색 바 (FTS5 BM25)
- metadata + text 혼합 검색
- source/doc_type/status 필터 패널
- relevance/year/recent 정렬
- snippet 하이라이트
- **PDF viewer 최소 기능** (MVP 보강 승격): 검색 결과 클릭 → 해당 페이지로 이동 (PyMuPDF render)

### 완료 기준

- full-text와 metadata 검색이 모두 가능하다
- 결과 해석에 필요한 provenance와 상태가 보인다
- snippet 클릭이 PDF 해당 페이지로 연결된다

## Phase 6. Review Queue + Controlled Automation

### 목표

high-confidence 자동 반영 외의 건들을 사용자가 통제 가능한 흐름으로 정리한다.

### 작업 항목

- review queue 뷰 (needs_review + low/medium confidence)
- diff view: current metadata vs extracted metadata (재사용)
- approve/edit/reject 흐름
- standalone promote 승인 흐름
- Zotero write-back 확인 흐름 (dry-run → 승인 → 반영 3단계)

### 완료 기준

- 자동 추출 결과를 검토 후 반영할 수 있다
- write-back이 무분별하게 동작하지 않는다

## Phase 7. Accuracy and Operations Hardening

### 목표

대량 운영과 예외 처리를 안정화한다.

### 작업 항목

- batch OCR retry/resume/concurrency 반영
- OCR backend switch: serverless / pod
- 실패 유형 세분화
- encrypted/broken PDF 처리
- 처리 통계/비용 추정 표시
- 테스트 코드 추가

### 완료 기준

- 대량 OCR에서 중단 후 복구가 가능하다
- reserved GPU와 serverless를 모두 운용할 수 있다
- 실패 원인을 사용자가 파악할 수 있다

## 상태 모델 (entity × state machine)

flat list 하나로 모든 상태를 표현하면 UI Library 매핑이 애매해진다.
각 entity별로 별개의 state machine을 유지하고, UI의 Library 폴더는 **이들의 조합 쿼리**로 정의한다.

### `PaperFile.status` — OCR 실행 관점

```
pending → processing → processed
                    ↘ failed (ocr_failed | download_failed)
```

- `pending`: OCR 아직 안 돌린 파일
- `processing`: OCR 실행 중 (UI에만 존재, DB엔 저장 안 함)
- `processed`: OCR JSON 캐시 존재 + Passage 적재 완료
- `failed`: OCR 실패. 세부 원인은 `PaperFile.failure_reason` (신규)에 저장

### `PaperBiblio.status` — 추출 결과 검토 관점 (신규 컬럼)

```
extracted → auto_committed   (P08 정책 통과)
         ↘ needs_review      (low/medium confidence 또는 필수 필드 누락)
         ↘ rejected          (사용자가 거부)
         ↘ applied           (사용자가 review 후 Paper에 반영)
```

- 여러 PaperBiblio row가 한 Paper에 달릴 수 있으므로, `status`는 row-level
- **P08에서 auto_committed 조건을 확정해야 이 상태가 실제로 의미를 갖음**

### `Paper` — 캐노니컬 메타데이터 품질 관점 (derived view, 저장 안 함)

```
stub       filesystem import 직후 (title = filename stem, year/authors/journal 없음)
empty      stub와 구분 안 해도 됨 (MVP에서는 stub로 통합)
extracted  PaperBiblio 있음, Paper에는 아직 반영 안 됨
curated    Paper.title 등이 PaperBiblio 또는 Zotero API로 채워짐
```

- 이는 derived view (쿼리로 판단), 컬럼 추가 안 함
- 판정 규칙:
  - `stub`: `Paper.year is null AND Author 없음 AND PaperBiblio 없음`
  - `extracted`: `stub 조건 + PaperBiblio 존재`
  - `curated`: `Author 존재 OR year not null` (Zotero에서 온 경우 자동으로 curated)

## Paper 정체성 비대칭 — Zotero vs Filesystem

`Paper / PaperFile / PaperBiblio` 분리는 원래 **Zotero 기준 모델**에서 왔다.

- Zotero에서 `Paper` = parent item (bibliographic entity), `PaperFile` = attachment
- Directory source에서 `Paper`에 해당하는 **사전 정보가 없음** — 파일이 전부

이로 인해 현재 `ingestion.py`는 directory import 시 `Paper.create(title=filename_stem)`으로 **stub Paper**를 만든다. 이건 정체성이 아니라 placeholder다.

### 의미

1. **directory import 직후**: Paper는 stub. title = 파일명, year = null, authors = 없음
2. **OCR 완료 후**: passage_fts는 채워지지만 Paper는 여전히 stub (본문 검색은 가능, 메타 검색은 부정확)
3. **biblio 추출 후**: PaperBiblio에 진짜 메타데이터 생김, Paper는 아직 stub
4. **P08 반영 후**: Paper가 curated 상태로 승격

### UI 함의

- Library의 "Needs Review"는 단순히 `PaperBiblio.status='needs_review'`만이 아니라,
  **stub Paper + PaperBiblio 없음** (= 추출 대기) 상태도 포함해야 할 수 있다.
- paper list에서 stub Paper는 시각적으로 구분 (예: title을 italic + placeholder 아이콘).
- 검색 결과에서 stub Paper는 "제목 없음 — 파일명: xxx.pdf"로 표기해 혼동 방지.

### Dedup / Merge 문제 (MVP 밖으로)

같은 PDF가 두 directory source에 있을 때 현재는 SHA256으로 같은 `PaperFile`로 인식하지만,
다른 PDF(버전 차이, 출판사/preprint)가 같은 work를 가리킬 때의 merge는 별개 문제.

- MVP: dedup은 PaperFile.hash 수준에서만. Paper 병합 없음.
- Phase 6+: DOI 기반 또는 사용자 수동 merge 도입 검토.

### 데이터 모델 보강 (경미)

현 모델을 그대로 두되, 운영상 다음만 추가한다:

- `PaperFile.failure_reason TEXT DEFAULT ''` — 실패 원인 세분화용
- `PaperBiblio.status TEXT DEFAULT 'extracted'` — 검토 큐 분류용 (extracted/needs_review/auto_committed/applied/rejected)

Paper 쪽에는 컬럼 추가 안 함 (stub/curated는 derived view로 판정).

### Workflow 상태 (별도 테이블 후보)

`promoted`, `writeback_pending` 같은 건 entity 상태가 아니라 **작업 큐의 상태**.
Phase 6에서 `WorkflowTask(type, target_id, status)` 테이블을 추가할 때 다루고, MVP에서는 뺀다.

### UI Library 폴더 매핑

| Library 폴더 | 쿼리 |
|-------------|------|
| All Files | PaperFile 전체 |
| Pending OCR | `PaperFile.status = 'pending'` |
| Processed | `PaperFile.status = 'processed'` |
| Failed | `PaperFile.status = 'failed'` |
| Needs Review | `PaperBiblio.status = 'needs_review'` (Paper 단위로 distinct) |
| Recently Added | `PaperFile.id` desc, 30일 내 |

## UI 구현 우선순위

1. source tree
2. paper list
3. detail panel
4. process window
5. preferences dialog
6. search UI
7. review queue

## 바로 해야 할 일 (2026-04-11 세션 10 갱신)

Phase 2가 닫히면서 남은 작업은 거의 Phase 4의 hookup 쪽으로 옮겨갔다.

1. ✅ [P08: PaperBiblio → Paper 반영 정책](./20260411_P08_PaperBiblio_Reflection_Policy.md) — §3.5 write path + §4.2.1 curated_author_shortfall 포함
2. ✅ [P09: 새 데스크탑 UI 설계](./20260411_P09_New_Desktop_UI_Design.md)
3. ✅ Phase 2 러너 구현 + 검증 (devlog 021/022)
4. ✅ Zotero write-back + `Paper.date` 컬럼 + 날짜 파서 fix (devlog 022)
5. ✅ `needs_review_paper_ids()` 공유 헬퍼 (세션 10)
6. Phase 3 스캐폴드 ✅ — **Phase 4 hookup 진행 중**:
   - desktop GUI 실제 실행 + Apply Biblio 버튼 클릭 실증 (백엔드는 검증됨)
   - desktop batch Reflect 트리거 UI + 결과 다이얼로그
   - desktop background worker (biblio 추출 / OCR 트리거)
   - desktop PaperList StatusBadge delegate
   - desktop OCR 미리보기 카드 (`ocr_json` 캐시)
7. Phase D (대량 운영): OCR 완료 ~2,000편에 Haiku biblio 추출 → Zotero write-back의 진짜 batch 시험대

**뒤로 미루는 것**:
- ~~Zotero write-back 정책 문서~~ → P08 §3.5로 흡수됨
- Preferences 스키마 재확정 → Phase 3 중반 (새 앱에서 필요한 것만)
- MVP 마일스톤 체크리스트 → HANDOFF.md에서 관리
- writeback batch rate limiting / 412 auto-retry → Phase D 착수 시점

## 결론

P07의 역할은 `P06`을 구현 가능한 순서로 바꾸는 데 있다.

정리하면 구현 순서는 다음과 같다.

1. ~~corpus 기반을 안정화한다~~ (이미 됨)
2. 서지정보 **반영 정책 + 러너**를 붙인다 (P08 기반)
3. 새 GUI를 모던 UI로 얹는다 (P09 기반, 기존 앱 동결)
4. paper list + detail + biblio 반영 hookup (한 건 반영 가능)
5. 검색 + PDF viewer 최소 기능
6. review queue + controlled automation
7. 대량 운영과 예외 처리를 강화한다

즉, `P06`이 무엇을 만들지 정하는 문서라면,
`P07`은 그것을 실제로 어떻게 완성할지 정하는 문서다.
2026-04-11 개정의 핵심은 **실제로 남아 있는 작업만 Phase로 남기고, 전제 정책을 별도 문서로 분리한 것**이다.
