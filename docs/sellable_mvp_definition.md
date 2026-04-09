# PaperMeister 판매 가능한 MVP 정의

**날짜:** 2026-04-03  
**상태:** 초안  
**목적:** 미래 비전과 구분되는, 실제로 판매나 파일럿 제안이 가능한 최소 제품 범위 정의

## 1. 문제

PaperMeister의 장기 비전은 크다.

- 구조화 corpus
- 분석 레이어
- assertion extraction
- research assistant

하지만 이 모든 것이 갖춰져야만 제품을 판매할 수 있는 것은 아니다.

오히려 판매 가능한 MVP는:

**지금 가장 아픈 문제 하나를 확실히 해결하는 최소 범위**

여야 한다.

## 2. MVP가 해결해야 할 핵심 문제

현 시점에서 PaperMeister가 해결할 수 있는 가장 강한 문제는 다음이다.

**흩어진 PDF와 reference source를 버리지 않고, 최소한 searchable corpus로 바꾸는 것**

즉, 사용자는:

- 기존 Zotero나 폴더를 버리지 않고
- 스캔본과 오래된 PDF까지 포함해
- 자신의 문헌 컬렉션을 다시 찾고 활용할 수 있게 되어야 한다

## 3. 판매 가능한 MVP의 약속

PaperMeister의 판매 가능한 MVP는 다음 약속을 할 수 있어야 한다.

- 기존 문헌 관리 방식을 버릴 필요가 없다
- PDF와 스캔본을 OCR 기반으로 searchable하게 만든다
- 한 번 corpus로 만든 자료를 이후에도 계속 다시 찾고 활용할 수 있다

이 정도면 이미 개인 연구자와 소규모 연구실에게 명확한 가치를 줄 수 있다.

## 4. MVP에 꼭 필요한 기능

최소한 필요한 기능은 다음이다.

- source 1~2종 지원
- PDF ingest
- OCR 처리 및 캐시
- 전문 검색
- 기본 상세 뷰
- source별 browse
- 재처리 가능
- 최소한의 처리 안정성

현실적으로는:

- Zotero + local directory

정도만 잘 되어도 충분히 초기 MVP가 될 수 있다.

## 5. 있으면 좋은 기능

- pending / failed 처리 상태 표시
- search snippet
- source provenance 표시
- 대량 처리 안정성 보강

이 기능들은 판매 가능성을 높여주지만, 반드시 모든 고급 기능이 필요한 것은 아니다.

## 6. 아직 없어도 되는 기능

초기 판매/파일럿 시점에서 없어도 되는 것:

- source 간 자동 dedup 완성도
- 완전한 canonical unified paper view
- 연구실 협업 기능 전체
- 개인/공용 annotation 공유
- entity/relation extraction
- assistant 기능
- 고급 시각화

이들은 확장 포인트이지, 현재 MVP의 필수 조건은 아니다.

## 7. 판매 가능한 이유

이 MVP가 팔릴 수 있는 이유는 기능이 많아서가 아니다.

다음 세 가지가 바로 체감되기 때문이다.

1. 이미 가진 PDF가 다시 살아난다
2. 기존 워크플로우를 부수지 않는다
3. 스캔본까지 searchable하게 된다

즉, MVP의 강점은 breadth가 아니라  
**즉시 체감되는 utility**다.

## 8. 개인용과 연구실용에서의 해석

개인용에서는:

- “내 PDF 아카이브를 searchable하게 해주는 도구”

로 팔릴 수 있다.

연구실용에서는:

- “연구실 자료 일부를 searchable corpus로 만들어주는 파일럿 도구”

로 파일럿 제안이 가능하다.

다만 연구실에 팔려면 최소한 다음 설명이 가능해야 한다.

- 기존 시스템을 파괴하지 않음
- source provenance를 유지함
- 설치와 운영이 과도하게 복잡하지 않음
- OCR 비용 정책이 명확함

## 9. 비전 데모와 MVP의 차이

PaperMeister에서는 다음 둘을 구분해야 한다.

## 판매 가능한 MVP

- OCR 기반 searchable corpus builder

## 비전 데모

- 구조화/분석/assertion/assistant까지 확장되는 미래 플랫폼

이 둘을 분리해야 “아직 다 안 됐으니 못 판다”는 함정에서 벗어날 수 있다.

## 10. 한 문장 정의

PaperMeister의 판매 가능한 MVP는:

**Zotero나 PDF 폴더를 버리지 않고, 스캔본까지 포함한 논문 아카이브를 OCR 기반 searchable corpus로 바꿔주는 로컬 도구**

정도로 정의할 수 있다.

## 11. 요약

판매 가능한 MVP는 미래 비전 전체가 아니라:

- multi-source 중 일부만 잘 지원하고
- OCR과 검색이 명확히 유용하며
- 기존 워크플로우를 부수지 않는

최소 제품이어야 한다.

즉, PaperMeister의 초기 판매 포인트는  
**“고급 지식 추출”이 아니라 “이미 가진 문헌을 다시 쓸 수 있게 만드는 것”**이다.
