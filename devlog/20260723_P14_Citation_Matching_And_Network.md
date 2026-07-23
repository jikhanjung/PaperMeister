# P14 — 참조 매칭 품질 + 논문 인용 네트워크

> 계획 문서 (2026-07-23, 세션 50). P11(references 추출)·P12(CitedWork 정규화)가
> 이미 라이브 반영된 상태에서, **참조↔보유논문 매칭의 남은 갭**과 **P11/P12가 명시적으로
> 미룬 "논문 인용 네트워크" 산출물**을 정리하고 착수 순서를 확정한다.

## 0. 배경 — 이미 있는 것 (재구현 금지)

references 매칭 "엔진"은 P11에서 설계+구현+라이브 실행됨. 새 작업은 매칭 *구현*이 아니라
**품질·증분성**과 **네트워크 산출물**이 초점.

| 이미 구현/라이브 | 위치 |
|---|---|
| DOI 정확일치 → 제목토큰+연도+1저자성 스코어링(임계 0.7) | `references.resolve_one` |
| 추출 직후 자동 resolve (배치당 인덱스 1회) | desktop 워커 + `scripts/extract_references.py` |
| 외부문헌 canonical 노드 dedup (exact + LLM 병합) | `references.canonicalize_reference` / `merge_works` |
| 신규 보유 시 외부노드→Paper 승격 | `references.reconcile_works_with_papers` |
| per-paper cited-by 역방향 뷰 / Cited Works 브라우저 | desktop `paper_service` / `cited_works_window` |

라이브 실측(2026-07-23): `Reference` 104,889행 · held 매칭 13,123 · external(CitedWork) 58,473 ·
`CitedWork` 49,728노드 · references_checked 1,737/9,828편(17.7%, 추출 진행 중).

P11이 계획만 하고 **미구현**으로 남긴 것: "인용 네트워크 export(GEXF/CSV)", "db_stats cited 카운트".
held↔held **공동인용/서지결합**은 어느 계획에도 없음(P12는 external 전용).

## 1. 매칭 — 남은 실질 과제

### A1. 증분 재-resolve 갭 ⚠️
resolve는 *추출 시점*에만 돈다. **나중에 새 논문이 라이브러리에 들어오면, 예전에 파싱돼
external/unresolved로 남은 references는 그 신규 논문과 자동 재매칭되지 않는다.**
`reconcile_works_with_papers`는 CitedWork→Paper 승격 경로만 커버 — CitedWork가 안 붙은
unresolved refs나 신규 논문에만 매칭될 refs는 방치됨. ("예전 엔트리 ↔ 현재 보유 논문 매칭"이
바로 이 지점.)
- **계획**: 논문 add / Zotero sync 완료 후 unresolved refs 한정 증분 재-resolve 훅.
  저비용(held 인덱스 1회 빌드 + 토큰 후보 조회). 우선 `scripts/resolve_references.py`에
  `--only-unresolved` 스코프를 확실히 하고, desktop sync 완료 콜백에서 호출.

### A2. 매칭 품질 감사 (임계 0.7 근거 없음)
precision/recall 미측정. 네트워크를 만들기 *전에* 엣지 품질을 확보해야 함(나쁜 매칭=나쁜 엣지).
- **계획**: `scripts/audit_matches.py`(read-only 샘플러) —
  (a) 임계 근처 title-match N개 → false positive 후보,
  (b) 제목이 보유논문과 강하게 겹치는데 external로 남은 refs N개 → false negative 후보.
  LLM(claude/qwen) 판정 옵션. 결과로 0.7 튜닝 근거 확보.

## 2. 논문 인용 네트워크 — 레이어별

held→held 엣지는 이미 `Reference.resolved_paper`에 존재(현재 13,123). 이를 산출물로.

- **L0 — 통계 (즉시, 저비용)**: `scripts/citation_stats.py` — 라이브러리 내 엣지 수,
  in-degree 최다(가장 많이 인용된 보유논문), out-degree, 고립 노드, 자기인용. read-only.
  17% 데이터로도 유의미 + sanity check.
- **L1 — 그래프 export**: `scripts/export_citation_graph.py` → `nodes.csv`(paper_id/title/
  year/author/in-deg/out-deg) + `edges.csv`(citing→cited) + GEXF. held→held만(양끝 보유).
  옵션 `--with-external`로 CitedWork를 2층 노드로. 인앱 엔진 없이 Gephi/Cytoscape로 시각화.
- **L2 — 인앱 ego-network 뷰** (추출 더 찬 뒤): 전역 hairball 대신 선택 논문의 1~2홉
  자기중심 그래프(references + citers)를 `QGraphicsView`로. tractable + 실사용성 높음.
- **L3 — 공동인용/서지결합** (신규 갭, 추출 더 찬 뒤): co-citation(A,B를 함께 인용하는
  논문 수) + bibliographic coupling(공유 references 수). "직접 인용 없이 관련된 논문" 발굴
  → "관련 논문" 패널.

## 3. 착수 순서 (차례대로)

추출이 17%로 진행 중 · 네트워크는 추출 완성도만큼만 완성됨 → **부분 데이터에도 동작하고
재실행 가능한 read-only부터**, 매칭 품질을 네트워크 export 이전에 확보.

1. **L0** `scripts/citation_stats.py` — 즉시 유용, sanity check.
2. **A2** `scripts/audit_matches.py` — 임계 튜닝 근거(엣지 품질).
3. **L1** `scripts/export_citation_graph.py` — Gephi용 GEXF/CSV.
4. **A1** 증분 재-resolve 훅 — 매칭의 구조적 갭(라이브러리 성장 대응). *DB 변경 → Windows 실행.*
5. **L2 / L3** — 추출이 더 찬 뒤(희소 그래프 회피) 재평가.

모든 read-only 스크립트는 **네이티브 Windows에서 실행**(WSL로 라이브 DB 접근 금지, devlog 068).
DB 변경 스크립트(A1)는 `--execute` 컨벤션 + Windows 실행.

## 4. 범위 밖

- Level 3 in-text 인용맥락(본문 `[12]` ↔ Reference 문장 단위) — P11 범위 밖 유지.
- 저자/기관 co-citation 네트워크.
- 시계열 인용 흐름 분석.
