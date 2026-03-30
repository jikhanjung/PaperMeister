# 20260330_002: OCR 파이프라인 수정 및 처리 UI 개선

**날짜:** 2026-03-30

---

## 요약

Chandra2-vllm OCR 응답 구조에 맞춰 파이프라인을 수정하고,
raw OCR JSON 보존, 캐시 기반 재처리, 독립 처리 윈도우 등을 구현했다.

---

## OCR 응답 구조 대응

### 문제
Chandra2-vllm의 실제 응답 구조가 예상과 달랐다.

- **예상:** `page_data.text` (단순 텍스트)
- **실제:** `page_data.markdown` (마크다운 텍스트) + `page_data.chunks` (구조화 블록 배열)

```json
{
  "pages": [{
    "page": 0,
    "markdown": "full page text...",
    "chunks": [
      {"bbox": [...], "content": "<h2>Title</h2>", "label": "Section-Header"},
      {"bbox": [...], "content": "<p>body text</p>", "label": "Text"}
    ],
    "duration_ms": 1234,
    "page_box": [...]
  }]
}
```

label 종류: Caption, Equation-Block, Figure, Image, List-Group, Page-Footer, Page-Header, Section-Header, Table, Text

### 수정
`ocr.py`에서 텍스트 추출 시 `markdown` → `text` 순 fallback:
```python
text = (page_data.get('markdown') or page_data.get('text') or '').strip()
```

---

## Raw OCR JSON 보존

PRD 원칙 "Store first, understand later"에 따라, RunPod 원본 응답을 파일로 보존.

- 저장 위치: `~/.papermeister/ocr_json/{sha256_hash}.json`
- atomic write (tempfile → rename)
- `ocr_pdf()` 반환값 변경: `list[dict]` → `(results, raw_result)` 튜플

---

## 캐시 기반 재처리

`process_paper_file()` 시작 시:
1. `~/.papermeister/ocr_json/{hash}.json` 존재 확인
2. 있으면 → JSON 로드, RunPod 호출 스킵
3. 없으면 → RunPod OCR 호출 → JSON 저장

기존 passage/author/FTS 데이터는 재처리 시 삭제 후 재생성 (멱등성 보장).

### 관련 메뉴
- **Reindex from Cache** — passage가 없고 JSON 캐시가 있는 파일만 재처리
- **Reprocess All** — 모든 파일 재처리 (캐시 있으면 OCR 스킵)
- **Retry Failed** — failed 파일을 pending으로 리셋 후 재처리

---

## 독립 처리 윈도우 (ProcessWindow)

`process_window.py` 신규 생성. 비모달 윈도우로 메인 창과 독립적으로 작동.

구성:
- 현재 처리 파일명 (상단 굵은 라벨)
- 프로그레스 바 + 카운터 (`3 / 15`)
- 스크롤 가능한 타임스탬프 로그 (성공=초록, 실패=빨강)
- 처리 중 닫기 시 숨기기만 (백그라운드 계속)

기존 MainWindow의 ProcessWorker와 상태바 프로그레스는 제거.
모든 처리 작업이 ProcessWindow를 통해 실행됨.

---

## OCR health 체크

`ensure_workers_ready()` 추가 — 세션당 한 번만 RunPod health 체크.
매 파일마다 반복 체크하지 않음.

---

## 소스 트리 중복 표시 수정

Source와 root Folder가 같은 이름으로 이중 표시되는 문제 수정.
root folder가 1개면 source 노드와 합쳐서 표시, sub-folder는 바로 아래에 연결.

---

## 파일 변경 목록

| 파일 | 변경 |
|------|------|
| `ocr.py` | markdown fallback, raw_result 반환, ensure_workers_ready |
| `text_extract.py` | JSON 저장/로드, 재처리 시 기존 데이터 삭제, OCR_JSON_DIR |
| `ui/process_window.py` | 신규 — 독립 처리 윈도우 |
| `ui/main_window.py` | ProcessWindow 통합, 메뉴 추가 (Retry/Reindex/Reprocess All), 소스트리 중복 수정 |
| `database.py` | _migrate() 추가 — 기존 DB에 folder_id 컬럼 자동 추가 |
| `requirements.txt` | Pillow, requests, python-dotenv 추가 |
| `.env` | RunPod API 키 설정 |
| `.gitignore` | .env, __pycache__, *.db, Trilobite Shape/ |
