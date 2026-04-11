# P07: 데스크탑 소프트웨어 구현 계획

## 문서 역할

이 문서는 데스크탑 앱의 **구현 계획 문서**다.

즉, 다음을 다룬다.

- `P06`에서 정의한 기능을 어떤 순서로 만들 것인가
- 어떤 레이어와 단계로 나눌 것인가
- 각 단계의 완료 기준은 무엇인가
- 지금 바로 어떤 작업부터 시작해야 하는가

기능 범위와 정책 자체는 `P06`을 기준으로 한다.

## 전제

이 계획은 다음 판단을 전제로 한다.

- searchable corpus는 OCR만으로 충분하지 않다.
- 서지정보는 corpus usability의 핵심 레이어다.
- source provenance를 유지한 UI가 현재 데이터 모델에 더 정직하다.
- vision pass, standalone promote, Zotero write-back은 중요하지만 정책 제어가 필요한 자동화 레이어다.

## 구현 목표

`P06`의 기능 정의를 구현 가능한 순서로 분해해,
작동하는 데스크탑 앱을 단계적으로 완성한다.

## 구현 전략

### 1. Foundation first

- source 연결
- OCR 캐시
- 상태 모델
- DB 재구성 가능성

이 네 가지를 먼저 안정화한다.

### 2. Bibliographic usability early

서지정보 추출은 뒤로 미루지 않는다.
검색 가능한 corpus의 실질적 가치가 여기서 올라가기 때문이다.

### 3. UI는 source-first

canonical merge가 성숙하기 전까지는 source별 구조와 operational view를 같이 제공한다.

### 4. 자동화는 단계적으로

추출 저장은 먼저 넣고,
promote/write-back/vision은 통제 가능한 흐름으로 뒤에 붙인다.

## 구현 레이어

### Layer 1. Corpus Foundation

- source 등록
- source 스캔/동기화
- PDF hash 계산
- OCR 실행
- OCR JSON 캐시
- 처리 상태 추적

### Layer 2. Bibliographic Layer

- OCR JSON 기반 서지정보 추출
- `PaperBiblio` 저장
- confidence / doc_type / needs_visual_review 처리
- Paper 반영 규칙 정의

### Layer 3. UI Layer

- source-first navigation
- operational views
- paper list
- detail panel
- preferences
- process window

### Layer 4. Search Layer

- FTS5 BM25
- metadata + text 혼합 검색
- filters / sorting / snippet

### Layer 5. Controlled Automation Layer

- review queue
- vision pass
- standalone promote
- Zotero write-back

### Layer 6. Hardening Layer

- retry/resume/concurrency
- failure taxonomy
- backend switching
- encrypted PDF 대응
- 테스트 코드

## 단계별 계획

## Phase 1. Core Corpus Foundation

### 목표

source, OCR, 캐시, 상태 모델을 먼저 안정화한다.

### 작업 항목

- Zotero source 추가/동기화 흐름 정리
- Local directory source 추가/스캔 흐름 정리
- SHA256 hash 계산과 dedup 정리
- `PaperFile.status` 기본 상태 정리
- OCR JSON 캐시 저장/재사용 정리
- DB 재구성 경로 점검
- migration 경로 점검

### 완료 기준

- source 추가 후 tree/list가 일관되게 생성된다
- 동일 PDF는 source와 무관하게 같은 OCR JSON을 재사용한다
- pending/processed/failed 상태가 일관된다
- DB를 지워도 source와 OCR JSON으로 복구 가능하다

## Phase 2. Bibliographic Corpus Layer

### 목표

서지정보를 corpus의 기본 usability 레이어로 구현한다.

### 작업 항목

- OCR JSON 첫 1~3페이지 기반 추출 연결
- `PaperBiblio` 저장 구조 정리
- text model 설정 연결
- confidence / doc_type / needs_visual_review 규칙 정리
- `PaperBiblio -> Paper` 반영 규칙 문서화
- review 대상 식별 규칙 정리

### 완료 기준

- processed 문서에 대해 `PaperBiblio` 생성 가능
- title/authors/year/journal/doc_type가 구조적으로 보관된다
- high confidence와 review 대상이 구분된다

## Phase 3. Desktop MVP UI

### 목표

핵심 흐름을 감당하는 기본 GUI를 완성한다.

### 작업 항목

- 좌측 `Library / Sources` 구조 구현
- middle list와 right detail 연동
- status badge/icon 표시
- provenance 표시
- preferences dialog 구현
- OCR process window 구현

### 완료 기준

- source 추가 후 탐색이 가능하다
- operational view에서 pending/processed/failed를 바로 볼 수 있다
- 상세 패널에서 metadata + OCR preview + provenance를 함께 본다

## Phase 4. Search and Retrieval

### 목표

corpus를 다시 찾고 활용하는 경험을 완성한다.

### 작업 항목

- FTS5 BM25 검색 입력/실행
- metadata + text 혼합 검색
- source/doc_type/status 필터
- relevance/year/recent 정렬
- snippet 표시

### 완료 기준

- full-text와 metadata 검색이 모두 가능하다
- 결과 해석에 필요한 provenance와 상태가 보인다

## Phase 5. Review and Controlled Automation

### 목표

자동화 결과를 사용자가 통제할 수 있게 만든다.

### 작업 항목

- review queue 구현
- current metadata vs extracted metadata diff
- approve/edit/reject 흐름
- standalone promote 승인 흐름
- Zotero write-back 확인 흐름

### 완료 기준

- 자동 추출 결과를 검토 후 반영할 수 있다
- write-back이 무분별하게 동작하지 않는다

## Phase 6. Accuracy and Operations Hardening

### 목표

대량 운영과 예외 처리를 안정화한다.

### 작업 항목

- batch OCR retry/resume/concurrency 반영
- OCR backend switch: serverless / pod
- 실패 유형 세분화
- encrypted/broken PDF 처리
- 처리 통계/비용 추정 표시
- 테스트 코드 추가

### 완료 기준

- 대량 OCR에서 중단 후 복구가 가능하다
- reserved GPU와 serverless를 모두 운용할 수 있다
- 실패 원인을 사용자가 파악할 수 있다

## 상태 모델 초안

기본 상태:

- `pending`
- `processed`
- `failed`
- `needs_review`
- `promoted`
- `writeback_pending`

세분화 후보:

- `download_failed`
- `ocr_failed`
- `llm_failed`
- `writeback_failed`

## UI 구현 우선순위

1. source tree
2. paper list
3. detail panel
4. process window
5. preferences dialog
6. search UI
7. review queue

## 바로 해야 할 일

- `P06` 기준으로 범위 밖 기능과 보강 기능을 다시 체크
- Preferences 스키마를 현재 backend 구조에 맞게 확정
- `PaperBiblio -> Paper` 반영 정책 문서 작성
- `Zotero write-back` 정책 문서 작성
- UI 화면별 액션/상태 표 작성
- MVP 마일스톤 체크리스트 작성

## 결론

P07의 역할은 `P06`을 구현 가능한 순서로 바꾸는 데 있다.

정리하면 구현 순서는 다음과 같다.

1. corpus 기반을 안정화한다
2. 서지정보 레이어를 붙인다
3. GUI를 얹는다
4. 검색을 완성한다
5. review와 write-back을 통제된 방식으로 붙인다
6. 대량 운영과 예외 처리를 강화한다

즉, `P06`이 무엇을 만들지 정하는 문서라면,
`P07`은 그것을 실제로 어떻게 완성할지 정하는 문서다.
