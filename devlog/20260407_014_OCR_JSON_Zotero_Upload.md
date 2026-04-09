# OCR JSON Zotero Sibling 업로드

## 배경

OCR 결과 JSON 파일을 Zotero에 PDF의 sibling attachment로 올려두면:
- 다른 기기에서도 OCR 결과에 접근 가능
- Zotero의 검색/태깅 기능과 연동 가능
- 나중에 DB를 재구성할 때 Zotero에서 JSON을 다시 가져올 수 있음

## 작업 내용

### 1. 초기 테스트 + API 키 문제

처음 3편 테스트 시 403 Write access denied → Zotero API 키가 read-only였음.
사용자가 read+write 키 재발급 후 정상 동작.

### 2. 일괄 업로드 (`scripts/upload_ocr_json.py`)

- 대상: processed + hash 있음 + zotero_key 있음 + 같은 Paper에 .json PaperFile 없음
- PDF attachment의 parentItem 조회 → sibling으로 upload
- Standalone PDF는 parent가 없어서 skip (RuntimeError → SKIP 로그)

결과:
- 1차 실행: 1,262개 성공 후 'itemType not provided' 400 에러 폭증 → 중단
- 2차 실행 (sleep 1초): 745개 추가 성공, standalone 48개 skip, timeout 1건
- 총 2,007개 JSON 업로드 완료

### 3. 자동 업로드 opt-in 전환

OCR 완료 시 자동으로 JSON을 Zotero에 올리는 기능을 `text_extract.py`에 추가했으나,
**기본값을 OFF로 변경** (`zotero_upload_ocr_json` preference).

이유:
- 사용자가 의도하지 않은 Zotero storage 사용 방지
- rate limit 위험
- 대량 처리 시 bulk 스크립트가 더 적합

### 4. PaperFile에 JSON 추적

처음에는 `PaperFile.ocr_json_zotero_key` 컬럼을 추가했으나, 사용자 피드백으로 **별도 PaperFile row로 처리**하도록 변경. JSON도 Zotero attachment이므로 동일한 모델로 다루는 게 일관됨.

### 5. PDF 필터링

JSON PaperFile 추가로 인해 기존 코드에서 "첫 PaperFile = PDF"라는 가정이 깨짐.
수정한 곳:
- `cli.py` cmd_list, cmd_show: `~PaperFile.path.endswith('.json')` 필터
- `main_window.py` reindex 대상: 같은 필터

## 교훈

- Zotero API bulk write는 요청 간 sleep 필요 (1초면 안정적)
- 'itemType not provided' 에러는 일시적 API 장애로 추정 — 시간 후 재시도하면 해결
- pyzotero `attachment_simple()`이 이미 업로드된 파일을 재업로드하면 `unchanged` 키로 반환 → 이를 처리해야 중복 없는 멱등 동작
