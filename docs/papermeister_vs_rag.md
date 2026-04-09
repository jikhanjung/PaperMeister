# PaperMeister vs RAG

**날짜:** 2026-04-03  
**상태:** 초안  
**목적:** PaperMeister와 일반적인 RAG 접근의 차이를 제품 및 아키텍처 관점에서 정리

## 1. 문제의식

PaperMeister를 설명할 때, 많은 사람들은 자연스럽게 “그럼 RAG 같은 건가?”라고 생각할 수 있다.

겉으로 보면 둘 다 문서를 다룬다.

- 문서를 모은다
- 텍스트를 읽는다
- 검색한다
- 나중에는 질문에 답할 수도 있다

하지만 PaperMeister와 일반적인 RAG는 중심이 다르다.

## 2. 한 문장 차이

가장 짧게 요약하면:

- RAG는 **질문에 답하기 위한 검색층**
- PaperMeister는 **읽을 수 있는 연구 corpus를 만들고 운영하는 기반층**

즉, RAG는 주로 answer generation에 가깝고,  
PaperMeister는 corpus infrastructure에 가깝다.

## 3. 일반적인 RAG의 특징

일반적인 RAG는 보통 이런 흐름을 갖는다.

1. 문서를 넣는다
2. 문서를 chunk로 나눈다
3. embedding을 만든다
4. 질문이 들어오면 관련 chunk를 꺼낸다
5. LLM이 답을 만든다

이 방식의 중심은:

- retrieval
- answer generation

이다.

즉, 문서는 주로 “질문에 답하기 위한 재료”로 다뤄진다.

## 4. PaperMeister의 중심

PaperMeister의 중심은 다르다.

PaperMeister는 먼저 다음을 해결하려고 한다.

- 논문이 어디에서 오는가
- PDF를 어떻게 읽을 수 있게 만들 것인가
- OCR과 layout 정보를 어떻게 보존할 것인가
- source provenance를 어떻게 유지할 것인가
- corpus를 시간이 지나도 어떻게 계속 갱신할 것인가

즉, 질문 응답 이전에 필요한:

- source ingestion
- sync
- OCR
- canonical corpus
- provenance
- 재처리 가능성

이 핵심이다.

## 5. 문서를 대하는 방식의 차이

## 5.1 일반 RAG

문서를 주로 chunk 단위 텍스트로 다루는 경우가 많다.

- 어떤 source에서 왔는지
- 어떤 문서 구조를 가졌는지
- 어떤 파일에서 추출되었는지

가 상대적으로 약하게 보존되기 쉽다.

## 5.2 PaperMeister

문서를 단순 텍스트 덩어리가 아니라 연구 자산으로 다룬다.

보존하려는 것은 다음과 같다.

- source
- file
- OCR raw result
- page
- section
- caption/body distinction
- provenance

즉, PaperMeister는 문서를 평평하게 펼치기보다  
**구조와 출처를 가진 corpus asset**으로 유지하려 한다.

## 6. Source awareness의 차이

일반적인 RAG 파이프라인에서는:

- 문서를 한 번 넣고
- embedding을 만들고
- 나중에 질의에 쓰는 방식

이 많다.

하지만 PaperMeister는 source-aware system이다.

즉:

- Zotero
- EndNote류 bibliographic record
- local directory

같은 다양한 source를 받아들이고, 각 source에서 새 문헌이 들어오면 sync를 통해 corpus를 계속 업데이트하는 구조를 지향한다.

이건 일회성 문서 투입과는 다르다.

## 7. Corpus lifecycle의 차이

RAG는 흔히 “질문하면 답한다”가 중심이다.

PaperMeister는 그보다 긴 lifecycle을 가진다.

1. source 등록
2. 새 문헌 유입
3. sync
4. OCR
5. corpus 갱신
6. 검색
7. 구조화
8. 향후 분석/추출

즉, PaperMeister는 질의응답 시스템이라기보다  
**계속 자라고 유지되는 corpus 운영 시스템**이다.

## 8. 구조 보존의 차이

학술 논문은 단순 텍스트 블록이 아니다.

특히 다음 구조가 중요하다.

- title
- abstract
- section hierarchy
- figure caption
- table context
- page reference

일반 RAG는 보통 chunk retrieval가 중심이기 때문에 이런 구조를 약하게 다루는 경우가 많다.

PaperMeister는 특히 Chandra2 같은 layout-aware OCR을 활용해,  
이 구조 자체를 이후 활용 가능한 자산으로 보려 한다.

즉, PaperMeister는 “chunk store”보다  
**structured research corpus**에 더 가깝다.

## 9. 장기적 관계

PaperMeister와 RAG는 경쟁 관계라기보다 계층 관계에 가깝다.

관계는 다음처럼 보는 편이 정확하다.

- PaperMeister = corpus / infrastructure layer
- RAG = 그 위에서 가능한 retrieval-and-answer layer 중 하나

즉, PaperMeister 위에 나중에 RAG를 올릴 수는 있지만,  
PaperMeister는 RAG로 환원되지 않는다.

## 10. 마케팅 관점의 차이

마케팅 문장으로 바꾸면 다음처럼 설명할 수 있다.

### 일반 RAG

문서를 넣고 질문에 답하게 한다.

### PaperMeister

흩어진 논문을 읽을 수 있는 corpus로 만들고, 그 corpus를 지속적으로 운영하게 한다.

또는 더 짧게:

- RAG는 답변을 만든다
- PaperMeister는 답변 가능한 연구 코퍼스를 만든다

또는:

- RAG는 문서를 소비한다
- PaperMeister는 문서를 연구 자산으로 축적한다

## 11. 왜 이 차이가 중요한가

이 차이는 단순 설명상의 차이가 아니다.

제품 구조에도 직접 영향을 준다.

PaperMeister에서는 중요하지만 일반적인 RAG 설명에서는 자주 빠지는 것:

- source sync
- OCR cache
- provenance
- canonical paper/file model
- source-aware browsing
- structured corpus persistence

즉, PaperMeister가 진짜로 풀려는 문제는 “질문에 답하기” 이전에 있는:

**논문을 장기적으로 유지 가능한 corpus asset으로 바꾸는 것**

이다.

## 12. 요약

PaperMeister와 RAG의 가장 큰 차이는 다음이다.

RAG는:

- 이미 읽을 수 있는 문서를 전제로 하고
- retrieval과 answer generation에 집중한다

PaperMeister는:

- 읽기 어려운 논문까지 포함해 corpus를 만들고
- source와 provenance를 보존하고
- 그 corpus를 지속적으로 운영하고 확장하는 기반을 만든다

즉, PaperMeister는 RAG의 한 변형이 아니라,  
**좋은 RAG조차 가능하게 만드는 더 아래쪽의 연구 corpus infrastructure**에 가깝다.
