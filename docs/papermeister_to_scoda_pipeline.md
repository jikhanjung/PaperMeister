# PaperMeister to SCODA Pipeline

**날짜:** 2026-04-03  
**상태:** 초안  
**목적:** PaperMeister에서 구축한 문헌 corpus가 어떻게 SCODA로 배포 가능한 도메인 artifact로 이어질 수 있는지 파이프라인 관점에서 정리

## 1. 문제의식

PaperMeister는 논문을 수집하고 OCR하여 searchable corpus를 만드는 시스템이다.

SCODA는 정규화된 데이터베이스와 메타데이터, 질의, UI manifest를 포함한 self-contained artifact를 배포하고 열람하는 런타임이다.

따라서 중요한 질문은 다음이다.

**PaperMeister에서 만든 corpus는 어떤 중간 단계를 거쳐 SCODA 패키지로 이어질 수 있는가?**

## 2. 핵심 결론

PaperMeister corpus가 곧바로 SCODA 패키지가 되는 것은 아니다.

그 사이에는 반드시 다음 단계가 필요하다.

1. 도메인 엔티티 모델 정의
2. assertion 추출
3. 정규화
4. canonical merge
5. domain database 적재
6. SCODA packaging

즉:

- PaperMeister는 원자료를 읽을 수 있게 만드는 corpus layer
- SCODA는 정제된 domain artifact를 배포하는 runtime layer

이고, 그 사이에 도메인별 knowledge construction 단계가 필요하다.

## 3. 계층 구조

전체 파이프라인은 다음처럼 보는 것이 가장 정확하다.

### Layer 1. Source Layer

- Zotero
- EndNote류 bibliographic records
- local PDF directories
- scanned archives

### Layer 2. PaperMeister Corpus Layer

- source ingest
- sync
- OCR
- raw OCR JSON
- searchable passages
- structured corpus 후보

### Layer 3. Domain Extraction Layer

- entity candidate extraction
- relation/assertion extraction
- bibliography linking
- evidence bundling

### Layer 4. Canonical Domain DB Layer

- normalized taxa
- normalized formations/locations/times
- synonym relations
- bibliographic references
- curated assertions

### Layer 5. SCODA Package Layer

- SQLite DB
- provenance
- named queries
- UI manifest
- entity schema
- dependency metadata

### Layer 6. SCODA Runtime / Distribution Layer

- generic viewer
- MCP access
- web/desktop runtime
- hub distribution

## 4. PaperMeister의 역할

PaperMeister는 다음을 담당한다.

- 문헌 수집
- source provenance 유지
- OCR과 layout 정보 확보
- 전문 검색
- 구조 보존
- 지속적인 corpus 갱신

즉, PaperMeister는 “읽을 수 있는 문헌 corpus”를 만든다.

이 단계의 결과는 가치가 크지만, 아직 SCODA 배포 artifact는 아니다.

왜냐하면 이 상태는 여전히:

- 문헌 중심
- assertion 미정규화 상태
- source-aware but domain-unnormalized 상태

이기 때문이다.

## 5. 중간 단계: Domain Extraction

PaperMeister에서 SCODA로 가기 위해 가장 중요한 중간 단계는 domain extraction layer다.

이 단계에서 필요한 일:

- 어떤 엔티티를 추출할지 정의
- 어떤 관계를 assertion으로 볼지 정의
- OCR/텍스트에서 후보를 뽑기
- bibliographic evidence 연결
- 기존 canonical DB와 대조하기
- 사람 또는 규칙 기반으로 검토하기

예를 들어 고생물학에서는:

- taxon
- formation
- locality
- chronostratigraphic interval
- bibliography
- synonym relation

같은 요소가 핵심이다.

즉 SCODA로 가기 위해서는 “문서를 읽은 상태”에서 “도메인 지식을 정제한 상태”로 올라가야 한다.

## 6. Canonical Domain DB의 역할

이 단계는 PaperMeister corpus에서 나온 assertion과 기존 지식을 합쳐, 하나의 canonical domain DB를 만드는 단계다.

예:

- valid taxon names
- synonym table
- bibliography
- formation/location links
- temporal mapping

이 단계의 결과물은 더 이상 단순 corpus가 아니라:

**질의 가능한 정규화된 도메인 데이터베이스**

가 된다.

이 상태가 되어야 비로소 SCODA 패키지로 깔끔하게 포장할 수 있다.

## 7. SCODA 패키지화

SCODA는 단순 DB 파일 포맷이 아니다.

패키지로 가려면 다음이 필요하다.

- 데이터베이스 스키마
- provenance
- manifest
- named queries
- UI display intent
- dependency metadata

즉, SCODA는 domain DB를 “보여주고 배포하고 재현 가능한 형태”로 만드는 레이어다.

예를 들어:

- `paleocore`
- `trilobase`
- future `brachiobase`

같은 패키지들이 여기에 해당할 수 있다.

## 8. 왜 이 파이프라인이 좋은가

이 분리가 중요한 이유는 다음과 같다.

### 8.1 역할이 명확해진다

- PaperMeister는 corpus OS
- domain DB는 canonical knowledge
- SCODA는 package/runtime

### 8.2 재사용성이 높아진다

같은 PaperMeister corpus에서 여러 domain package가 나올 수 있다.

예:

- trilobite taxonomy package
- paleogeography package
- stratigraphic concept package

### 8.3 package는 더 작고 안정적일 수 있다

원본 corpus 전체를 배포하지 않고, 정제된 결과만 artifact로 배포할 수 있다.

### 8.4 provenance를 유지한 채 배포할 수 있다

SCODA 패키지는 canonical DB이지만, 그 뒤의 evidence chain은 PaperMeister corpus를 통해 계속 추적 가능하다.

## 9. 고생물학 도메인에서의 예시

고생물학 도메인에서는 다음이 자연스러운 흐름이다.

1. PaperMeister가 Treatise, Jell & Adrain, 후속 논문 등에서 corpus 구축
2. taxon/formation/location/bibliography assertion 후보 추출
3. 정규화와 검토
4. canonical database 구축
5. `PaleoBase` 계열 SCODA package 생성
6. SCODA Engine으로 배포/탐색/MCP 제공

즉 Trilobase 같은 artifact는 결국:

**PaperMeister corpus 위에서 만들어지는 도메인 지식 패키지**

로 볼 수 있다.

## 10. 요약

PaperMeister에서 SCODA로 가는 길은 직접 연결이 아니라 계층적 파이프라인이다.

즉:

- PaperMeister = 문헌 corpus 구축
- Domain Extraction = assertion 및 정규화
- Canonical DB = 도메인 지식 구조화
- SCODA = 패키징과 배포

이 구조가 갖춰지면, PaperMeister는 단순 OCR/search 앱이 아니라  
**배포 가능한 연구 artifact를 생산하는 상위 corpus infrastructure**가 된다.
