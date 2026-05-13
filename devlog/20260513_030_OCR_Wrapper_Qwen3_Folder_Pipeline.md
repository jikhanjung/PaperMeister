# 2026-05-13 — OCR Wrapper/Qwen3 통합, 폴더 일괄 처리 파이프라인

## 배경

Windows + Anaconda 환경에서 desktop 앱을 처음으로 실사용 시작. 연구소 네트워크(자체 CA)와 로컬 OCR 서버(172.16.x.x:8080)를 사용하는 환경으로 전환하면서 여러 인프라 변경이 필요했다.

## 주요 변경

### 1. SSL 문제 해결

연구소 자체 CA로 인한 Zotero API SSL 에러. pyzotero가 `requests.get/post`를 직접 호출하므로 Session 패치 불가. `desktop/app.py`에서 `requests.api.request`를 래핑하여 `verify=False` 기본 주입.

### 2. Zotero Sync 버그 수정

DB가 비어있는데 `zotero_library_version`이 이전 환경 값(31307)으로 남아 incremental sync가 "변경 없음" 반환. 원인: `sync_zotero_collections()`이 Phase 1(collections) 끝에서 version을 덮어씀. version 읽기를 collections 전으로 이동.

### 3. OCR 3-Backend 체계

| Backend | 설명 | 인증 |
|---------|------|------|
| `serverless` | RunPod serverless (기존) | endpoint_id + api_key |
| `pod` | Direct vLLM `/v1/chat/completions` | URL만 |
| `wrapper` | Wrapper API: PDF 통째로 POST, job 폴링 | URL만 |

Wrapper 모드가 가장 단순 — 클라이언트에서 PDF 렌더링, 배치 분할, max_tokens 관리가 불필요. `docs/WRAPPER_API.md` 명세 기반 구현.

**타임아웃 제거**: 서버가 `processing`을 반환하는 한 무한 폴링. 큰 PDF(수백 페이지)도 안전. 연결 에러 10회 연속 시만 실패 처리.

### 4. Biblio 추출 Qwen3-14B 지원

`docs/ENDPOINTS.md`의 `/llm/v1/chat/completions` (Qwen3-14B) 활용. `papermeister/biblio.py`에 `extract_biblio_llm(file_hash, backend)` 통합 함수 신설.

- `_call_claude()`: 기존 `claude -p` CLI
- `_call_qwen()`: OpenAI 호환 API, thinking 모드 비활성화
- `_parse_llm_json()`: `<think>` 태그 제거 + markdown fence 처리

`SOURCE_RANK`에 `llm-qwen: 25` (Sonnet 30 아래, Haiku 20 위).

### 5. 폴더 컨텍스트 메뉴 + 파이프라인

**SourceNav 우클릭 메뉴**:
- "Process Folder (OCR → Biblio)" — 하위폴더 재귀 포함
- "Upload OCR JSON to Zotero" — 하위폴더 포함 일괄 업로드

**Wrapper 파이프라인 모드** (`ProcessWorker._run_wrapper_pipeline`):
- 서버 큐에 항상 N페이지 이상 유지 (`ocr_min_queued_pages` pref, 기본 6)
- `_queued_pages()`: 미완료 페이지 기준 (total - done)
- seed submit → (poll → refill) 루프
- OCR 완료 파일마다 자동 biblio 추출 큐잉 (`_auto_biblio_queue`)
- OCR(ProcessWorker QThread)과 biblio(BackgroundTask QThread)가 병렬 진행

### 6. PDF 캐시 통합

`_resolve_filepath()`가 `~/.papermeister/tmp/`가 아닌 `~/.papermeister/pdf_cache/{zotero_key}/{filename}`에 저장. OCR 후 삭제하지 않으므로 PDF 탭에서 재다운로드 없이 바로 표시.

### 7. Biblio 비교 UI 개선

- Apply 후 사용되지 않은 쪽 dim 표시 (`color: #555`)
- `biblio_reflect.evaluate()` 저자 비교 정규화 (`_normalize_names`): "Oh, Yeongju" vs "Yeongju Oh" → 동일 판정. 기존에는 raw 비교로 항상 `override_conflict` 발생

### 8. 기타 UX

- 폴더 전환 시 DetailPanel 초기화
- Apply Biblio 후 pill `done` 업데이트
- Preferences: OCR 3-backend 라디오, Biblio Claude/Qwen 라디오

### 9. 로깅

`~/.papermeister/logs/` 디렉토리:
- `zotero_sync.log` — sync 전 과정
- `ocr.log` — backend 설정, health check, 요청/응답

`_FlushHandler`로 매 라인 즉시 flush. `tail -f`로 실시간 확인 가능.

## Preferences 신규 키

| 키 | 기본값 | 설명 |
|---|---|---|
| `ocr_backend` | `serverless` | `serverless` / `pod` / `wrapper` |
| `ocr_pod_url` | `''` | pod/wrapper URL |
| `biblio_backend` | `claude` | `claude` / `qwen` |
| `ocr_min_queued_pages` | `6` | wrapper 파이프라인 최소 큐 페이지 수 |

## 수정 파일

- `desktop/app.py` — SSL 무시 monkey-patch
- `desktop/views/source_nav.py` — folder_action 시그널, 컨텍스트 메뉴
- `desktop/views/detail_panel.py` — apply 후 dim, 폴더 전환 초기화
- `desktop/windows/main_window.py` — 폴더 처리, OCR JSON 업로드, 자동 biblio 큐, apply pill 업데이트
- `desktop/workers/zotero_sync.py` — version 읽기 순서 수정, 로깅 추가
- `papermeister/ocr.py` — wrapper backend, 3-backend 체계, 로깅
- `papermeister/biblio.py` — `extract_biblio_llm()`, `_call_qwen()`, prompt 상수화
- `papermeister/biblio_reflect.py` — `_normalize_names()`, SOURCE_RANK qwen 추가
- `papermeister/text_extract.py` — `_resolve_filepath()` pdf_cache 통합
- `papermeister/zotero_client.py` — (SSL 패치 시도 후 revert)
- `papermeister/ui/process_window.py` — wrapper 파이프라인 모드
- `papermeister/ui/preferences_dialog.py` — OCR/Biblio backend UI
