# PaperMeister 프로젝트 현황과 다음 발전 방향 Overview

**날짜:** 2026-04-03
**유형:** 프로젝트 방향 정리

## 1. 현재 PaperMeister의 상태

현재 PaperMeister는 이미 "아이디어 단계"를 넘어, 실사용 가능한 **논문 수집/처리/검색용 로컬 워크벤치**에 도달해 있다.

구현 완료 범위는 대략 다음과 같다.

- 로컬 폴더 및 Zotero 컬렉션에서 논문 수집
- PDF 단위 등록 및 중복 관리
- RunPod Chandra2 기반 OCR 및 raw JSON 캐시 보존
- SQLite + FTS5 기반 전문 검색
- PyQt6 GUI
- PyQt6 없이 동작하는 CLI

즉, 현재 프로젝트의 본체는 "논문 PDF를 구조화 가능한 내부 자산으로 축적하는 ingestion engine"이며, 이 기반은 꽤 탄탄하다.

핵심적으로 중요한 점은 이미 다음 원칙이 코드와 문서에 반영되어 있다는 것이다.

> Store first, understand later

이 원칙은 앞으로의 확장 방향과도 잘 맞는다. 지금 단계에서 가장 가치 있는 일은 새로운 기능을 여기저기 붙이는 것이 아니라, 이미 쌓인 corpus를 **어떻게 구조화된 지식 레이어로 승격시킬지**를 설계하는 것이다.

---

## 2. idea1, idea2를 현재 상태와 연결해서 보면

두 아이디어는 모두 충분히 현실적이다. 다만 지금의 PaperMeister에 가장 잘 맞는 방식으로 재정리할 필요가 있다.

### idea1의 핵심

idea1은 PaperMeister를 장기적으로 **고생물학 Research Assistant의 기반 시스템**으로 확장하자는 제안이다.

이 방향은 타당하다. 이유는 다음과 같다.

- corpus 확보 파이프라인이 이미 구현되어 있다
- OCR 결과 raw JSON까지 보존하고 있어 후처리 확장이 쉽다
- Zotero 연동이 있어 개인 논문 라이브러리를 지속적으로 흡수할 수 있다
- FTS 검색이 이미 있으므로 retrieval 기반 워크플로우의 출발점이 마련되어 있다

다만 지금 바로 "Claude Code 스타일 상시 실행 에이전트"로 가는 것은 과하다. 현재 프로젝트에 가장 자연스러운 경로는 아래와 같다.

1. 논문 저장소
2. 구조화 추출 레이어
3. 분석 도구 레이어
4. 마지막에 research assistant 레이어

즉, agent는 마지막 단계여야 한다. 먼저 **좋은 corpus와 좋은 도구**가 있어야 한다.

### idea2의 핵심

idea2는 corpus에서 키워드, 태그 클라우드, 네트워크 분석 같은 분석 결과를 뽑아보자는 방향이다.

이 역시 현실적이지만, 우선순위를 나누는 게 중요하다.

- 단순 tag cloud: 만들기 쉽지만 연구적 가치가 낮을 수 있음
- TF-IDF / n-gram / keyphrase: 실용성 높음
- taxon / locality / geologic time 같은 엔티티 기반 분석: 장기 가치가 큼
- co-occurrence / citation / author network: 시각화와 탐색 측면에서 유용

결론적으로 idea2는 "별도 아이디어"라기보다 PaperMeister의 **첫 번째 분석 레이어**로 보는 편이 맞다.

---

## 3. 지금 가장 적절한 제품 방향

현 시점에서 PaperMeister는 "PDF 관리 앱"으로 남기기엔 아깝고, 반대로 곧바로 "지능형 에이전트"로 점프하기엔 이르다.

가장 좋은 발전 방향은 다음 한 문장으로 정리할 수 있다.

**PaperMeister를 논문 검색 앱에서 구조화된 연구 코퍼스 플랫폼으로 확장한다.**

조금 더 구체적으로 말하면:

- 1단계: 저장과 검색을 안정화
- 2단계: 구조화 추출 결과를 별도 레이어로 저장
- 3단계: 분석과 탐색 기능을 붙임
- 4단계: 그 위에 연구보조 agent를 얹음

이 순서가 중요한 이유는, 지금 프로젝트가 이미 1단계 후반부에 있기 때문이다. 지금 필요한 것은 기능의 폭 확장보다 **데이터 모델의 깊이 확장**이다.

---

## 4. 추천 로드맵

## Phase A. 현재 MVP를 "운영 가능한 기반"으로 다듬기

이 단계는 연구 보조 기능으로 넘어가기 전에 반드시 필요하다.

우선순위:

- 테스트 코드 추가
- OCR 실패/예외 처리 강화
- 검색 결과 패시지 하이라이트
- 대량 컬렉션 처리 시 안정성 점검
- 재처리/재색인 흐름 검증

이 단계의 목표는 "논문 수집과 검색이 흔들리지 않는 상태"다.

### 왜 필요한가

이후의 모든 분석/추출은 결국 `Paper`, `PaperFile`, `Passage`, OCR JSON에 의존한다. 기반이 흔들리면 상위 레이어가 전부 불안정해진다.

---

## Phase B. 구조 보존된 corpus 만들기

지금 가장 중요한 다음 단계다.

현재 DB에는 passage 단위 텍스트가 저장되지만, 앞으로는 OCR JSON의 구조를 더 적극적으로 활용해야 한다. 특히 다음 정보가 중요하다.

- section header
- caption
- figure/table 존재 여부
- page block label

즉, 단순 `text` 저장을 넘어 **문서 구조를 재구성한 derived layer**가 필요하다.

추천 방향:

- `passages`를 유지하되 block/section 성격을 구분하는 메타데이터 추가
- caption, section title, body text를 구분 저장
- 논문 단위 "structured_text JSON" 또는 equivalent derived cache 도입

이 단계가 완료되면 검색 품질도 좋아지고, 이후의 키워드/개체명/관계 추출도 훨씬 쉬워진다.

---

## Phase C. 분석 레이어 추가

idea2를 가장 현실적으로 수용하는 단계다.

이 단계에서는 "보여주기 쉬운 분석"부터 시작하고, 점차 "연구적으로 강한 분석"으로 넘어가면 된다.

### C-1. 바로 구현 가능한 것

- corpus word frequency
- unigram / bigram / trigram
- TF-IDF keyword extraction
- 연도별 키워드 변화
- 저자별 / 컬렉션별 키워드 비교

이건 구현 난이도가 낮고, 사용자가 corpus를 탐색하는 재미도 빠르게 준다.

### C-2. 더 가치 있는 것

- taxon 빈도 집계
- 지질시대명 빈도 집계
- locality / formation 추출
- co-occurrence network
- author collaboration network

여기서부터는 단순 NLP가 아니라 도메인 지식과 결합된 분석이 된다. PaperMeister의 차별점도 이쪽에서 나온다.

### 실무적 판단

tag cloud는 데모용으론 좋지만 중심 기능으로 두기엔 약하다. 우선순위는 다음이 더 높다.

1. n-gram/TF-IDF
2. 도메인 엔티티 추출
3. 네트워크/시계열 분석
4. tag cloud 시각화

---

## Phase D. assertion 기반 지식 레이어

idea1의 핵심은 사실 "키워드 추출"이 아니라 **assertion extraction**이다.

고생물학 문헌에서 정말 중요한 것은 다음과 같은 구조다.

- Taxon A occurs in Formation B
- Specimen C found at Location D
- Taxon A described by Author E
- Taxon A belongs to higher taxon B
- Taxon A assigned to stratigraphic interval C

즉, 앞으로의 핵심 확장은 아래처럼 가는 편이 맞다.

- 엔티티 추출
- 엔티티 정규화
- 관계 추출
- assertion 저장
- 검증/수정 UI

여기서 중요한 점은 처음부터 완전 자동화를 목표로 잡지 않는 것이다.

현실적인 방식:

1. high-recall 후보 추출
2. 정규화
3. 검토 또는 검증
4. 확정 assertion 저장

이렇게 해야 품질과 속도를 모두 잡을 수 있다.

또한 이 단계는 별도 graph DB 없이도 시작 가능하다. 현재 프로젝트 철학과 구현 상태를 보면, 우선은 **SQLite/RDB 기반 assertion 테이블**로 가는 것이 훨씬 적절하다.

---

## Phase E. Research Assistant 레이어

이 단계가 되면 idea1의 비전이 본격적으로 살아난다.

다만 agent는 corpus가 아니라 **도구와 구조화 레이어 위에서** 돌아야 한다.

초기 RA는 다음 정도면 충분하다.

- 질의 입력
- 관련 논문 검색
- 관련 assertion 조회
- 요약 생성
- 근거 논문/페이지 제시

즉, 처음에는 "루프를 도는 자율 에이전트"보다 **stateless tool orchestration**이 더 적절하다.

예:

- "Ordovician trilobite diversity in Korea"
- 관련 논문 검색
- taxon / locality / formation assertion 집계
- 요약 보고서 생성

이 정도만 되어도 이미 단순 검색 앱과는 완전히 다른 가치가 생긴다.

---

## 5. 지금 당장 무엇을 만들면 좋은가

현실적으로는 아래 순서를 추천한다.

### 최우선

- 테스트 보강
- 검색 UX 보강
- OCR 구조 정보 활용을 위한 derived schema 설계

### 그 다음

- corpus analysis CLI 또는 별도 메뉴 추가
- keyword / n-gram / TF-IDF 분석
- 연도별/컬렉션별 비교 리포트

### 그 다음

- taxon / geologic time / locality 추출 파이프라인 프로토타입
- assertion 테이블 설계
- semi-automatic validation 흐름 설계

### 마지막

- 질문 기반 research assistant
- 도구 호출형 요약/탐색 인터페이스

---

## 6. 추천 제품 정체성

앞으로의 PaperMeister는 다음처럼 정의하는 것이 가장 자연스럽다.

**PaperMeister는 개인 논문 컬렉션을 검색 가능한 corpus로 바꾸고, 그 corpus를 구조화된 연구 지식으로 승격시키는 로컬 연구 플랫폼이다.**

이 정의의 장점은 다음과 같다.

- 현재 구현 상태와 모순되지 않는다
- idea1의 장기 비전을 품을 수 있다
- idea2의 분석 기능을 자연스럽게 포함할 수 있다
- "OCR 앱"이나 "검색 앱"에 머무르지 않는다

---

## 7. 최종 판단

현재 프로젝트 상태를 기준으로 보면, 가장 좋은 다음 방향은 다음 셋이다.

1. **MVP 안정화**
2. **구조화 corpus 레이어 추가**
3. **분석/assertion 레이어로 확장**

그리고 Research Assistant는 그 다음이다.

정리하면:

- 지금은 agent를 먼저 만들 시점이 아니다
- 지금은 corpus를 더 잘 저장하고 더 잘 읽어내는 시점이다
- tag cloud 자체보다, 구조화된 키워드/엔티티/관계 분석이 더 중요하다
- PaperMeister의 진짜 잠재력은 "논문 OCR 저장소"가 아니라 "domain-aware research corpus platform"에 있다

이 방향으로 가면 PaperMeister는 단순한 개인 PDF 관리 도구를 넘어, 이후 Trilobase류의 지식 시스템과도 자연스럽게 연결되는 기반 프로젝트가 될 수 있다.
