# P01: MVP 아키텍처 및 구현 계획

**날짜:** 2026-03-30
**목표:** PRD 기반 MVP 구현 — PDF 수집, 텍스트 추출, 전문 검색이 가능한 데스크톱 앱

---

## 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.10+ | 과학 문서 처리 생태계 |
| GUI | PyQt6 | 크로스플랫폼 데스크톱 앱 |
| DB | SQLite (FTS5) | 단일 파일 DB, 전문 검색 내장 |
| ORM | Peewee | 경량, SQLite 확장 지원 |
| PDF 처리 | PyMuPDF (fitz) | 텍스트 추출 + 메타데이터 |

---

## 모듈 구조

```
papermeister/
├── __init__.py
├── models.py          # Peewee 모델: Paper, Author, PaperFile, Passage
├── database.py        # DB 초기화, FTS5 가상 테이블 생성
├── ingestion.py       # 디렉토리 스캔, 해시 기반 중복 방지, PDF 등록
├── text_extract.py    # PyMuPDF 텍스트/메타데이터 추출, 패시지 분할
├── search.py          # FTS5 BM25 검색 엔진
└── ui/
    ├── __init__.py
    └── main_window.py # PyQt6 메인 윈도우
main.py                # 엔트리포인트
```

---

## 데이터 흐름

```
[폴더 선택] → scan_directory() → ingest_pdf() (해시 중복 체크)
    → PaperFile(status='pending') 생성
    → process_paper_file()
        → extract_metadata_from_pdf()  → Paper 업데이트
        → extract_text_from_pdf()      → 페이지별 텍스트
        → split_into_passages()        → Passage 레코드 생성
        → FTS5 인덱스 삽입
        → PaperFile(status='processed')
```

---

## 검색 전략

- SQLite FTS5 가상 테이블 `passage_fts`
- 컬럼: title(가중치 10), authors(가중치 5), text(가중치 1), paper_id(UNINDEXED), page(UNINDEXED), passage_id(UNINDEXED)
- BM25 랭킹으로 정렬
- `snippet()` 함수로 매칭 구절 하이라이트

---

## UI 레이아웃

```
+------------------------------------------------------------+
| PaperMeister                                               |
+------------------------------------------------------------+
| File(Import Folder, Exit)                                  |
+------------------------------------------------------------+
| [Search...                              ] [Search][Show All]|
+------------------------------------------------------------+
|  Results (TreeWidget)     |  Detail (TextEdit, readonly)   |
|                           |                                 |
|  - Paper Title 1  2020  3 |  Title / Authors / Year / DOI  |
|  - Paper Title 2  2018  1 |  Matching Passages             |
|  - Paper Title 3  2023  5 |  Full Text by Page             |
+------------------------------------------------------------+
| Status: Papers: N | Passages: M                            |
+------------------------------------------------------------+
```

---

## 구현 순서

1. `models.py` — Peewee 모델 정의
2. `database.py` — DB 초기화 + FTS5
3. `ingestion.py` — PDF 스캔 및 등록
4. `text_extract.py` — 텍스트/메타데이터 추출
5. `search.py` — FTS5 검색
6. `ui/main_window.py` — PyQt6 UI (QThread 비동기 임포트)
7. `main.py` — 엔트리포인트
