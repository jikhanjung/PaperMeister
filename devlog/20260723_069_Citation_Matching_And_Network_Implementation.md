# 069 — P14 구현: 인용 매칭 품질 + 네트워크 산출물 + 라이브 재-resolve

> 구현 기록 (2026-07-23). 계획 [P14](20260723_P14_Citation_Matching_And_Network.md).
> 결정·근거 위주(diff는 git).

## 1. 스코어러 보강 (`references._score_title`)

**문제**(A2 감사로 실측): 매칭 스코어가 `inter/min(두 쪽)` **순수 containment**라,
짧은 ref 제목이 긴 논문 제목에 통째로 박히면 **1.0** → 오연결. 라이브에서 title 매칭
12,925 중 4,279(33%) 의심, "On Growth and Form"이 "…growth and form of teeth…"에 오연결.
반대로 정규화 제목 **완전일치인데** year/저자 요건 때문에 놓친 FN 4,403.

**해결**: containment에 **Jaccard(대칭) 블렌드** → 짧은제목-긴제목 박힘이 1.0 안 됨.
+ **near-exact 토큰셋**(≥3 공유, 큰 쪽 1개 이내 차이)은 강신호로 year mismatch veto 면제 →
exact-title FN 회수.

**검증**: 오프라인 A/B(라이브 스냅샷, DB의 기존 match를 OLD로 사용). held 9,339 유지,
**FP 3,225 제거 · FN 7,697 회수**(일부는 fresh 인덱스 재-resolve 효과). 회귀 테스트로 고정
(`tests/test_references.py`).

## 2. 네트워크 산출물 (read-only 스크립트)

held→held 인용은 이미 `Reference.resolved_paper_id`에 존재 → 이를 산출물로:
- **L0 `citation_stats.py`**: 통계(엣지/노드/in·out-degree, 최다 피인용/인용).
- **L1 `export_citation_graph.py`**: nodes/edges CSV + GEXF(Gephi), `--with-external`로 CitedWork 2층.
- **A2 `audit_matches.py`**: 매칭 감사(FP: year gap/surname mismatch, FN: 미연결인데 제목일치).
- **모니터 `refs_progress.py`**: 추출 진행률/ETA.
- 전부 `mode=ro` + stdlib, **Windows 네이티브 실행**(WSL 라이브 DB 금지, devlog 068).

## 3. A1 — 라이브 재-resolve (⚠️ P12-safe 픽스가 핵심)

새 스코어러를 기존 104k refs에 반영하려면 `resolve_references.py --reresolve`. **그런데 이
스크립트는 P12 이전 것**이라 그대로 실행하면: (a) FN 회수분(외부→held)에서 `resolved_work`를
안 지워 **이중 링크**, (b) 매칭 안 되는 외부 refs의 `work-*` match_method를 `none`으로 덮어
**CitedWork 58k 레이어 라벨 파괴**.
→ **held 차원만 수정, 외부 레이어 보존**하도록 재작성: held 매칭 시 `resolved_work=None`,
외부로 남는 건 skip. 오프라인 시뮬레이션으로 "외부 refs 오writes 0" 불변식 검증 후 실행.

**라이브 결과**(Windows, 앱 닫은 상태, resolve→normalize `--pass 1`→`--pass 2` ~61분):
unresolved **31.7%→4.3%**, held 13,123→**17,671**, external 58,473→**83,388**, held→held 엣지
12,038→**17,089**, CitedWork 49,728→**59,963**(pass1 canonicalize 순증 − pass2 near-dup 5,989 병합).
`quick_check=ok`. **병합 spot-check 통과**(OCR/철자/음차 변형, Hupé 1953/1955 Part1/2는 연도로
구분 유지 — 과대병합 없음).

## 비고
- L2(인앱 ego-view)·L3(공동인용)은 추출이 더 찬 뒤. 관찰: out-degree 이상치("Education 2005"
  367), borderline 병합 1건(work#20427).
