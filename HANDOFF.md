# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: 새 데스크탑 앱 스캐폴드 완료, P07 Phase 3 착수 중**

기존 GUI/CLI 동작. RunPod OCR + Zotero 연동 + Haiku/Sonnet 서지 추출 파이프라인 완성.

**2026-04-11 새 단계**: 기존 `papermeister/ui/`는 동결하고, 새 모던 UI를 `desktop/` 패키지로 분리.
- P07 개정 (현재 구현 상태 매트릭스 + entity×state machine + Phase 재순서)
- P08 작성: PaperBiblio → Paper 반영 정책
- P09 작성: 새 데스크탑 UI 설계 (custom QSS + design tokens)
- `desktop/` 스캐폴드: `python -m desktop` 실행, 3-pane + Library/Sources 이중 네비 + 상세 패널 동작

---

## 다음 할 일

### 새 desktop 앱 (P07 Phase 2~4)
- [ ] `papermeister/biblio_reflect.py` — P08 정책 러너 구현 (auto_commit / needs_review / skip)
- [ ] `scripts/reflect_biblio.py` — batch 진입점 (dry-run / apply / single paper)
- [ ] DB migration: `PaperBiblio.status`, `PaperFile.failure_reason` 컬럼 추가
- [ ] desktop: 상세 패널 Apply Biblio 버튼 활성화 (single paper 반영)
- [ ] desktop: source/folder 단위 batch Reflect 트리거 + 결과 다이얼로그
- [ ] desktop: background worker (biblio 추출 / OCR 트리거)
- [ ] desktop: PaperList 상태 셀에 StatusBadge delegate 렌더링
- [ ] desktop: OCR 미리보기 카드 — ocr_json 캐시에서 로드
- [ ] desktop: list_by_library('needs_review') 쿼리 수정 (현재 count와 list 불일치)

### 기존 백로그
- [ ] 1960s 컬렉션 standalone PDF 226편 OCR 진행 중 (RunPod)
- [ ] OCR 완료 후 → Haiku biblio 추출 → promote
- [ ] Phase D 본격 추출: OCR 완료된 전체 ~2,000편에 Haiku biblio 추출
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
| Zotero API | pyzotero (read+write) | user_id + api_key, Preferences에 저장 |
| Zotero PDF | 로컬 저장 안 함 | 임시 다운로드 → OCR → 삭제. NAS backup 별도 |
| Zotero 메타데이터 | API 데이터 우선 | PDF 메타데이터보다 정확 |
| Zotero key 저장 | PaperFile.zotero_key | 첨부파일 key, Folder.zotero_key는 collection key |
| Zotero 컬렉션 | 시작 시 자동 동기화 | 캐시 → API 순서, 소스 트리에 표시 |
| Zotero 아이템 | 컬렉션 클릭 시 fetch | API 1회 호출로 parent+attachment 매칭 |
| Zotero attachment sync | 모든 타입 수집 (PDF+JSON) | ingestion.py에서 파생(JSON)은 status='processed' |
| OCR JSON → Zotero | opt-in (`zotero_upload_ocr_json` pref) | OCR 후 자동 sibling upload, 기본 OFF |
| OCR 엔진 | Chandra2 유지 | glm-ocr 평가 후 탈락 (한국어 정확도 부족) |
| CLI | `cli.py` (argparse) | PyQt6 의존 없음, GUI와 동일 DB 공유 |
| 서지 추출 모델 | Haiku 4.5 (텍스트) | 세 모델 동률, Haiku가 비용 최적 |
| Vision pass 모델 | Sonnet 4.6 | CJK는 Haiku vision 부정확, Sonnet 필수 |
| 서지 추출 DB | PaperBiblio 별도 테이블 | 비파괴 원칙, source 필드로 모델/버전 구분 |
| Standalone promote | LLM biblio → Zotero parent 생성 | confidence=high만 자동, 나머지 수동 |
| Journal issue | Vision pass → document 타입 | Zotero에 journalIssue 타입 없음 |

---

## 미결 사항

- 컬렉션-수준 메타데이터 (issue 모음 마킹 등)
- PaperBiblio → Paper 반영 검토 UI
- Zotero → DB pull sync (현재 push only)
- 검색 결과 매칭 패시지 하이라이트 표시 방식

---

## 최근 세션 요약

**2026-04-11 (세션 7, 후반)** — [devlog 020](./devlog/20260411_020_Docs_Source_Cleanup_And_Portability.md)
- `docs` directory source 및 관련 Paper/PaperFile 3건 DB에서 제거 (Zotero source만 남음)
- Paper 9,786 → 9,783 / PaperFile 11,981 → 11,978
- Windows 이식성 점검 완료: `~/.papermeister/`에 Linux 절대경로 0건 (Zotero 파일명만), cross-platform 안전
- `~/papermeister.tar.gz` (334 MB) 생성 — Windows 이식용 일회성 아티팩트
- 세션 중 노출된 RunPod / Zotero API 키 모두 revoke + 재발급 완료

**2026-04-11 (세션 7)** — [devlog 019](./devlog/20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md)
- P07 개정: 현재 구현 상태 매트릭스 추가, entity×state machine 모델, Paper 정체성 비대칭(Zotero vs filesystem stub), Phase 재순서(biblio 반영 → 검색)
- P08 작성: PaperBiblio → Paper 반영 정책. auto-commit 조건(high confidence + 필수 필드 + stub Paper), override 정책(빈 슬롯만), needs_review taxonomy
- P09 작성: 새 데스크탑 UI 설계. custom QSS + design tokens, 4-layer 구조(views/services/components/workers), 화면별 상태/액션 매트릭스
- `desktop/` 패키지 스캐폴드:
  - `python -m desktop` 실행, 기존 `papermeister/ui/`와 완전 독립
  - 다크 모던 테마 (Linear/Zed/Raycast 류)
  - 3-pane 레이아웃 + 좌측 rail + 상단 검색 바 + 하단 상태바
  - Library 이중 네비 (All/Pending/Processed/Failed/Needs Review/Recent)
  - Sources 트리 (Zotero 45 컬렉션 + Local)
  - 우측 상세 패널 (Metadata / Extracted Biblio / File 카드)
  - stub Paper는 italic + banner 표시
- PyQt6 6.6.1 → 6.11 업그레이드 (PyQt6-Qt6 6.11 런타임과 맞춤, `QFont::tagToString` 심볼 이슈 해결)
- requirements.txt: `PyQt6>=6.7,<6.12`

**2026-04-08~09 (세션 6)**
- Zotero DB 초기화 후 전체 재동기화 (scripts/resync_zotero.py)
  - 9,783 papers, 9,897 paperfiles 생성
- NAS storage에서 PDF hash 계산 + OCR 캐시 매칭 (scripts/update_hashes.py)
  - 9,503 hash 매칭, 1,116 status=processed 복원
- OCR JSON Zotero sibling upload (scripts/upload_ocr_json.py)
  - 2,007개 JSON을 Zotero에 업로드
  - 자동 업로드 opt-in (`zotero_upload_ocr_json` preference)
- LLM 서지정보 추출 파이프라인 구축
  - `papermeister/biblio.py`: OCR JSON 로드 + BiblioResult dataclass
  - `papermeister/biblio_eval.py`: GT 대비 메트릭 (title/authors/year/journal/doi)
  - 평가셋 200편 stratified sampling (scripts/build_eval_set.py)
  - Baseline(정규식) overall=0.139
  - Haiku/Sonnet/Opus 평가: 모두 overall ≈ 0.88 (동률)
  - devlog: 모델 비교표 (20260408_011)
- PaperBiblio 테이블 추가 (비파괴 추출 결과 보관)
- Standalone PDF promote (scripts/promote_standalone.py)
  - confidence=high 39편 → Zotero parent item 생성 + PDF/JSON child 이동
  - CJK 저자 이름 분리 (4글자→2/2, 3글자→1/2)
- Vision pass (scripts/extract_biblio_vision.py)
  - 1-30 (A5) 컬렉션 28편: 「化石」 제1~30호 → journal_issue 분류
  - 31-71 (B5) 컬렉션 31편: 「化石」 제31~71호 → journal_issue 분류
  - Sonnet vision >> Haiku vision (CJK)
- 기존 잘못된 parent item in-place 수정 (scripts/update_promoted_items.py)
- Zotero attachment sync 개선 (JSON 포함 모든 attachment 수집)
- 1960s 컬렉션 OCR 226편 진행 중 (RunPod)
- devlog: 배운 것들 정리 (20260409_012)

**2026-04-01 (세션 5)**
- CLI 버전 구현 (`cli.py`)
  - 서브커맨드: import, process, search, list, show, config, status, zotero
  - 인터랙티브 모드, `process -c <컬렉션>` 지원

**2026-03-31 (세션 4)**
- Ollama glm-ocr 로컬 OCR 엔진 평가 → 탈락 (한국어 부족)

**2026-03-31 (세션 3)**
- Zotero 연동 디버깅/최적화, OCR 병렬 처리, Preferences UI

**2026-03-30 (세션 2)**
- Zotero 연동 초기 구현

**2026-03-30 (세션 1)**
- PRD → MVP 전체 구현 (0 → 1)
