# 072 — 인용 네트워크 그래프 시각화 (P14 L2, ego-network)

> 구현 기록 (2026-07-24). [P14](20260723_P14_Citation_Matching_And_Network.md) L2.

## 결정: 전역 hairball 대신 ego-network

held→held 인용 그래프는 라이브러리 전체로는 수천 노드 → 화면에 다 그리면 hairball이라
쓸모없음. **선택 논문 중심 1~2홉 자기중심(ego) 그래프**로 스코프(P14 권고). 노드 상한
`max_nodes=60`(고차수 노드가 2홉에서 폭발하는 것 방지).

## 산출물

- **`paper_service.load_ego_network(paper_id, hops, max_nodes)`**: **전체 인용 네트워크** ego —
  held 논문(`resolved_paper`) + **외부 CitedWork**(`resolved_work`, references 추출된 미보유 문헌)
  둘 다 포함. held만 확장·external은 leaf(외부 문헌의 자체 refs는 없음), held 우선 상한. 노드 키
  `"p{id}"/"w{id}"`로 Paper/CitedWork id 충돌 회피. 반환 `(center_key, nodes{key→EgoNode}, edges)`.
  `EgoNode.kind` ∈ {held_pdf, held, external}, `paper_id`(held만 non-None → 클릭 재중심 대상).
- **`desktop/windows/network_window.py`**:
  - `spring_layout()` — Fruchterman–Reingold force-directed, **순수 함수**(RNG 없이 원형 시드 →
    결정적, 테스트 가능), center 노드 고정. O(n²·iter)이지만 ego는 n≤60이라 즉시.
  - `_NetworkView(QGraphicsView)` — 줌(휠)·팬(drag), 방향 화살표 엣지, center 노드 강조,
    노드 툴팁=제목. **클릭=재중심**(그래프 탐색; 팬과 구분: press·release 같은 노드+이동<5px).
  - `NetworkWindow` — 헤더(Back 히스토리 / 제목 / Hops 1·2 / "Open in list") + 뷰. 이웃
    클릭 → 재중심(히스토리 push), Open → `open_paper` 시그널로 메인 리스트 reveal.
- **배선**: PaperList 우클릭 "Show in citation network"(status 무관) → main_window
  `_open_network` → `open_paper`를 `_on_reference_navigate`에 연결.

## UX
노드를 **클릭하면 그 논문 중심으로 재구성**(그래프 걸어다니기), 원하는 논문에서 "Open in list"로
점프. 리스트 열기가 버튼이라 단일 클릭=재중심에 모호성 없음. 팬(드래그)과는 press·release 같은
노드 + 이동<5px로 구분.

**2채널 시각화**:
- **채움색 = 방향**(center 기준 직접 엣지): 초록=이 논문을 인용(피인용), 앰버=이 논문이 인용,
  시안=상호, 회색=2홉. (피인용은 다른 논문이 references 추출돼 이 논문으로 resolve된 만큼만.)
- **테두리 = 보유 상태**: 굵은 실선=**PDF 보유 held**, 얇은 실선=held(PDF 없음), 점선=**external
  (cited-only, 미보유)**. external 노드는 클릭 재중심 안 됨(논문이 아님), 툴팁만.
상태바에 방향/테두리 양쪽 카운트+범례.

## 검증
`spring_layout` 회귀 테스트(center 고정/경계/결정성), offscreen 렌더 스모크, import 스모크.
`load_ego_network`(DB 의존)는 라이브 확인 대기. 후속: L3(공동인용/서지결합) 오버레이.
