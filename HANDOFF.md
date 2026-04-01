# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: MVP + Zotero 연동 + 병렬 OCR + CLI 구현 완료**

GUI 실행 확인. RunPod OCR 실 연동 성공 (Chandra2-vllm).
Zotero API 연동 완료. OCR 병렬 처리 구현 (health check 기반).
설정은 Preferences 다이얼로그에서 관리 (.env 사용하지 않음).
**CLI 추가:** `python cli.py` — PyQt6 없이 리눅스에서 사용 가능.

---

## 다음 할 일

- [ ] 병렬 OCR 실 테스트 (max worker 올린 상태에서 처리 속도 확인)
- [ ] 검색 결과 매칭 패시지 하이라이트 표시
- [ ] 에러 핸들링 보강 (암호화된 PDF 등)
- [ ] 테스트 코드 작성

---

## 결정된 사항

| 항목 | 결정 | 비고 |
|------|------|------|
| GUI | PyQt6, 3-pane | 소스/폴더 트리 \| 논문 목록 \| 상세 뷰 |
| DB | SQLite + FTS5 | `~/.papermeister/papermeister.db` |
| ORM | Peewee 4.x | `DatabaseProxy` + `SqliteDatabase` |
| 설정 | `~/.papermeister/preferences.json` | RunPod + Zotero 자격증명 |
| 텍스트 추출 | 항상 RunPod OCR | 텍스트 레이어 유무 불문 |
| OCR 병렬 | ThreadPoolExecutor | health check → idle worker 수만큼 동시 처리 |
| OCR 응답 | `markdown` 필드 사용 | `chunks`도 raw JSON에 보존 |
| Raw OCR 보존 | `~/.papermeister/ocr_json/{hash}.json` | 캐시 재활용 가능 |
| 메타데이터 | PyMuPDF (fitz) | PDF 내장 메타데이터만 (Zotero는 API 데이터 우선) |
| 검색 | FTS5 BM25 | title×10, authors×5, text×1 |
| Import 흐름 | Scan → Process 분리 | ScanWorker(빠름) → ProcessWindow(OCR) |
| 처리 UI | 독립 윈도우 (ProcessWindow) | 비모달, 로그 누적, 프로그레스 바 |
| 재처리 | 기존 데이터 삭제 후 재생성 | 멱등성 보장, 캐시 있으면 OCR 스킵 |
| Zotero API | pyzotero | user_id + api_key, Preferences에 저장 |
| Zotero PDF | 로컬 저장 안 함 | 임시 다운로드 → OCR → 삭제 |
| Zotero 메타데이터 | API 데이터 우선 | PDF 메타데이터보다 정확 |
| Zotero key 저장 | PaperFile.zotero_key | 첨부파일 key, Folder.zotero_key는 collection key |
| Zotero 컬렉션 | 시작 시 자동 동기화 | 캐시 → API 순서, 소스 트리에 표시 |
| Zotero 아이템 | 컬렉션 클릭 시 fetch | API 1회 호출로 parent+attachment 매칭 |
| OCR 엔진 | Chandra2 유지 | glm-ocr 평가 후 탈락 (한국어 정확도 부족) |
| CLI | `cli.py` (argparse) | PyQt6 의존 없음, GUI와 동일 DB 공유 |

---

## 미결 사항

- 검색 결과 매칭 패시지 하이라이트 표시 방식

---

## 최근 세션 요약

**2026-04-01 (세션 5)**
- CLI 버전 구현 (`cli.py`)
  - 서브커맨드: import, process, search, list, show, config, status, zotero
  - PyQt6 의존 없이 리눅스에서 사용 가능
  - GUI와 동일한 DB(`~/.papermeister/papermeister.db`) 공유
  - 병렬 OCR 처리 (ThreadPoolExecutor, GUI 버전과 동일 로직)
  - **인터랙티브 모드** (`python cli.py`): Zotero 컬렉션 테이블 + 선택적 fetch/process
  - `process -c <컬렉션>`: 특정 컬렉션만 OCR 처리 가능

**2026-03-31 (세션 4)**
- Ollama glm-ocr 로컬 OCR 엔진 평가 테스트
  - 테스트 스크립트 작성 (`scripts/test_ollama_ocr.py`)
  - docs/ PDF 3개 전체 페이지 OCR 처리 → `docs/ocr_results/`에 결과 저장
  - Chandra2 vs glm-ocr 비교: 한국어 학술 용어 인식 정확도 glm-ocr 심각하게 낮음
  - 결론: glm-ocr 탈락, Chandra2 유지
  - devlog: `20260331_005_Ollama_GLM-OCR_Test.md`

**2026-03-31 (세션 3)**
- Zotero 연동 디버깅 및 최적화:
  - pyzotero `itemType` 필터 → 코드 레벨 필터링
  - pyzotero `dump()` Windows 권한 → `file()` 직접 다운로드
  - N+1 API 문제 → `collection_items()` 1회로 parent+attachment 매칭
  - 스캔 단계에서 PDF 다운로드 제거 (메타데이터만 가져옴)
  - 컬렉션 클릭 → 아이템 자동 fetch + WaitCursor
  - 가운데 패널에 PDF 유무 표시 (pending/processed/failed/no PDF)
- RunPod 설정 `.env` → preferences.json 마이그레이션
- Preferences 다이얼로그에 RunPod 필드 추가
- 시작 시 Zotero 컬렉션 자동 동기화
- OCR 처리 단계별 상태 표시 (Downloading/Running OCR/Loading cache)
- OCR 병렬 처리 구현 (ThreadPoolExecutor + health check 기반)

**2026-03-30 (세션 2)**
- Zotero 연동 초기 구현 (preferences, zotero_client, UI dialogs, ingestion, model changes)

**2026-03-30 (세션 1)**
- PRD → MVP 전체 구현 (0 → 1)
