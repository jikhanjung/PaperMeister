# CLI 구현

**날짜:** 2026-04-01
**유형:** 구현 기록

## 목표

PyQt6 없이 리눅스에서 사용 가능한 커맨드라인 인터페이스 구현.

## 구현 내용

### 1. CLI 기본 구조 (`cli.py`)

argparse 기반 서브커맨드 구조. 코어 모듈(`papermeister/`)을 직접 호출하며 PyQt6에 의존하지 않음.

**서브커맨드:**

| 명령 | 설명 |
|------|------|
| `import <path>` | 디렉토리 PDF 가져오기 |
| `process [-c COLLECTION] [-f FOLDER]` | pending 파일 OCR 처리 (컬렉션/폴더 필터 가능) |
| `search <query> [-n LIMIT]` | 전문 검색 |
| `list sources\|papers\|pending\|folders` | 목록 조회 |
| `show <id> [-t]` | 논문 상세 (-t: 전문 텍스트) |
| `config get\|set [KEY] [VALUE]` | 설정 조회/변경 |
| `status [--ocr]` | DB 현황 (--ocr: RunPod 상태) |
| `zotero sync [--full]` | Zotero 컬렉션 동기화 (증분/전체) |
| `zotero fetch [-c COLLECTION]` | Zotero 아이템 가져오기 |
| `zotero run [-c COLLECTION]` | fetch + OCR 원스텝 실행 |
| `zotero collections` | 컬렉션 목록 테이블 표시 |

### 2. 인터랙티브 모드 (`python cli.py`)

인자 없이 실행하면 자동 진입.

- Zotero 자격증명 확인 (없으면 입력 프롬프트)
- 컬렉션 자동 동기화 (증분)
- 컬렉션 테이블 (Papers, Pending, Done, Fail)
- 대화형 명령: `<번호>` (fetch+process), `f/p <번호>`, `fa/pa` (전체), `s <검색>`, `q`

### 3. 특정 컬렉션 OCR 처리

`_get_pending_files()`와 `_run_process()`를 분리하여 폴더/컬렉션 필터링 지원.

```bash
python cli.py process -c "Korean Fossils"    # 특정 컬렉션만 OCR
python cli.py zotero run -c "Korean Fossils"  # fetch + OCR 한번에
```

### 4. Zotero 증분 동기화

- `zotero_client.get_library_version()`: 현재 library version 조회
- `zotero_client.get_collections(since=N)`: 변경된 컬렉션만 반환
- `preferences.json`에 `zotero_library_version`, `zotero_last_sync` 저장
- `zotero sync`: 저장된 version 이후 변경분만 동기화
- `zotero sync --full`: 버전 무시 전체 동기화

## 주요 설계 결정

- **코어 로직 재사용:** GUI ProcessWorker와 동일한 병렬 OCR 로직(`_run_process`)을 CLI에서 공유
- **library version 저장 위치:** `preferences.json` — ingestion.py의 `sync_zotero_collections()` 완료 시 자동 저장하여 CLI/GUI 모두 적용
- **인터랙티브 모드 기본:** 인자 없이 실행 시 interactive → Zotero 작업 흐름에 최적화
- **컬렉션 테이블:** `_collection_table()` 함수로 분리하여 interactive, `zotero collections` 양쪽에서 사용

## 변경 파일

| 파일 | 변경 |
|------|------|
| `cli.py` | 신규 — CLI 전체 구현 |
| `papermeister/zotero_client.py` | `get_library_version()` 추가, `get_collections(since=)` 증분 지원 |
| `papermeister/ingestion.py` | `sync_zotero_collections()` 끝에 `zotero_last_sync`, `zotero_library_version` 저장 |
| `HANDOFF.md` | 세션 5 기록 추가 |
