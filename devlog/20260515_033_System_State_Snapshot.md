# 20260515_033 — 현재 시스템 상태 스냅샷 (docs/ 매핑)

## 목적

`docs/`에 누적된 전략/아키텍처 문서들과 현재 코드 상태를 한 번 맞춰서, 어디까지 와 있고 다음 결정 포인트가 어디인지 정리한다. 세션 19 이후가 들어왔을 때 빠르게 좌표를 잡기 위한 스냅샷.

## 1. 제품 원칙

**"Store first, understand later."** (`papermeister_specification.md` §3)

- raw OCR이 source-of-truth
- 모든 derived layer는 raw에서 재생성 가능해야 함
- 해석은 destructive하지 않고 additive

이 원칙은 현재 코드에 반영돼 있다:
- `~/.papermeister/ocr_json/{hash}.json` — raw OCR 캐시 영속
- `PaperBiblio` — LLM 추출은 별도 테이블, `Paper`를 직접 안 건드림
- biblio reflect 정책은 빈 슬롯 채우기 우선, override는 force flag 필요

## 2. 로드맵 위치

```
Phase 1 (Foundation 안정화) ──┐
                              │← 현재 위치
Phase 2 (Structured corpus) ──┘ ↓ 진입 대기
Phase 3 (Analysis)
Phase 4 (Entity/Assertion extraction)
Phase 5 (Research assistant)
```

세션 16~18에서 한 작업(`papermeister_meta` cross-machine sync, write-back 토글, client_id, server-load wait, bookSection 픽스)은 Phase 1 안정화 범주에 속한다. Phase 2 진입 결정이 아직 안 났다.

명시적 non-goal (`papermeister_specification.md` §4, §5):
- open-ended autonomous loop agent — 만들지 않음
- always-on persona — 만들지 않음
- agent behavior로 가는 것보다 **structured corpus + 더 좋은 derived data**가 먼저

## 3. 구현 상태 ↔ docs vision 매핑

### Source/Sync 레이어 (`sync_centric_architecture_spec.md`)

| docs가 그리는 그림 | 현재 코드 |
|---|---|
| Zotero/EndNote/folder를 source로 받아 canonical corpus로 통합 | Zotero + folder 두 source. EndNote/RIS/BibTeX는 미지원 |
| 단방향 sync (외부 → PaperMeister) | 동작 중 (Zotero incremental pull, folder scan) |
| 매칭 정책: DOI/hash auto-merge, title/author candidate, weak signal alone은 안 함 | 부분적 — hash 기반 dedup만 있고 DOI/title cross-source 매칭은 없음 |
| Bidirectional sync는 나중 | **세션 17부터 Zotero write-back 시작** — pref 토글(기본 OFF)로 제한적 부분 활성화 |
| 메타데이터 우선순위: external bib > linked source > PDF embedded > OCR 추측 | 적용 중 (`zotero_writeback._compute_patch`는 Zotero 빈 슬롯만 채움) |

### 데이터 모델 (`data_model_revision_spec.md`)

| docs가 그리는 그림 | 현재 코드 |
|---|---|
| Source → SourceRecord → SourceFile (외부 관찰) | **SourceRecord/SourceFile 없음** — Zotero item을 직접 `Paper`로 흡수 |
| Paper → PaperFile → Passage (canonical) | 있음 |
| PaperSourceLink (M:N 외부 ↔ canonical) | **없음** |
| `Paper.zotero_key` 같은 source-specific 필드는 canonical에 두지 말 것 | **여전히 있음** — `Paper.zotero_key`, `PaperFile.zotero_key` 직접 저장 |
| `PaperFolder` M:N (다중 collection 소속) | **있음** (세션 13 추가) |
| Passage에 `block_type`, `section_title` 등 구조 메타 | **없음** — 평평한 텍스트만 |

→ data model revision은 **거의 진입 안 함**. 현재는 MVP-스러운 source-tied 모델 그대로. Phase 2 진입 시 `SourceRecord`/`SourceFile`/`PaperSourceLink` 도입 필요.

### OCR & Corpus

| docs가 그리는 그림 | 현재 코드 |
|---|---|
| Chandra2 layout-aware OCR | 동작 중 (3 백엔드: RunPod serverless / Direct vLLM pod / Wrapper API) |
| layout/section/caption 보존 | **거의 안 함** — markdown만 추출해서 passage로 평평하게 split |
| OCR 비용 최적화 | wrapper 자체 서버로 옮겨가면서 RunPod 비용 우려는 해소 |
| 머신 간 OCR cache 공유 | **세션 17~18에서 추가됨** — Zotero sibling JSON으로 cross-machine sync. `papermeister_meta`로 biblio 상태도 함께 전달 |

### LLM 추출 (Phase 1.5 즈음)

docs에는 명시적 항목 없음. 코드에서는:
- Haiku/Sonnet (Anthropic API via `claude -p`), Qwen3-14B (자체 wrapper) 모두 지원
- PaperBiblio 별도 테이블에 비파괴 저장
- evaluate → auto_commit / needs_review / skip 정책
- write-back: Zotero PATCH로 빈 슬롯 채움 + force override 경로

이 부분은 docs vision에는 명시 안 됐지만 Phase 2의 "structured corpus" 진입 전에 자연스럽게 추가된 layer다.

### Search

| docs가 그리는 그림 | 현재 코드 |
|---|---|
| FTS5 BM25 | 동작 중 |
| Highlight matched snippets | **미구현** (`papermeister_specification.md` §7.2 Workstream C) |
| Title × document-level boost | **미구현** — `passage_fts`가 passage 단위라 title 가중치가 document-level로 작동 안 함 |

## 4. 판매 vs 비전 (`sellable_mvp_definition.md`)

명시적 분리가 중요하다:

- **판매 MVP**: "Zotero/폴더 안 버리고 스캔본까지 searchable corpus로 바꿔주는 로컬 도구"
- **비전 데모**: 구조화 + 분석 + assertion + assistant 확장

현재 판매 MVP는 사실상 작동 가능한 상태:
- Zotero/folder source ✓
- OCR + 캐시 ✓
- FTS 검색 ✓
- 기본 상세 뷰 ✓
- source별 browse ✓
- 재처리 가능 ✓
- 기본 처리 안정성 ✓ (세션 16~18에서 보강)

남은 "있으면 좋은" 항목 (`sellable_mvp_definition.md` §5):
- pending/failed status 표시 ✓
- search snippet — 미구현
- source provenance 표시 — 부분적
- 대량 처리 안정성 — 세션 18에서 client_id + server wait로 보강

## 5. RAG와의 구분 (`papermeister_vs_rag.md`)

마케팅 한 줄:
- RAG는 답변을 만든다
- PaperMeister는 답변 가능한 연구 코퍼스를 만든다

계층 관계 (경쟁 아님):
- PaperMeister corpus 위에 RAG 올릴 수 있음
- PaperMeister 자체는 RAG로 환원되지 않음

## 6. SCODA/PaleoBase 연결 (`papermeister_to_scoda_pipeline.md`, `papermeister_paleobase_feedback_loop.md`)

PaperMeister corpus → SCODA package로 바로 안 변환됨. 사이에:

```
Source → PaperMeister Corpus → Domain Extraction → Canonical Domain DB → SCODA Package
                ↑                                          ↓
                └──────── PaleoBase feedback loop ─────────┘
```

PaperMeister는 Layer 1~2, SCODA는 Layer 5. Layer 3~4 (assertion 추출, normalization)는 **현재 코드에 없음** (Phase 4 영역).

## 7. 네이밍 상태 (`docs/naming/`)

`final_name_direction_memo.md` 결정:
- **회사명은 paleontology로 좁히지 말 것** — broader infrastructure 정체성
- `Paleo...`는 domain package 이름에만 사용
- shortlist에서 `Noematica`가 회사명 후보로 정리됨 (`noematica_brand_package.md`)
- 제품명 `PaperMeister` 대체 후보로 `Noostrata` 등 (`product_name_shortlist_refresh.md`)

코드/UI에는 아직 `PaperMeister` 그대로. 이름 전환은 미정.

## 8. API 명세 (`ENDPOINTS.md`, `WRAPPER_API.md`)

자체 OCR 서버:
- `:8080/ocr` → wrapper (FastAPI, Job 관리)
- `:8080/llm/` → Qwen3-14B (OpenAI 호환)
- `:8080/v1/` → Chandra OCR (직접 접근)
- `:8080/health` → Chandra 헬스체크

`client_id` 지원: form 필드 또는 `X-Client-ID` 헤더. `(file_hash, client_id)` 기반 server dedup.

## 9. 미정/대기 결정 사항

### 데이터 모델 분리 (Phase 2 전제조건)

`Paper.zotero_key`, `PaperFile.zotero_key` 같은 source-specific 필드를 canonical entity에서 떼어내고 `SourceRecord`/`SourceFile`/`PaperSourceLink` 구조로 옮길 것인가. 단계적 마이그레이션 권장 (`data_model_revision_spec.md` §10).

진입하지 않는 한 EndNote/RIS/BibTeX 등 metadata-only source 지원이 깔끔하지 않다.

### Structured corpus (Phase 2 핵심)

OCR 결과를 단순 markdown에서 section/caption/body로 분리해 저장할 것인가. Chandra2 출력에 layout 정보가 있다는 게 전제. `Passage.block_type` 같은 필드 추가 + parser 신설 필요.

### Search 개선

- BM25 document-level title boost (passage_fts 한계, Phase 5 경계로 기록되어 있음)
- 검색 결과 매칭 패시지 하이라이트 (Phase 1 Workstream C)

### 운영

- 1960s standalone PDF 226편 OCR 상태 확인
- ~2,000편 OCR 완료분에 일괄 biblio 추출 → reflect_biblio 실행 (Phase D)
- batch reflect 트리거 UI / background worker / StatusBadge delegate (Phase 4 hookup 미완)

### 라이브 검증

- 세션 18의 변경(papermeister_meta + client_id + bookSection 픽스) cross-machine 시나리오 한 사이클 검증

## 10. 문서 인덱스 (빠른 참조)

| 주제 | 문서 |
|---|---|
| **전체 방향** | `papermeister_specification.md`, `phase1_task_breakdown.md` |
| **아키텍처** | `sync_centric_architecture_spec.md`, `data_model_revision_spec.md`, `minimal_multi_source_gui_spec.md` |
| **판매 MVP** | `sellable_mvp_definition.md`, `lab_vs_individual_requirements.md` |
| **포지셔닝** | `papermeister_vs_rag.md`, `ai_era_academic_infrastructure_positioning.md` |
| **연결** | `papermeister_to_scoda_pipeline.md`, `papermeister_paleobase_feedback_loop.md` |
| **OCR/데모** | `ocr_cost_optimization_plan.md`, `demo_corpus_strategy.md`, `copyright_demo_policy.md` |
| **마케팅/세일즈** | `pricing_and_go_to_market_memo*.md`, `customer_discovery_plan*.md`, `landing_page_copy*.md`, `pilot_one_pager_ko.md`, `interview_outreach_email_ko.md`, `leaflet_copy.md` |
| **네이밍** | `naming/final_name_direction_memo.md`, `naming/noematica_brand_package.md`, `naming/product_name_shortlist_refresh.md` |
| **API** | `ENDPOINTS.md`, `WRAPPER_API.md` |

## 한 줄 요약

판매 MVP는 작동, Phase 1 안정화 끝물 (세션 16~18에서 cross-machine sync + bookSection 픽스로 끝마무리 중), **Phase 2 (structured corpus) 진입은 데이터 모델 분리부터 시작해야 함**.
