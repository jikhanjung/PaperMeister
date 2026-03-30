# PaperMeister

학술 논문 PDF 컬렉션을 검색 가능한 지식 베이스로 변환하는 데스크톱 앱.

## 주요 기능

- **PDF 임포트**: 로컬 폴더 구조를 그대로 반영하여 논문 등록
- **Zotero 연동**: Zotero 라이브러리의 컬렉션/논문을 직접 가져오기
- **OCR**: RunPod 서버리스 GPU (Chandra2-vllm)를 통한 전문 텍스트 추출 (병렬 처리)
- **전문 검색**: SQLite FTS5 기반 BM25 랭킹 검색
- **3-pane UI**: 소스/폴더 트리 | 논문 목록 | 상세 뷰

## 설치

```bash
pip install -r requirements.txt
```

## 설정

**File > Preferences** 에서 설정:

- **RunPod OCR**: Endpoint ID + API Key
- **Zotero** (선택): User ID + API Key ([zotero.org/settings/keys](https://www.zotero.org/settings/keys))

설정은 `~/.papermeister/preferences.json`에 저장됩니다.

## 실행

```bash
python main.py
```

## 사용법

| 동작 | 단축키 |
|------|--------|
| 폴더 임포트 | Ctrl+I |
| Zotero 임포트 | Ctrl+Z |
| 미처리 파일 OCR | Ctrl+P |
| 실패한 파일 재시도 | Ctrl+R |
| 종료 | Ctrl+Q |

### 로컬 폴더
1. **File > Import Folder** — PDF가 있는 폴더 선택
2. 폴더 구조가 왼쪽 트리에 표시되고, OCR이 백그라운드에서 시작

### Zotero
1. **File > Preferences** — Zotero User ID + API Key 입력
2. 시작 시 컬렉션 구조가 자동으로 왼쪽 트리에 표시
3. 컬렉션 클릭 → 아이템 목록 자동 가져오기
4. **File > Import from Zotero** 또는 **Process Pending** → PDF 다운로드 + OCR

### 검색
- 상단 검색창에서 전문 검색 (BM25 랭킹)

## 기술 스택

- **GUI**: PyQt6
- **DB**: SQLite + FTS5
- **ORM**: Peewee
- **PDF**: PyMuPDF
- **OCR**: RunPod (Chandra2-vllm)
- **Zotero**: pyzotero

## 프로젝트 구조

```
papermeister/
├── models.py          # DB 모델 (Source, Folder, Paper, Author, PaperFile, Passage)
├── database.py        # DB 초기화 + 마이그레이션
├── ingestion.py       # 디렉토리/Zotero 스캔 + Paper/PaperFile 등록
├── ocr.py             # RunPod OCR 클라이언트 (병렬 처리, health check)
├── text_extract.py    # OCR 결과 + 메타데이터 → DB 저장
├── search.py          # FTS5 검색
├── preferences.py     # 설정 파일 읽기/쓰기
├── zotero_client.py   # Zotero API 래퍼 (pyzotero)
└── ui/
    ├── main_window.py          # 메인 3-pane UI
    ├── process_window.py       # OCR 처리 진행 윈도우
    ├── preferences_dialog.py   # 설정 다이얼로그
    └── zotero_import_dialog.py # Zotero 컬렉션 선택 다이얼로그
```
