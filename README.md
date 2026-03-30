# PaperMeister

학술 논문 PDF 컬렉션을 검색 가능한 지식 베이스로 변환하는 데스크톱 앱.

## 주요 기능

- **PDF 임포트**: 로컬 폴더 구조를 그대로 반영하여 논문 등록
- **OCR**: RunPod 서버리스 GPU (Chandra2-vllm)를 통한 전문 텍스트 추출
- **전문 검색**: SQLite FTS5 기반 BM25 랭킹 검색
- **3-pane UI**: 소스/폴더 트리 | 논문 목록 | 상세 뷰

## 설치

```bash
pip install -r requirements.txt
```

### 필수 설정

프로젝트 루트에 `.env` 파일 생성:

```
RUNPOD_ENDPOINT_ID=your_endpoint_id
RUNPOD_API_KEY=your_api_key
```

## 실행

```bash
python main.py
```

## 사용법

| 동작 | 단축키 |
|------|--------|
| 폴더 임포트 | Ctrl+I |
| 미처리 파일 OCR | Ctrl+P |
| 실패한 파일 재시도 | Ctrl+R |
| 종료 | Ctrl+Q |

1. **File > Import Folder** — PDF가 있는 폴더 선택
2. 폴더 구조가 즉시 왼쪽 트리에 표시되고, OCR이 백그라운드에서 시작
3. 프로그레스 바로 진행 상황 확인
4. 완료 후 검색창에서 전문 검색

## 기술 스택

- **GUI**: PyQt6
- **DB**: SQLite + FTS5
- **ORM**: Peewee
- **PDF**: PyMuPDF
- **OCR**: RunPod (Chandra2-vllm)

## 프로젝트 구조

```
papermeister/
├── models.py        # DB 모델 (Source, Folder, Paper, Author, PaperFile, Passage)
├── database.py      # DB 초기화 + 마이그레이션
├── ingestion.py     # 디렉토리 스캔 + PDF 등록
├── ocr.py           # RunPod OCR 클라이언트
├── text_extract.py  # OCR 결과 + 메타데이터 → DB 저장
├── search.py        # FTS5 검색
└── ui/
    └── main_window.py
```
