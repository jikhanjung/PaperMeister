# P06: 데스크탑 애플리케이션 MVP 기능 정의

## 문서 역할

이 문서는 데스크탑 앱의 **기능 정의 문서**다.

즉, 다음을 다룬다.

- 무엇을 만들 것인가
- 무엇을 MVP에 포함할 것인가
- 각 기능은 어떤 사용자 가치를 제공하는가
- 어떤 정책과 제약을 유지해야 하는가

구현 순서, 단계별 착수 계획, 완료 기준은 `P07`에서 다룬다.

## 배경

세션 1~6을 거치며 다음 파이프라인이 실제로 검증되었다.

- PDF 수집
- OCR 실행 및 JSON 캐시 저장
- LLM 기반 서지정보 추출
- Zotero read/write 연동
- standalone PDF promote
- vision pass 기반 예외 처리

이 경험을 바탕으로 데스크탑 앱 MVP의 기능 범위를 확정한다.

## 제품 정의

PaperMeister 데스크탑 앱은:

**기존 Zotero나 로컬 PDF 폴더를 버리지 않고, OCR과 서지정보 정리를 통해 연구용 corpus를 구축하고 다시 활용하게 만드는 로컬 소프트웨어**

로 정의한다.

여기서 핵심은 다음 두 가지다.

- OCR만으로 corpus를 만드는 데서 끝나지 않는다.
- 서지정보를 정리해 corpus를 실제로 해석하고 검색하고 검토할 수 있게 만든다.

## 핵심 원칙

- **OCR JSON이 source of truth**: `~/.papermeister/ocr_json/{sha256}.json`이 기준 데이터다.
- **DB는 재구성 가능**: source와 OCR JSON이 있으면 DB를 다시 만들 수 있어야 한다.
- **비파괴**: 원본 PDF는 수정하지 않는다.
- **서지정보는 핵심 기능**: searchable corpus의 usability를 결정하는 기본 레이어로 본다.
- **보수적 자동화**: 불확실한 결과는 review 대상으로 남기고, 외부 시스템 반영은 신중하게 한다.
- **source-first browsing**: provenance를 숨기지 않고 source 구조를 유지한다.

## MVP 핵심 사용자 가치

MVP는 최소한 다음 가치를 제공해야 한다.

- 기존 PDF 아카이브를 다시 검색 가능한 corpus로 만든다.
- 서지정보가 정리되어 검색 결과를 사람이 해석할 수 있게 한다.
- Zotero나 폴더 구조를 버리지 않고 그대로 활용하게 한다.
- OCR, 추출, 반영 과정을 비파괴적으로 운영하게 한다.

## MVP 기능 범위

## 1. Data Source 관리

두 종류의 source를 지원한다.

### Zotero

- pyzotero 기반 read/write 연동
- 컬렉션 트리 동기화
- parent item과 attachment 매칭
- PDF는 임시 다운로드 후 처리
- 필요 시 로컬 Zotero storage 경로 사용

### Local directory

- 폴더 구조 스캔
- `Source/Folder/Paper/PaperFile` 생성
- SHA256 hash 기반 dedup
- 원본 파일은 제자리 유지

### 기능 목적

- 사용자가 기존 문헌 관리 방식을 버리지 않게 한다.
- source provenance를 유지한 채 corpus를 구성하게 한다.

## 2. OCR 처리

PDF를 OCR JSON으로 변환한다.

### 기본 정책

- 출력은 `~/.papermeister/ocr_json/{sha256}.json`
- 같은 PDF는 같은 hash를 사용
- 캐시가 있으면 OCR를 재실행하지 않음
- 처리 상태는 `pending / processed / failed`를 기본으로 관리

### 지원 backend

- RunPod serverless
- Reserved GPU Pod

### 추가 정책

- parent item이 있는 Zotero PDF는 JSON sibling upload를 옵션으로 허용
- OCR 결과는 장기 재활용 가능한 자산으로 취급

### 기능 목적

- 스캔본과 오래된 PDF를 corpus로 편입한다.
- source와 무관한 공통 텍스트 레이어를 확보한다.

## 3. 서지정보 추출

OCR JSON을 기반으로 제목, 저자, 연도, 저널 등 메타데이터를 추출한다.

이 기능은 MVP의 핵심 범위에 포함한다.

### 추출 스키마

```text
title, authors[], year, journal, doi, abstract,
doc_type (article|book|chapter|thesis|report|journal_issue|unknown),
language, confidence (high|medium|low), needs_visual_review, notes
```

### 기본 추출

- OCR JSON 첫 1~3페이지 기반 텍스트 추출
- `PaperBiblio`에 비파괴적으로 저장
- source 필드로 모델/버전 구분

### 정확도 보강

- low confidence 또는 visual ambiguity가 있는 경우 별도 review 대상으로 분리
- vision pass는 지원하되, MVP 핵심보다는 보강 기능으로 본다

### 기능 목적

- corpus를 단순 텍스트 저장소가 아니라 연구용 자료 집합으로 만든다.
- 검색 결과를 사람이 해석하고 필터링할 수 있게 한다.

## 4. 검색과 탐색

MVP에는 검색을 포함한다.

### 검색 범위

- full-text search
- title/authors/year/journal 기반 검색
- 상태, source, doc_type 기반 필터

### 탐색 범위

- source별 browse
- corpus-wide operational views
- 상태별 목록 확인

### 기능 목적

- corpus를 실제로 다시 찾고 활용하게 만든다.
- OCR와 서지정보 레이어를 UI에서 연결한다.

## 5. 로컬 DB

`~/.papermeister/papermeister.db`를 사용한다.

### 기본 구조

```text
Source -> Folder -> Paper -> PaperFile
                       -> Author
                       -> Passage -> passage_fts
                       -> PaperBiblio
```

### 정책

- 조회와 운영을 위한 로컬 상태 저장소
- source와 OCR JSON으로 재구성 가능해야 함
- 자동 마이그레이션 지원

## 6. 설정

`~/.papermeister/preferences.json`

### 주요 설정

- OCR backend
- RunPod endpoint / API key
- Pod URL
- Zotero user ID / API key
- Zotero storage path
- text model
- vision model
- JSON upload 여부

### 정책

- GUI에서 관리
- `.env` 대신 사용자 설정 파일 사용

## 7. 데스크탑 UI

MVP UI는 3-pane 구조를 기본으로 한다.

### 좌측

- `Library`
- `Sources`

`Library` 예시:

- All Files
- Pending OCR
- Processed
- Failed
- Needs Review
- Recently Added

`Sources` 예시:

- Zotero collection tree
- Local directory folder tree

### 가운데

- 현재 선택 기준에 맞는 paper/file 목록
- status, title, authors, year, source 표시

### 우측

- 메타데이터
- OCR 텍스트 preview
- provenance
- 최신 `PaperBiblio` 결과

### 별도 처리 창

- OCR 진행률
- 로그
- 실패/재시도 현황

## 8. 자동화 및 외부 반영 정책

자동화는 허용하되, 정책상 구분한다.

### MVP에 포함되는 자동화

- high confidence 서지정보 추출 저장
- 기본 review 대상 분리

### MVP 보강 기능

- standalone PDF promote
- Zotero write-back

### 정확도 보강 기능

- vision pass
- journal issue 특수 처리

## MVP 범위 정리

### MVP 핵심

- source 관리
- OCR 처리
- OCR 캐시
- 서지정보 추출
- 검색
- source-first browse
- provenance 표시

### MVP 보강

- review queue 기본 버전
- standalone promote
- Zotero write-back

### MVP 이후

- PDF viewer + passage highlight
- hybrid search
- 자연어 질의 해석
- entity extraction
- relation extraction

## 사용자 워크플로

1. source 추가
2. source 스캔 또는 동기화
3. pending PDF 처리
4. OCR JSON 저장 및 재사용
5. 서지정보 추출
6. 검색 및 탐색
7. 필요 시 review 후 promote 또는 write-back

## 결론

P06의 결론은 단순하다.

PaperMeister 데스크탑 MVP는 OCR 도구만이 아니라,
**서지정보까지 정리된 연구용 corpus를 구축하고 탐색하게 만드는 데스크탑 소프트웨어**여야 한다.

즉, MVP의 핵심은 다음 세 가지를 함께 제공하는 것이다.

- corpus 생성
- corpus 이해 가능성 확보
- corpus 재활용 가능성 확보
