# 20260330_001: MVP 초기 구현

**날짜:** 2026-03-30

---

## 요약

PRD만 있던 상태에서 출발하여, 하루 만에 MVP 전체 골격을 구현했다.
PDF 폴더 임포트 → RunPod OCR → SQLite FTS5 검색까지의 전체 파이프라인이 연결되었고,
PyQt6 3-pane GUI로 소스/폴더 트리, 논문 목록, 상세 뷰를 갖추었다.

---

## 기술 스택 결정

| 항목 | 선택 | 이유 |
|------|------|------|
| GUI | PyQt6 | 크로스플랫폼 데스크톱 앱 |
| DB | SQLite + FTS5 | 단일 파일, 전문 검색 내장 |
| ORM | Peewee 4.x | 경량, SQLite 잘 지원 |
| PDF | PyMuPDF (fitz) | 메타데이터 추출 + 페이지 렌더링 |
| OCR | RunPod (Chandra2-vllm) | 서버리스 GPU OCR |

---

## 구현한 모듈

### 1. 데이터 모델 (`models.py`)

6개 테이블: Source → Folder → Paper → PaperFile, Author, Passage

- **Source**: 논문 소스 (directory / zotero)
- **Folder**: 소스 내 폴더 계층 (self-referencing parent FK)
- **Paper**: 논문 메타데이터 + Folder FK
- **PaperFile**: PDF 파일 경로, SHA256 해시, 처리 상태 (pending/processed/failed)
- **Passage**: 페이지별 텍스트 조각

초기에는 Source/Folder 없이 Paper만 있었으나, 폴더 트리 UI 요구에 따라 추가.

### 2. DB 초기화 (`database.py`)

- `DatabaseProxy` + `SqliteDatabase` (Peewee 4.x 호환)
- `create_tables` + FTS5 가상 테이블 자동 생성
- 기존 DB 마이그레이션: `folder_id` 컬럼 없으면 `ALTER TABLE`로 추가

### 3. 수집 (`ingestion.py`)

- `import_source_directory(dir_path)` — 디렉토리 트리 재귀 스캔
  - Source 레코드 생성 (이미 있으면 재사용)
  - 각 서브디렉토리를 Folder로 생성 (계층 구조 유지)
  - PDF 발견 시 SHA256 해시로 중복 체크 후 PaperFile 생성
- 재스캔 지원: 같은 경로 재임포트 시 새 파일만 추가

### 4. OCR (`ocr.py`)

`../fsis2026/scripts/batch_runpod.py`를 참고하여 PaperMeister용으로 재작성.

- `render_page()` — PyMuPDF로 PDF 페이지 → base64 JPEG
- `wake_and_wait()` — 서버리스 워커 cold start 대기
- `ensure_workers_ready()` — 세션당 한 번만 health 체크
- `submit_and_wait()` — async 제출 → 폴링 → 결과 (재시도 + 지수 백오프)
- `ocr_pdf()` — 전체 PDF OCR (배치 처리, PayloadTooLarge 자동 분할)

### 5. 텍스트 추출 (`text_extract.py`)

- `process_paper_file(pf)` — OCR 결과 + 메타데이터를 DB에 저장
- PyMuPDF 텍스트 레이어는 사용하지 않음 (일관성을 위해 항상 OCR)
- PyMuPDF는 PDF 내장 메타데이터(title, author, year) 추출에만 사용
- 텍스트를 단락 단위로 분할하여 Passage로 저장
- FTS5 인덱스에 title(×10), authors(×5), text(×1) 가중치로 삽입

### 6. 검색 (`search.py`)

- FTS5 MATCH + BM25 랭킹
- 쿼리 실패 시 따옴표로 감싼 exact phrase 폴백
- `get_papers_in_folder()`, `get_papers_in_source()` — 폴더/소스별 논문 조회

### 7. UI (`ui/main_window.py`)

3-pane 레이아웃:
```
소스/폴더 트리 | 논문 목록 (Title, Year, Status) | 상세 뷰
```

**메뉴:**
- File > Import Folder (Ctrl+I)
- File > Process Pending (Ctrl+P)
- File > Retry Failed (Ctrl+R)
- File > Exit (Ctrl+Q)

**비동기 처리 (QThread):**
- `ScanWorker` — 디렉토리 스캔 + DB 구조 생성 (빠름)
- `ProcessWorker` — OCR 처리 (느림), 완료 후 논문 목록 자동 갱신

**프로그레스:**
- 상태바 메시지: 현재 작업 파일명
- 프로그레스 바 + 숫자 레이블: `3/15` 형태
- 처리 완료 시 프로그레스 바 자동 숨김

---

## 해결한 문제들

1. **Peewee 4.x 호환성**: `SqliteExtDatabase` 제거됨 → `DatabaseProxy` + `SqliteDatabase` 조합으로 대체
2. **기존 DB 마이그레이션**: `ALTER TABLE paper ADD COLUMN folder_id` 자동 실행
3. **OCR health 체크 중복**: `ensure_workers_ready()`로 세션당 한 번만 체크

---

## 설계 결정 기록

### 항상 OCR 사용 (텍스트 레이어 무시)

처음에는 텍스트 레이어가 있으면 PyMuPDF로 추출하고, 없으면 OCR하는 분기를 두었다.
그러나 텍스트 레이어 품질이 불균일하므로, 일관성을 위해 항상 RunPod OCR로 통일하기로 결정.
PyMuPDF는 메타데이터 추출에만 사용.

### Import 흐름 2단계 분리

- **Scan** (빠름): 폴더 구조 + PaperFile 생성 → 즉시 UI에 반영
- **Process** (느림): OCR → DB 저장 → 백그라운드에서 진행

사용자가 임포트 즉시 폴더 구조와 파일 목록을 볼 수 있고,
OCR은 프로그레스 바로 진행 상황을 확인하면서 기다릴 수 있다.

---

## 현재 파일 구조

```
PaperMeister/
├── main.py                 # 엔트리포인트
├── requirements.txt        # PyQt6, peewee, PyMuPDF, Pillow, requests, python-dotenv
├── .env                    # RUNPOD_ENDPOINT_ID, RUNPOD_API_KEY
├── .gitignore
├── CLAUDE.md
├── HANDOFF.md
├── papermeister_prd.md
├── papermeister/
│   ├── __init__.py
│   ├── models.py           # Peewee 모델 6개
│   ├── database.py         # DB 초기화 + 마이그레이션
│   ├── ingestion.py        # 디렉토리 스캔 + PDF 등록
│   ├── ocr.py              # RunPod OCR 클라이언트
│   ├── text_extract.py     # OCR + 메타데이터 → DB 저장
│   ├── search.py           # FTS5 검색
│   └── ui/
│       ├── __init__.py
│       └── main_window.py  # PyQt6 3-pane UI
└── devlog/
    ├── 20260330_P01_MVP_Architecture_and_Implementation.md
    └── 20260330_001_MVP_Initial_Implementation.md (이 파일)
```

---

## 다음 단계

- RunPod OCR 실제 연동 테스트 (API 키 설정 완료)
- Zotero 연동 모듈 구현
- 검색 결과 매칭 패시지 하이라이트
- 에러 핸들링 보강
