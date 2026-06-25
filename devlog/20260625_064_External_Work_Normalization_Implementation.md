# P12 구현 — 외부 문헌 정규화 (CitedWork 노드) + co-citation UI

> 구현 기록. 계획·설계는 [P12 계획서](./20260625_P12_External_Work_Normalization.md) 참조.
> 본 문서는 그 계획을 코드로 옮긴 결과(파일·동작·검증·실행 절차)를 정리한다.
>
> **상태(2026-06-25)**: 코드·임시DB 검증 완료. 라이브 마이그레이션/백필은 대기
> (진행 중인 reference 추출 작업 종료 후 Windows에서 실행).

## 1. 스키마 (`models.py` / `database.py`)

- **`CitedWork`** 신규 — 외부(미보유) 문헌 1건 = canonical 노드:
  `doi`(정규화·인덱스), `title`, `title_key`(지문·인덱스), `year`, `authors_json`,
  `container`, `first_surname`(blocking 키), `cite_count`(비정규화),
  `merge_checked`(패스2 판정 영속화), `merged_into_paper`(promotion tombstone), `created_at`.
- **`Reference.resolved_work`** FK 추가 — `resolved_paper`(held)와 **상호배타**, 둘 다 null=junk.
- `database.py`: `ALL_TABLES`에 `CitedWork` 등록(create_tables 자동 생성),
  `_migrate`가 기존 DB에 `reference.resolved_work_id` 컬럼+인덱스 추가
  (citedwork 테이블이 먼저 생성되므로 FK 참조 안전).

## 2. 정규화 로직 (`references.py`)

**패스 1 — exact dedup (deterministic):**
- `well_formed_doi()` — `^10\.\d{4,9}/` 형태만 신뢰(OCR 오염 방지).
- `work_title_key()` — 정규화 제목 지문(소문자·스톱워드 제거·CJK 유지·토큰 정렬).
- `build_work_index()` — 활성 CitedWork의 `{doi→wid, (title_key,year)→wid}` 인메모리 인덱스.
- `canonicalize_reference()` — DOI/title_key exact 일치 시 링크, 없으면 새 CitedWork 생성.
  인덱스를 in-place 갱신해 같은 배치 내 후속 ref가 중복 생성 방지.
- `resolve_paper_references(..., work_index=None)` — `work_index` 주면 held 매칭 실패 ref를
  canonicalize(Phase 2), 없으면 기존 Phase 1 동작(**하위호환**).

**패스 2 — LLM 병합 (충돌 클러스터만):**
- `cluster_works_by_block(max_cluster)` — `(first_surname, year)`로 묶어 후보 ≥2·미판정
  클러스터만 반환.
- `biblio.llm_match_works()` — 클러스터 후보를 LLM에 보내 "같은 work 그룹"을 받음
  (`_WORK_MERGE_PROMPT`, 워커 안전, 인덱스 누락→singleton 보정). 보수적(애매하면 분리).
- `merge_works(keep, ids)` — dup의 citation을 keep으로 repoint(`match_method='work-llm'`)
  + dup 행 삭제(works는 재생성 가능하므로 tombstone 불필요).
- `mark_merge_checked()` — 판정 완료 표시 → 재실행 시 스킵(resumable).

**공용:** `recompute_cite_counts()`(distinct citing paper 수 재계산),
`reconcile_works_with_papers()`(보유 논문 획득 시 promotion).

## 3. LLM 병합 프롬프트 (`biblio.py`)

`_WORK_MERGE_PROMPT` + `llm_match_works(works, backend, base_url)` — `_call_qwen` 재사용,
`_parse_llm_json_array`로 그룹 배열 파싱, 모든 인덱스 정확히 1회 등장 보정.

## 4. 백필 스크립트 (`scripts/normalize_works.py`)

dry-run 기본, `--execute`로 기록. 옵션: `--backend`, `--pass {all,1,2}`, `--workers`,
`--max-cluster`, `--no-reconcile`. 흐름: 패스1(exact) → 패스2(LLM, 워커 병렬·DB write는
메인스레드) → cite_count 재계산 → reconcile. resumable(판정 영속화).

## 5. 추출 파이프라인 연결

- `scripts/extract_references.py` 추출 후 auto-resolve가 `build_work_index`로 패스1
  canonicalize까지 수행.
- **desktop 추출 워커**(`main_window._run_references_extraction_silent`)도 동일 —
  `_refs_work_index` per-batch 캐시, `_after_refs`에서 `_refs_index`와 함께 무효화.

## 6. Desktop UI (단계 6)

- **References 탭 외부 카드 배지 3종**(`detail_panel._reference_badge`):
  held=초록 `● in library`(클릭→이동) / 공동인용=앰버 `◆ also cited by N`
  (클릭→`_show_cocitations` QMenu로 공동인용 논문 나열→이동) / 단독=회색 `○ cited only`.
  co-citation 카운트는 `paper_service.load_references`에서 aggregate 1회(N+1 회피).
- **Cited Works 브라우저**(`desktop/windows/cited_works_window.py`): Rail 액션 `works`
  (신규 `desktop/theme/icons/works.svg`)로 오픈. 외부 work를 인용수 desc 테이블
  (Cites/Year/Authors/Title/In/DOI), 좌=work·우=인용 라이브러리 논문 리스트
  (더블클릭→메인창에서 논문 열기), title/author 필터 + "≥2만" 토글.
  `cite_count`는 live 집계(denormalized 컬럼 미의존 → recompute 안 돌렸어도 정확).
- 서비스(`paper_service.py`): `ReferenceRow`에 `resolved_work_id`/`cocite_count`,
  `CitedWorkRow` + `top_cited_works()` + `load_work_cociters()`.

## 7. 검증

라이브 DB·LLM 서버 미사용, 임시 throwaway DB로:
- **코어 16/16** — held resolve / 제목·DOI exact dedup / junk / cite_count /
  클러스터·LLM 병합(스텁)·merge_checked 재실행 스킵 / reconcile promotion.
- **desktop 14/14**(offscreen Qt) — co-citation 배지·카운트 / `top_cited_works`(≥1·≥2·필터) /
  `load_work_cociters` / Rail `works` 아이콘 / 브라우저 테이블·선택 / References 탭 빌드.

## 8. 커밋

```
1469d96 references(P12): CitedWork node schema + Reference.resolved_work
ca17cf0 references(P12): exact dedup + LLM merge for external works
1b8f9d3 references(P12): normalize_works backfill + auto-canonicalize on extract
7911f21 docs(P12): external work normalization plan + status
6906b73 desktop(P12): co-citation + top-cited-works service queries
bc2f1d6 desktop(P12): Cited Works browser + co-citation badges
14c8961 docs(P12): step-6 desktop UI status (co-citation + Cited Works)
```

## 9. 남은 일 / 실행 절차

- **라이브 적용** (추출 작업 종료 후 Windows Anaconda):
  1. 아무 PaperMeister 프로세스 실행 시 마이그레이션 자동 적용(citedwork 테이블 + 컬럼).
     추출 도중 다른 프로세스 동시 실행은 피한다(동시 ALTER lock 회피).
  2. `python scripts\normalize_works.py`(미리보기) → `--execute`(패스1)
     → `--pass 2 --execute --workers 3`(LLM 병합).
- 패스2 LLM 병합은 desktop에서 자동 실행하지 않음(배치 전용). 브라우저는 패스1 노드로 동작
  (일부 중복 가능, 허용).
- 현재 실행 중인 추출에는 무영향(옛 코드 메모리 상주; 다음 실행부터 적용).
