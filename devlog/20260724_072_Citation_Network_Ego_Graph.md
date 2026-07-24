# 072 — 인용 네트워크 그래프 시각화 (P14 L2, ego-network)

> 구현 기록 (2026-07-24). [P14](20260723_P14_Citation_Matching_And_Network.md) L2.

## 결정: 전역 hairball 대신 ego-network

held→held 인용 그래프는 라이브러리 전체로는 수천 노드 → 화면에 다 그리면 hairball이라
쓸모없음. **선택 논문 중심 1~2홉 자기중심(ego) 그래프**로 스코프(P14 권고). 노드 상한
`max_nodes=60`(고차수 노드가 2홉에서 폭발하는 것 방지).

## 산출물

- **`paper_service.load_ego_network(paper_id, hops, max_nodes)`**: `reference.resolved_paper_id`
  기반 held→held 엣지를 BFS로 홉만큼 확장(노드 상한) → 유도 부분그래프 엣지. raw SQL(기존
  co-citation 패턴). 반환 `(center, nodes{pid→EgoNode(label,title)}, edges[(s,d)])`.
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

**양방향 색상 구분**: ego 쿼리가 애초에 `citing IN … OR resolved IN …`라 **인용한/피인용** 둘 다
포함. render 시 center와의 직접 엣지로 노드 분류 — 초록=이 논문을 인용, 앰버=이 논문이 인용,
시안=상호, 회색=2홉. 상태바에 카운트+범례. (피인용은 다른 논문들이 references 추출돼 이 논문으로
resolve된 만큼만 나타남 — 추출 진행률에 비례.)

## 검증
`spring_layout` 회귀 테스트(center 고정/경계/결정성), offscreen 렌더 스모크, import 스모크.
`load_ego_network`(DB 의존)는 라이브 확인 대기. 후속: L3(공동인용/서지결합) 오버레이.
