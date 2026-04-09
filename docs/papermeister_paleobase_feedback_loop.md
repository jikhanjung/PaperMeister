# PaperMeister and PaleoBase Feedback Loop

**날짜:** 2026-04-03  
**상태:** 초안  
**목적:** PaperMeister와 Trilobase 계열 프로젝트의 상호보완 관계를 정리하고, 이를 장기적으로 `PaleoBase`라는 더 큰 프레임 안에서 해석

## 1. 문제의식

처음에는 다음처럼 보일 수 있다.

- PaperMeister가 문헌 corpus를 만든다
- 그 corpus에서 Trilobase 같은 structured DB를 만든다

즉, PaperMeister가 upstream이고 Trilobase가 downstream인 단방향 구조처럼 보인다.

하지만 실제로는 더 강한 구조가 가능하다.

**PaperMeister와 Trilobase 계열 프로젝트는 상호보완적이며, 서로의 품질을 높이는 feedback loop를 만들 수 있다.**

## 2. Trilobase를 더 큰 틀에서 보기

현재 이름은 `Trilobase`지만, 장기적으로는 이것을 더 큰 `PaleoBase` 프레임 안에서 보는 것이 자연스럽다.

이 관점에서 보면:

- `PaleoBase` = 고생물학 도메인 지식 계층 전체
- `Trilobase` = 그 안의 trilobite-specific package 또는 module

즉, Trilobase는 독립 프로젝트일 수 있지만, 동시에 PaleoBase family의 첫 사례로 볼 수 있다.

가능한 future package 예:

- Trilobase
- Brachiobase
- Graptolitebase
- PaleoCore
- Stratibase 계열

## 3. 기본 역할 분담

### PaperMeister의 역할

- 문헌 수집
- multi-source sync
- OCR
- searchable corpus 구축
- source provenance 유지
- 구조화 가능한 raw/derived text 확보

### PaleoBase 계열의 역할

- 도메인 엔티티 정규화
- synonym/relationship 모델링
- canonical taxonomy/formation/location/bibliography 구축
- queryable domain knowledge 제공
- SCODA package 배포

즉:

- PaperMeister는 corpus infrastructure
- PaleoBase는 domain knowledge infrastructure

이다.

## 4. 왜 상호보완적인가

이 둘은 서로 다른 문제를 푼다.

### PaperMeister만 있을 때의 한계

- 문헌은 읽을 수 있다
- 검색은 된다
- 하지만 추출 결과의 정규화 기준이 약하다
- taxon/synonym/formation 같은 도메인 엔티티는 noisy할 수 있다

### Trilobase/PaleoBase만 있을 때의 한계

- 정규화된 도메인 지식은 있다
- 하지만 새 문헌이 지속적으로 들어오는 ingestion 경로가 약하다
- 새로운 사실을 corpus 규모로 포착하기 어렵다

즉:

- PaperMeister는 유입과 탐색에 강하고
- PaleoBase는 정규화와 검증에 강하다

이 둘이 결합될 때 가장 강해진다.

## 5. Feedback Loop 구조

가장 자연스러운 루프는 다음과 같다.

1. PaperMeister가 새로운 문헌을 ingest/OCR
2. 문헌에서 taxon/location/formation/bibliography/assertion 후보 추출
3. PaleoBase 계열 DB와 대조하여 정규화 시도
4. 충돌, 미매칭, 신규 후보를 검토
5. canonical domain DB 업데이트
6. 업데이트된 PaleoBase가 다시 PaperMeister extraction의 grounding reference가 됨

즉:

- PaperMeister는 PaleoBase를 만들어낼 수 있고
- PaleoBase는 다시 PaperMeister가 더 정확하게 추출하도록 돕는다

이건 단순 upstream/downstream보다 훨씬 강한 구조다.

## 6. 추출 단계에서 PaleoBase가 주는 이점

문헌 추출은 그냥 LLM만으로 하면 흔들리기 쉽다.

특히 고생물학에서는:

- taxon 표기 변형
- synonym 문제
- formation 표기 흔들림
- locality 표기 다양성
- bibliography 매칭 난이도

가 크다.

이때 PaleoBase 계열 DB가 있으면 다음이 가능해진다.

- valid taxon name 확인
- synonym 후보 대조
- formation normalized name 매칭
- 기존 locality vocabulary와 비교
- 이미 존재하는 bibliography와 연결

즉, PaleoBase는 extraction의 품질을 올려주는  
**domain grounding layer**가 된다.

## 7. 검증과 확장 측면의 이점

이 구조의 장점은 단순 정확도 향상만이 아니다.

### 7.1 검증 비용 감소

완전히 백지 상태에서 검토하는 것보다, 기존 canonical DB와 비교하면서 검토하는 편이 훨씬 싸다.

### 7.2 신규 지식 탐지 가능

기존 DB에 없는 taxon, relation, bibliography를 “새로운 후보”로 더 쉽게 포착할 수 있다.

### 7.3 도메인 package family 확장

Trilobase에서 끝나지 않고, PaleoBase family 전체로 확장 가능한 구조가 된다.

## 8. 왜 `PaleoBase`라는 이름이 유용한가

`Trilobase`는 구체적이고 강한 이름이지만, 범위는 명확히 trilobites에 한정된다.

반면 `PaleoBase`라는 이름은:

- 더 넓은 고생물학 도메인 인프라를 포괄할 수 있고
- Trilobase를 그 안의 대표 패키지로 위치시킬 수 있으며
- PaperMeister와의 연결도 더 자연스럽게 설명할 수 있다

즉:

- PaperMeister = corpus layer
- PaleoBase = paleontology knowledge layer
- Trilobase = PaleoBase의 한 핵심 package

라는 구조가 된다.

## 9. 장기적 아키텍처 해석

이 관계를 장기적으로 보면:

- PaperMeister는 문헌 기반 원자료를 계속 흡수
- PaleoBase는 정규화된 도메인 knowledge layer로 성장
- SCODA는 그 결과를 재현 가능하고 배포 가능한 artifact로 만듦

즉 세 층은 다음처럼 연결된다.

- PaperMeister = corpus ingestion / sync / OCR
- PaleoBase = normalized paleontological knowledge
- SCODA = packaging / runtime / distribution

## 10. 요약

PaperMeister와 Trilobase 계열 프로젝트의 관계는 단방향이 아니다.

PaperMeister는:

- 새로운 문헌 corpus를 공급하고
- 추출 가능한 raw evidence를 제공한다

PaleoBase 계열은:

- 정규화 기준을 제공하고
- extraction의 품질을 높이며
- canonical knowledge layer를 형성한다

즉, 둘은 서로를 강화하는 feedback loop를 형성할 수 있다.

장기적으로는 `Trilobase`를 `PaleoBase`라는 더 큰 프레임 안에 두는 것이 자연스럽고,  
이 구조는 PaperMeister를 단순 corpus 도구가 아니라  
**도메인 knowledge system을 지속적으로 공급하는 research infrastructure**로 위치시킨다.
