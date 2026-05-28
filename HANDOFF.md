# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: P07 Phase 2 완전 종료 / Phase 3 완료 + 기본 사용 가능 / Phase 4 hookup 진행 중**

### 안정적으로 돌아가는 것
- 기존 GUI (`papermeister/ui/` — **동결**, 신규 개발 없음). Process/Preferences 다이얼로그는 새 desktop 앱에서 재사용 중
- CLI (`cli.py`) — import/process/search/list/show/config/zotero
- **OCR 3-backend**: RunPod serverless / Direct vLLM pod / **Wrapper API** (세션 16 추가)
- Zotero 양방향 동기화: pull(기존) + **push/write-back(`papermeister/zotero_writeback.py`)**
- Haiku/Sonnet/**Qwen3** 서지 추출 파이프라인 + PaperBiblio 저장
- P08 반영 러너 (`scripts/reflect_biblio.py`): single / batch / `--force` 세 경로 모두 실DB에서 검증됨
- **새 desktop 앱** (`python -m desktop`, Windows + Anaconda):
  - 좌측 Rail (Library/Search 모드 + **Sync**/Process/Settings 액션)
  - **SourceNav 2-section**: 상단 Collections tree + 하단 STATUS 패널 (접기/펴기, 항상 하단 고정)
  - 중앙 PaperList (Status/Authors/Year/Title 컬럼, **인용 스타일 저자**: `Smith et al.` / `정직한 외`) — **Ctrl+click → SourceNav에서 컬렉션 reveal**, **헤더 클릭 정렬**
  - **우클릭 컨텍스트 메뉴 (PaperList)**: status별 다음 액션 (Process OCR / Retry / Extract Biblio / Open PDF / Review Biblio)
  - **우클릭 컨텍스트 메뉴 (SourceNav)**: Process Folder (OCR → Biblio) / Upload OCR JSON to Zotero — **하위폴더 재귀 포함**
  - **Status pill 파이프라인 반영**: `wait`(pending) → `OCR`(processed) → `done`(biblio applied), `rev`(needs_review), `err`(failed), `—`(no PDF)
  - 우측 DetailPanel — **탭 3개**: **Metadata** (메타데이터 + 파일 + Biblio 비교 통합) / **PDF** (PyMuPDF 렌더링 + Zotero 다운로드) / **Text** (OCR markdown)
  - **Biblio 비교 UI**: apply 후 사용되지 않은 쪽 dim 표시 (#555)
  - **상단 검색창 동작** (Enter로 FTS5 검색, Clear로 이전 뷰 복원, Nav 클릭으로 검색 취소)
  - **폴더 전환 시 DetailPanel 초기화**
  - **Zotero incremental sync** (시작 시 자동 + Sync 버튼 + 우클릭 Full Sync, progress 표시 + 아이콘 pulse 애니메이션)
  - **PaperFolder** M2M junction table — Zotero multi-collection membership 지원
  - **ProcessWindow**: Cancel 버튼 + 서버 상태 폴링 표시 + 완료 시 pill 실시간 갱신
  - **Wrapper 파이프라인 모드**: 서버 큐에 항상 N페이지 이상 유지 (`ocr_min_queued_pages` pref, 기본 6). OCR 완료 파일부터 자동 biblio 추출 (병렬 진행)
  - **Extract Biblio**: 우클릭 → Sonnet 4.6 또는 Qwen3-14B로 서지 추출, 자동 apply (Zotero 데이터 일치 시)
  - **PDF 캐시**: `~/.papermeister/pdf_cache/{zotero_key}/{filename}` — OCR 다운로드도 같은 캐시 사용
  - **Apply Biblio → pill 업데이트** 연결
  - **Zotero write-back 토글** (`zotero_writeback_enabled` pref, 기본 OFF) + **OCR JSON 자동 업로드 토글** (`zotero_upload_ocr_json` pref, 기본 OFF) — Preferences UI에 노출됨. write-back OFF면 Apply Biblio가 local-only 경로로 우회 (다음 Zotero pull sync에서 덮어쓰여질 수 있음)
  - **403 Forbidden 친절 처리**: `zotero_writeback.ZoteroWriteAccessDenied` 래퍼가 pyzotero `UserNotAuthorised`를 잡아 명확한 메시지 + 해결책 안내
  - **Sibling JSON pre-fetch**: OCR 진입 시 로컬 cache miss + Zotero-sourced이면 같은 paper의 `{pdf_hash}.json` sibling을 DB로 확인 → 있으면 Zotero에서 다운로드해 cache에 atomic write → OCR API call 우회 (크로스머신/캐시 손실 복구). wrapper 파이프라인 `_prepare_file`에도 동일 적용
  - **`papermeister_meta` in OCR JSON**: apply 시 `record_biblio_applied`가 JSON에 `{schema_version, biblio_state, biblio_source, biblio_applied_at}` 박고 in-place로 Zotero 재업로드 (attachment key 보존, `upload_attachments` + If-Match md5). 5개 apply 경로 모두에서 호출. 읽기 측은 `extract_biblio_llm` 진입에서 meta 보고 `BiblioAlreadyApplied` raise → LLM 호출 우회
  - **itemType 별 journal-like 필드 매핑** (`ITEM_TYPE_JOURNAL_FIELD`): `bookSection→bookTitle`, `conferencePaper→proceedingsTitle` 등. 기존엔 모두 `publicationTitle`로 보내서 `bookSection` 등에서 400 `UnsupportedParams`. `ZoteroPatchRejected` 래퍼로 친절 처리
  - **OCR Wrapper `client_id`** (`papermeister-{8 hex}`): per-install ID, `preferences.json`에 영속. `POST /ocr` form data에 동봉 → 서버 dedup `(file_hash, client_id)` 활용. `GET /ocr` 응답의 `client_id`로 "내 잡 vs 남 잡" 구분
  - **Server-load wait**: wrapper 파이프라인 시작 직전 `GET /ocr` → 다른 client_id의 active 잡(`queued`/`processing`)이 있으면 15초 간격 폴링하며 대기. `ocr_wait_for_others` pref로 토글 (기본 ON), Cancel 가능
  - **자동 큐 깊이** (`GET /api/stats` 의 `recommended_concurrency` 사용): `ocr_min_queued_pages` pref 미설정이면 auto — 서버가 모드(`2ocr`/`llm+ocr`/`1ocr`)에 따라 권장 동시성(12/6/6)을 알려줌. 명시적 숫자가 박혀있으면 override. Process 시작 시 status bar에 `Queue depth target: N pages (mode=..., OCR backends a/b)` 한 번 출력
  - **Preferences QTabWidget**: 평면 dialog → 4탭(OCR / Biblio / Zotero / About). About 탭 하단에 read-only `Client ID` 표시. 다크 QSS `#PrefsTabs` 스코프 추가로 탭 라벨 가시성 확보
  - **Biblio auto/manual 분리 토글**: `auto_biblio_extract` (OCR 완료 후 자동 큐잉) / `manual_biblio_extract` (우클릭 Extract Biblio 메뉴 활성) 두 pref 독립. LLM provider 라디오는 OR 로직 (둘 중 하나라도 ON이면 enable). Manual OFF면 우클릭 메뉴 항목 회색 + 툴팁 안내
  - **폴더 Process Folder `failed` 재시도 포함**: 기존엔 `pending`만 수집했으나 이제 `pending` + `failed` 둘 다. 다이얼로그 메시지 케이스별 분기 ("Process N pending + retry M failed"), Yes 누르면 failed → pending 일괄 reset + pill 즉시 `err → wait` 갱신
  - **Standalone PDF auto-promote** (`auto_promote_standalone` pref, 기본 ON): OCR 완료 후 passages/FTS 저장 직후, JSON 업로드 직전에 `promote_standalone_with_filename` 호출 → Zotero에 `document` 타입 parent item 생성(title=filename), PDF를 그 child로 이동, 로컬 `Paper.zotero_key` 갱신. Zotero GUI "Create Parent Item…"의 LLM-less 자동화 등가물. Preferences → Zotero 탭에 토글. `upload_sibling_attachment`이 standalone PDF에서 raise 하던 문제가 자연스럽게 해소됨
  - **Stale standalone 자동 merge** (sync 시): 사용자가 Zotero GUI에서 standalone을 promote하면 새 parent로 attachment의 `parentItem`만 바뀌고 PaperMeister는 옛 standalone Paper를 그대로 둬서 중복이 발생하던 버그. `_merge_stale_standalone()`이 PaperFile/PaperBiblio/Passage/passage_fts를 새 parent로 일괄 이관 후 옛 Paper 삭제. `sync_zotero_items`의 3개 attachments 처리 지점(메인/orphan/backfill) 모두에서 자동 detection
  - **PaperList 우클릭 'Process OCR (re-run + create parent)'**: standalone PDF는 status와 무관(pending/processed/done/review)하게 메뉴 노출 — cache load → promote 트리거로 retroactive parent 생성 가능. `PaperRow.is_standalone` 필드 + tree item `UserRole+3`에 저장, `update_status`가 promote 후 false로 갱신
  - **ProcessWorker enqueue**: 폴더/단건 우클릭 액션이 실행 중인 worker의 큐에 ID 추가 가능. 기존엔 "Already processing" 거절. `(paper_file_ids, hash) dedupe`로 Rail Process 재클릭 시 in-flight 중복 처리 방지. `_run_wrapper_pipeline`은 `total` 동적 참조로, `_run_parallel`은 polling 패턴(`wait(FIRST_COMPLETED)`)으로 전환
  - **Multi-PDF parent의 JSON sibling 추적 버그 픽스**: 기존엔 "paper에 어떤 JSON이라도 있으면 skip" → PDF 2번째/3번째 JSON이 영구 누락. 이제 `(paper_id, hash)` 쌍으로 매칭(`{hash}.json` 파일명 규약). 영향받은 3 hot path(`text_extract.py`, `scripts/upload_ocr_json.py`, desktop SourceNav 폴더 우클릭 업로드) 모두 수정
  - **DetailPanel lazy 탭/페이지 렌더** (세션 37): paper 클릭 시 Metadata만 즉시 빌드, PDF/Text 탭은 `currentChanged` 첫 활성화 때 한 번만 빌드. PDF 탭은 `_LazyPdfView`(QScrollArea)가 페이지 placeholder를 `page.rect × 1.5`로 미리 잡고 viewport ± 800px lookahead 영역만 `get_pixmap()` 호출 → 100페이지 PDF 클릭도 즉시 응답
  - **Metadata 카드에 Zotero Key 행** (세션 37): `paper.zotero_key`가 있을 때만 `Source` 행 다음에 표시 (디렉토리 소스는 잡음 회피)
  - **OCR `wrapper_submit` 로컬 페이지 수 hint** (세션 37): 제출 전에 `fitz.open(path).page_count`로 페이지 수를 미리 읽어서 (a) POST form에 `total_pages` advisory hint로 동봉 (b) 서버 first-poll이 0을 주면 로컬 값을 그대로 반환. 큰 PDF가 서버 파싱 전에 0으로 응답해서 `process_window`의 `tp or 1` 폴백이 큐 깊이를 1로만 카운트 → 12개 PDF가 burst-submit되던 버그 해소. 서버 측 hint 핸들링은 별도 리포 작업
  - **Zotero attachment 다운로드 direct GET 우회** (세션 37): pyzotero `Zotero.file()`이 응답 Content-Type을 sniff해서 빈 Content-Type의 S3 attachment(`imported_url` linkMode)를 JSON으로 오인식 → 멀쩡한 PDF에 `json.loads()` 호출 → `JSONDecodeError`. `ZoteroClient.download_file_content()` 신설(raw GET, bytes 반환), `download_attachment` / `_resolve_filepath` / `_try_fetch_sibling_json` 3개 다운로드 경로 모두 라우팅. 404는 `requests.HTTPError`로 분리 → "attachment record는 있지만 file이 web storage에 없음" 명시 메시지

### 진행 중인 것
- **Phase 4 (hookup)**:
  - **Apply Biblio Zotero write-back 라이브 검증**: 세션 18에서 write 키로 한 번 돌렸음. paper 4315 (bookSection)에서 400 → `ITEM_TYPE_JOURNAL_FIELD` map 픽스 + `ZoteroPatchRejected` 래퍼로 해결. 48편 status=extracted 잔존 (다음 Process 시 재시도 → 일부는 evaluate가 needs_review로 분류한 정상 케이스, 나머지는 bookSection 400으로 멈춘 케이스)
  - batch Reflect 트리거 UI / background worker / StatusBadge delegate — 미완
  - **PaperFolder full sync 미완**: backfill은 Paper.folder 1:1만

### 대기 중
- **Phase D (대량 운영)**: OCR 완료분에 biblio 추출 → `reflect_biblio.py`로 일괄 반영
- **1960s standalone OCR**: 226편. 세션 36 이후엔 OCR 완료 시 자동 promote(parent item 생성)되므로 흐름 단순화됨 — Process Folder 한 번이면 OCR + 자동 parent 생성 동시 진행

---

## 다음 할 일

### 즉시 착수 가능 (Phase 4 hookup)
- [ ] **48편 extracted 잔존분 재시도** — 세션 18 폴더 처리 중 bookSection 400으로 멈춘 케이스 + needs_review 정상 케이스 혼재. 같은 폴더들 다시 Process 한 번 돌려서 `ITEM_TYPE_JOURNAL_FIELD` 픽스 효과 + biblio_state 메타 cross-machine sync 확인 (세션 35의 폴더 failed retry 포함 덕분에 한 번에 처리 가능해짐)
- [ ] **모드 라벨 status bar 영구 표시 여부 결정** (세션 34 미정) — 지금은 Process 시작 시 한 번만 출력. 항상 표시 vs 공간 절약 트레이드오프
- [ ] **`/api/stats` 주기적 재조회 여부** (세션 34 미정) — mid-batch 모드 전환 시나리오 발생하면 추가
- [ ] **Apply Biblio Zotero write-back 추가 검증** — auto_commit 한 건이라도 Zotero 서버 version 증가 + papermeister_meta가 JSON에 박혀서 in-place replace 되는지 확인. 다른 머신에서 같은 폴더 받았을 때 `BiblioAlreadyApplied`로 LLM 스킵되는 cross-machine 시나리오까지
- [ ] **Process 액션 end-to-end 검증** — pending 논문이 있는 상태에서 Rail의 Process 버튼 → 확인 다이얼로그 → `ProcessWindow`가 실제 OCR 돌리는지 + status bar 카운트가 갱신되는지
- [ ] **Settings 액션 실증** — Rail의 Settings 버튼 → PreferencesDialog → 값 저장 후 Zotero 재동기화 실증 (코드 연결됨, 미검증)
- [ ] desktop: source/folder 단위 batch Reflect 트리거 + 결과 다이얼로그
- [ ] desktop: background worker (biblio 추출 / OCR 트리거) — QThread 기반, 기존 `papermeister/ui/` 패턴 참고
- [ ] desktop: PaperList 상태 셀에 StatusBadge delegate (현재는 축약 pill — done/wait/err/rev. 필요 시 풀 라벨로 복원 또는 아이콘화 검토)
- [ ] **BM25 tie-break 개선** (Phase 5 경계): 현재 `passage_fts`는 passage 단위라 title 가중치가 document-level boost로 작동 안 함. 예: `trilobite`로 검색하면 title에 trilobite가 없는데 본문에 많이 나온 논문이 top에 올라옴. 해결안: 별도 `paper_fts` (title/authors)와 합산 or Python post-processing boost. 지금은 alerting 수준

### 큰 덩어리 (Phase D 대량 운영)
- [ ] **작은 mixed 폴더 OCR 검증** (10-30편) — 세션 36 auto-promote 흐름 end-to-end. ProcessWindow 로그에서 standalone 케이스 1-2건의 `Creating Zotero parent item...` / `→ parent created: KEY` 라인 확인 + Zotero에서 parent + child 구조 확인
- [ ] 1960s 컬렉션 standalone PDF 226편 Process Folder — OCR + 자동 parent 생성. 세션 36 enqueue 덕에 도중 다른 폴더도 큐에 추가 가능
- [ ] OCR 완료된 ~2,000편에 Haiku biblio 추출 (`scripts/extract_biblio.py`) — `auto_biblio_extract` OFF 권장(통제 분리)
- [ ] 추출 직후 **반드시 non-dry `reflect_biblio.py` 한 번 돌리기** → biblio status stamp (아니면 Library "Needs Review" 폴더가 비어 보임)
- [ ] `reflect_biblio.py` 대량 실행 — Zotero API rate limit, 412 version conflict 자동 재시도, 진행률 표시 필요 (현재는 pyzotero backoff에만 의존)

### 저순위 백로그
- [ ] 병렬 OCR 실 테스트 (max worker 올린 상태에서 처리 속도 확인)
- [ ] 검색 결과 매칭 패시지 하이라이트 표시
- [ ] 에러 핸들링 보강 (암호화된 PDF, 파손된 파일 등)
- [ ] 테스트 코드 작성
- [ ] DB 삭제 후 복구 경로 실증 테스트 (Phase 1 잔여)

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
- PaperBiblio → Paper 반영 **검토 UI** (현재는 CLI `--paper`만)
- **systematic** Zotero → DB pull sync (현재는 on-demand: resync_zotero.py는 destructive, 타겟 in-place refresh는 수동 one-off)
- 검색 결과 매칭 패시지 하이라이트 표시 방식

---

## 운영 규칙 (세션 8~10에서 발견된 것)

### biblio 추출 후 반드시 non-dry reflect 한 번
`extract_biblio.py`가 새 PaperBiblio row를 만들어도, `reflect_biblio.py --dry-run`은 `status` 필드를 persist하지 않는다. **Library 트리의 "Needs Review" 폴더가 비어 보이면** 이 스텝이 빠진 것. Phase D 워크플로우는 `extract → real reflect → UI 확인` 순서로 구성.

### Zotero-sourced Paper는 local 직접 쓰기 금지
P08 §3.5 원칙. `biblio_reflect.apply()`가 자동으로 분기하지만, 혹시 별도 스크립트에서 Zotero-sourced Paper를 로컬에서 직접 건드리면 드리프트가 생긴다. `resync_zotero.py`가 destructive라 PaperBiblio 손실 위험도 있음. 타겟 in-place refresh가 필요하면 `client._zot.item(key)` → `_parse_item_metadata` 조합 사용.

### `resync_zotero.py`는 위험
`Paper`를 drop하면 `PaperBiblio`가 cascade 삭제됨. 오늘 날까지 추출한 모든 PaperBiblio가 사라진다. 전면 재동기화가 필요하면 먼저 PaperBiblio 테이블 백업, 또는 Zotero에서만 일부 item을 refresh하는 타겟 스크립트 작성.

### preferences.json을 세션에 노출하지 않기
평문 API 키가 들어있다. `cat preferences.json` 직접 실행 금지. 존재 확인은 `get_pref('key', '')` 의 boolean만 활용.

### 세션 마무리 checklist
- HANDOFF.md "다음 할 일" / "현재 단계" 갱신
- P07 매트릭스에 오늘 바뀐 항목 반영 (세션 10에서 이걸 놓쳐서 stale했음)
- devlog NNN 작성 (결정 과정과 근거 위주, 단순 diff는 git이 기록)
- git commit + push (commit 분리는 논리 단위로)

---

## 최근 세션 요약

**2026-05-28 (세션 37)** — [devlog 037](./devlog/20260528_037_Lazy_PDF_Render_Tab_Build_OCR_Submit_Hint.md) · [devlog 038](./devlog/20260528_038_Zotero_File_Direct_Download_Bypass.md)
- **DetailPanel 응답성 개선**: paper 클릭 → 패널 표시 지연이 큰 PDF에서 눈에 띄게 길었음. 원인은 `show_paper()`가 세 탭을 즉시 빌드하면서 PDF 모든 페이지를 1.5x QPixmap으로 동기 렌더. 두 단계 lazy화:
  - **Lazy tab build**: Metadata만 즉시 빌드, PDF/Text는 빈 wrapper만 두고 `QTabWidget.currentChanged` 시그널의 `_on_tab_changed`가 첫 활성화 때만 실제 빌드. `_pdf_built` / `_text_built` 플래그로 재빌드 방지. paper 전환 시 플래그 리셋. `setCurrentIndex`가 index unchanged면 signal 안 뜨므로 `_on_tab_changed(currentIndex())` 명시 호출로 default 탭의 lazy build도 trigger
  - **Lazy PDF page render**: 새 `_LazyPdfView(QScrollArea)` 클래스. `len(doc)`만큼 placeholder QLabel을 `page.rect × 1.5`로 미리 생성(fitz의 page rect는 디코딩 없이 instant) → 스크롤바 총 높이 즉시 정확. `verticalScrollBar().valueChanged` + `resizeEvent`에서 viewport ± 800px 영역과 겹치는 placeholder만 `get_pixmap()` 디코드. 첫 렌더는 `QTimer.singleShot(0, ...)`로 layout pass 이후 defer. PDF download 콜백도 wrapper 내부 child swap으로 전환(탭 인덱스 흐트러짐 방지)
- **Metadata에 Zotero Key 행**: `PaperDetail.paper_zotero_key` 필드 추가, `_build_metadata_card`가 `paper.zotero_key` 있을 때만 `Source` 행 다음에 추가. 외부 도구 cross-reference 편의성
- **OCR `wrapper_submit` 페이지 수 hint** (큰 발견): 서버 12-backend 모드인데 in-flight 12개가 떠 있는 현상의 정체. `wrapper_submit`이 제출 직후 한 번 폴링해서 `total_pages`를 받는데 **서버가 큰 PDF를 아직 파싱 못 했으면 0 반환**. `process_window._submit_next`의 `'total_pages': tp or 1` 폴백 때문에 그 job은 큐 깊이 계산에서 1페이지로만 카운트 → seed loop가 `min_queued_pages=12` 채우려고 12개 burst-submit. 수정: 제출 전에 `fitz.open(pdf_path).page_count`로 로컬에서 미리 읽음 (PDF 구조 파싱만, ms 단위 비용), POST form에 `total_pages` advisory hint로 동봉, 서버 응답 0일 때 로컬 값으로 fallback. 서버 측 hint 핸들링은 별도 리포 작업(client만 보내두고 서버 무시해도 backwards-compatible)
- **pyzotero Content-Type sniffing 우회** (세션 시작 전 미커밋 변경이 본 세션에 정리/커밋된 케이스): pyzotero `Zotero.file()`이 응답 `Content-Type`을 sniff해서 빈 Content-Type인 S3 attachment(`imported_url` linkMode)를 JSON으로 잘못 분류 → 멀쩡한 PDF bytes에 `json.loads()` 호출 → `JSONDecodeError`. 세션 36의 에러 wrap은 메시지만 친절했지 다운로드 자체는 여전히 실패. 새 `ZoteroClient.download_file_content(key)` 메서드 — raw `requests.get`으로 `/items/{key}/file` 직접 호출, Content-Type 무시 후 bytes 반환. pyzotero의 endpoint/library 메타는 재사용 → 인증/베이스 URL 단일 경로 유지. 세 다운로드 경로(`download_attachment`, `_resolve_filepath`, `_try_fetch_sibling_json`) 모두 라우팅. 404는 `requests.HTTPError` 분리 처리해서 "attachment record는 있지만 web storage에 file 없음" 명시 메시지로
- 3개 commit: `01754bd` (desktop + OCR submit), `d5024ed` (devlog 037), `f4e6113` (zotero direct GET + devlog 038)

**2026-05-21 (세션 36)** — Standalone PDF auto-promote, stale standalone merge, multi-PDF JSON, ProcessWorker enqueue
- **`promote_standalone_with_filename()`** (`papermeister/zotero_writeback.py`): Zotero GUI "Create Parent Item…"의 LLM-less 자동화 등가물. itemType=document, title=filename(without ext), 기존 collections 그대로 새 parent에 복사, PDF의 `parentItem` 설정 + collections 비움(children inherit), `Paper.zotero_key` 갱신. 403은 `ZoteroWriteAccessDenied`로 친절 처리
- **OCR 완료 자동 hook** (`text_extract.process_paper_file`): is_zotero AND `Paper.zotero_key == PaperFile.zotero_key` AND `auto_promote_standalone` pref ON이면 passages 저장 직후 JSON 업로드 직전에 promote. 효과로 `upload_sibling_attachment`이 standalone PDF에 raise 하던 문제 자연 해소
- **Stale standalone detection on sync** (`papermeister/ingestion.py`): 사용자가 Zotero GUI에서 standalone을 promote한 경우(attachment의 `parentItem`만 바뀜) 옛 Paper가 남는 버그 픽스. `_merge_stale_standalone()`이 PaperFile/PaperBiblio/Passage/passage_fts(SQL UPDATE)를 새 parent로 이관 후 옛 Paper 삭제. `sync_zotero_items`의 3 attachments 처리 지점(메인/orphan/backfill) 모두에서 자동 작동. backfill 블록은 이전엔 "existing PaperFile 발견 → continue"로 PaperFile을 옛 Paper에 영구 묶어두던 버그 자체의 진입로
- **One-shot cleanup script** (`scripts/cleanup_stale_standalones.py`): 이미 적체된 stale 케이스용. 로컬에서 standalone-shaped Paper 후보 추출 → Zotero API로 현재 `parentItem` 확인 → 새 parent가 로컬에 있으면 merge. dry-run 기본 + `--filename-contains` / `--title-contains` 필터. SSL monkey-patch 포함. 검증: GSAB-41-1.pdf, Loose-Ends-and-False-Starts.pdf 2건 merge 완료
- **Retroactive promote script** (`scripts/promote_processed_standalones.py`): auto-promote hook 추가 이전에 OCR된 standalone PDF들 일괄 promote. 후보 = `Paper.zotero_key == PaperFile.zotero_key AND status='processed' AND not .json`. 필터(`--folder-name-contains`, `--filename-contains`) + dry-run. 검증: 69/69 promote 성공, 0 실패
- **Multi-PDF JSON sibling 추적 버그 픽스**: 한 Zotero parent에 PDF가 2개 이상 있을 때 PDF #1만 JSON이 올라가고 #2/#3은 paper 단위 필터에 걸려 영구 누락되던 anti-pattern. `(paper_id, hash)` 쌍 매칭으로 전환 — JSON 파일명 규약 `{hash}.json` 활용. 3 hot path 수정: `text_extract.py` (자동 업로드), `scripts/upload_ocr_json.py` (CLI 일괄), `desktop/windows/main_window.py::_upload_ocr_json` (폴더 우클릭). 검증: `upload_ocr_json.py` 재실행으로 145/145 누락 JSON 복구
- **ProcessWorker.enqueue()** (`papermeister/ui/process_window.py`): 진행 중 worker에 ID 추가 가능. 기존 "Already processing" 거절을 제거하고 dedup 후 append. `_run_wrapper_pipeline`은 `total = len(...)` 캡처 제거 후 동적 참조 + 메인 루프를 "drained-but-more-arriving" 대응 구조로 재작성. `_run_parallel`은 `as_completed` snapshot 패턴 → `wait(FIRST_COMPLETED, timeout)` polling 패턴으로 전환 (둘 다 enqueue 지원). `ProcessWindow.start()`은 실행 중이면 enqueue로 분기 + total/progress 갱신 + 로그 메시지
- **PaperList 우클릭 standalone 메뉴 확장**: `PaperRow.is_standalone` 필드 추가 (`Paper.zotero_key == PaperFile.zotero_key`). 모든 status(pending/processed/done/failed/review)에서 standalone PDF는 "Process OCR (re-run + create parent item)" 액션 노출 — cache load + auto-promote 트리거. `update_status`가 promote 직후 `is_standalone=False`로 갱신해 다음 우클릭에선 일반 메뉴
- **Preferences UI**: Zotero 탭에 `auto_promote_standalone` 체크박스 (기본 ON)
- **운영 흐름 권고**: 작은 mixed 폴더(10-30편) 워밍업 → 1960s 226편 → 전체 pending. biblio는 OCR 다 끝난 뒤 별도 단계로 분리 (`auto_biblio_extract` OFF 권장)

**2026-05-18 (세션 35)** — [devlog 035](./devlog/20260518_035_Biblio_Toggles_Preferences_Tabs_Folder_Retry.md)
- **폴더 Process Folder `failed` 재시도 포함**: `_process_folder` 쿼리를 `status == 'pending'`에서 `status.in_(['pending', 'failed'])`로 확장. 다이얼로그 메시지 케이스별 분기, Yes 누르면 failed → pending 일괄 reset + PaperList pill `err → wait` 즉시 갱신. 단건 우클릭 Retry와 동일 패턴
- **Auto-biblio extract 토글** (`auto_biblio_extract` pref, 기본 True): OCR 완료 직후 자동 큐잉 게이팅. OFF면 pill이 `OCR`에서 정지 (`done`/`rev` 전환 없음)
- **Preferences QTabWidget 재작성**: 평면 `QVBoxLayout` → 4탭 (OCR / Biblio / Zotero / About). objectName `PrefsTabs` 부여 + `desktop/theme/qss.py`의 `#SourceTabs`/`#DetailTabs` 스코프에 `#PrefsTabs` 합류 (5개 규칙). 다크 QSS 미스코프로 첫 띄움 시 탭 라벨이 흰 바탕 흰 글자로 안 보였던 cascade 버그 해소
- **Biblio auto/manual 분리 토글**: `manual_biblio_extract` pref 신설 (bool, 기본 True). LLM provider 라디오 enable은 `auto OR manual` 헬퍼 `_refresh_biblio_radio_state()`. 우클릭 Extract Biblio 메뉴는 manual OFF면 회색 + 툴팁 ("Disabled: turn on in Preferences → Biblio")
- 디폴트가 둘 다 True라 기존 사용자 동작 변화 없음

**2026-05-15 (세션 34)** — [devlog 034](./devlog/20260515_034_Auto_Queue_Depth_From_Stats.md)
- **자동 큐 깊이** (mode-aware): 서버 `GET /api/stats`의 `recommended_concurrency`를 wrapper 파이프라인 큐 깊이로 사용. 서버 GPU 모드 두 가지 — `llm+ocr` (GPU 0=OCR, 1=Qwen3 → 6 in-flight) / `2ocr` (GPU 0+1 모두 OCR → 12 in-flight). 사용자가 매번 pref 손으로 바꾸지 않도록
- `papermeister/ocr.py::wrapper_get_stats()` 신설 (5초 서버 캐시 활용, 실패 시 `{}` 반환)
- `process_window.run()`: `ocr_min_queued_pages` pref가 미설정이면 stats의 `recommended_concurrency` 사용, 명시적 숫자면 override. Process 시작 시 status bar에 `Queue depth target: N pages (mode=2ocr, OCR backends 2/2)` 한 번 출력
- One-shot 조회 선택 (mid-batch 재조회 안 함): 모드 전환은 사용자 의도적 행위(`mode-llm.sh`/`mode-ocr.sh`)라 중간에 일어날 일 거의 없음 + 큐 깊이가 mid-run에 바뀌면 처리량 측정 흔들림
- 서버 측 `/api/stats`, `/api/services` 명세는 사용자가 세션 18 → 34 사이 추가 (`docs/WRAPPER_API.md`, `docs/ENDPOINTS.md`)

**2026-05-15 (세션 33)** — [devlog 033](./devlog/20260515_033_System_State_Snapshot.md)
- 시스템 상태 스냅샷 — `docs/`의 전략/아키텍처 문서들과 현재 코드 상태를 한 번 매핑. 세션 19 이후 좌표 잡기용 (커밋도 코드 변경 없는 docs-only)
- **로드맵 위치 확인**: Phase 1 (Foundation 안정화) ↔ Phase 2 (Structured corpus) 경계. 세션 16~18 작업은 Phase 1 안정화 범주. Phase 2 진입 결정 미달
- **data model revision 미진입 확인**: `sync_centric_architecture_spec.md` / `data_model_revision_spec.md`이 그리는 `SourceRecord`/`SourceFile`/`PaperSourceLink` M:N 모델로 안 옮겨감. 현재는 source-tied MVP 모델 (Paper.zotero_key 직접 보유). Phase 2 진입 시 도입 필요
- OCR/biblio/write-back 영역은 docs vision보다 빨리 진행됨 (Phase 1.5 LLM extraction layer, write-back 토글 기반 양방향)

**2026-05-15 (세션 18)** — papermeister_meta cross-machine sync, OCR wrapper client_id, server-load wait, bookSection 400 픽스
- 세션 17 끝나고 `Antarctic archaeocyath` 폴더로 라이브 검증 시도 중 발견된 이슈 연쇄 처리
- **sibling JSON fetch decode 버그**: pyzotero `_zot.file(key)`가 JSON attachment에 대해서는 raw bytes가 아니라 이미 파싱된 dict를 반환 → `decode → json.loads` 경로가 `'dict' object has no attribute 'decode'`로 터짐. `isinstance(content, dict/bytes/str)` 분기로 우회
- **wrapper 파이프라인 sibling fetch 누락**: 세션 17에서 `text_extract.process_paper_file`에만 hook해서 wrapper 모드에선 발동 안 함 (`process_window._prepare_file`이 자체 cache 체크 + 곧장 wrapper queue). 사용자가 로그로 잡아줌. `_prepare_file`에도 `_try_fetch_sibling_json` hook 추가
- **`papermeister_meta` field in OCR JSON** (cross-machine sync 핵심): OCR JSON 안에 `{schema_version, biblio_state, biblio_source, biblio_applied_at}` 박아서 머신 간 "biblio 이미 됐다" 신호 전달
  - 쓰기: `text_extract.record_biblio_applied(biblio)` 헬퍼. 5개 apply 경로 모두에서 one-line 호출 (`biblio_reflect.apply()` Zotero/local 분기, `apply_single()`, `desktop biblio_service._apply_merged_zotero/local`). 본문 중복 대신 헬퍼 + 5콜로 통일
  - Zotero in-place file replace: `zotero_client.replace_attachment_file()` — pyzotero `upload_attachments`에 기존 key + 현재 md5(If-Match) 전달 → `_create_prelim` skip → `_get_auth` → S3 PUT 경로로 file content만 교체. **attachment key 보존** (delete+upload 안 함)
  - PaperFile.hash도 재계산해서 sibling row에 반영 (이전엔 빈 문자열)
  - 읽기: `biblio.load_ocr_meta(file_hash)` + `class BiblioAlreadyApplied(Exception)`. `extract_biblio_llm()` 진입에서 meta 체크 → state ∈ {applied, auto_committed}이면 raise. desktop 캘러는 catch → `{'skipped': True, 'meta': ...}`로 done 시그널, `_on_biblio_extracted`가 skip 분기에서 status bar 표시 + pill `done`
- **bookSection 400 `'publicationTitle' is not a valid field for type 'bookSection'`** (paper 4315 ZVFPZI9B): `_compute_patch`가 무조건 `publicationTitle`로 쏘고 있었음. itemType별로 journal-like 필드명이 다름 (article: publicationTitle, bookSection: bookTitle, conferencePaper: proceedingsTitle, ...). `ITEM_TYPE_JOURNAL_FIELD` map 도입, `_journal_field_for(item_type)` 헬퍼로 분기. 매핑 없는 itemType은 journal 쓰기 skip. `_compute_override_patch`도 동일. pyzotero `UnsupportedParams`는 `ZoteroPatchRejected(RuntimeError)`로 래핑해서 UI에 친절 메시지
- **OCR wrapper `client_id`**: 서버가 `(file_hash, client_id)` 기반 dedup + `GET /ocr?client_id=` 필터를 이미 지원 (docs/WRAPPER_API.md). `preferences.get_client_id()` — `papermeister-{8 hex}`, lazy 생성, `preferences.json`에 영속. `wrapper_submit`이 form data로 동봉, response의 `cached=true`는 로그. wait 루프는 `j.get('client_id') != my_cid`로 externals 필터 → 자기 자신은 wait 안 하고 다른 머신/다른 도구만 wait. `ocr_wait_for_others` pref 토글 (기본 ON), 15초 폴링, Cancel 가능
- **About 섹션** (PreferencesDialog 하단): read-only Client ID 표시. 별도 메뉴 안 만들고 자연스러운 위치 (사용자 의견)
- **운영 흐름 검증 메모**: 세션 종료 시점 paper 활동 — 24h 윈도우에서 48편 status='extracted' (LLM 끝났는데 apply 못한 잔존), 15편 'applied'. 48편의 상당수는 needs_review 정상 케이스 + 일부 bookSection 400으로 멈춘 케이스. 픽스 후 같은 폴더 재처리로 자연스럽게 해소될 예정
- commit: `2b34aba` (write-back 토글 + cross-machine sync) + `5ce062c` (client_id + server wait + bookSection fix)

**2026-05-14 (세션 17)** — Zotero write-back 토글, 403 핸들링, evaluate 버그 픽스, sibling JSON 선조회
- **`zotero_writeback_enabled` pref 신설** (기본 OFF) + Preferences UI 체크박스 — 어제 세션 16 작업 중 read-only API 키로 PATCH 시도 → `UserNotAuthorised(403)` 발생이 계기
- **`biblio_reflect.apply()` 게이팅**: `paper.zotero_key`가 있어도 pref가 OFF면 `_local_apply()` 경로로 우회. Mirror가 다음 Zotero pull에서 덮어쓰여질 위험은 사용자가 토글 OFF로 수용한 것으로 간주
- **`desktop/services/biblio_service::apply_merged()` 동일 게이팅** — 비교 UI Apply 경로도 일관성
- **`ZoteroWriteAccessDenied(PermissionError)` 래퍼** (`zotero_writeback._update_item`) — pyzotero `UserNotAuthorised`를 잡아 명확한 메시지 + 해결책 (write 권한 키 발급 or 토글 OFF) 안내. desktop `_on_biblio_extracted`에서 raw traceback 안 새도록 try/except
- **`zotero_upload_ocr_json` pref UI 노출** — 기존엔 preferences.json 직접 편집해야 켤 수 있던 것. write-back과 독립적인 토글 (OCR 완료 직후 sibling JSON 업로드, `text_extract.py:239` 이미 구현됨)
- **`_normalize_name()` 버그 픽스** (Rode et al 2003 / paper 2243 발견): `"Last, First"`(Zotero)와 `"First Last"`(LLM)을 모두 `"last first"`로 정규화. 기존엔 콤마 케이스만 풀고 공백 케이스는 그대로 둬서 동일인이 mismatch → override_conflict 오판. UI의 `format_author_display`가 두 표기를 모두 `"Lastname, Firstname"`으로 렌더했기 때문에 "UI는 동일한데 evaluate는 conflict"의 비대칭이 발생
- **`evaluate()` all_match 버그 픽스**: `_no_conflict(paper_val, biblio_val)` 헬퍼 도입 — biblio 필드가 비어있으면 "할 말 없음"으로 처리 (conflict 아님). 기존엔 paper에만 값 있고 biblio가 비면 unequal → override_conflict. year/authors도 동일 패턴
- **OCR 직전 sibling JSON 선조회** (`text_extract._try_fetch_sibling_json`): 로컬 cache miss + Zotero-sourced이면 같은 paper에 `{pdf_hash}.json` 이름의 PaperFile sibling을 DB로 확인 → 있으면 `client._zot.file(key)`로 raw bytes 받아 cache에 atomic write → OCR API call 우회. Best-effort, 실패 시 OCR로 fallback. 크로스머신/캐시 손실 복구 시나리오 대응
- **운영 흐름 명확화**: write-back ON일 때 OCR → biblio 추출 → `evaluate()` 판정 → `auto_commit`이면 Zotero metadata PATCH 자동 + biblio.status='applied' + pill='done', `needs_review`면 비교 UI 대기 (pill='rev'). OCR JSON 업로드는 별도 토글로 독립 동작

**2026-05-13 (세션 16)** — OCR Wrapper/Qwen3 통합, 폴더 일괄 처리 파이프라인
- **환경 이전**: Windows + Anaconda 환경에서 desktop 앱 실행. SSL 문제 해결 (`requests.api.request` monkey-patch, 연구소 자체 CA 대응)
- **Zotero sync 버그 수정**: `sync_zotero_collections()`이 `zotero_library_version` pref를 덮어써서 item full fetch가 안 되던 문제. version 읽기를 collections 단계 전으로 이동
- **OCR 3-backend 체계**:
  - `serverless` (RunPod) / `pod` (Direct vLLM) / `wrapper` (Wrapper API, 신규)
  - Wrapper: PDF 통째로 `POST /ocr` → job_id 폴링 → 페이지별 markdown 수집. 클라이언트 측 렌더링/배치 불필요
  - 타임아웃 제거 — 서버가 `processing` 반환하는 한 무한 폴링, 연결 에러 10회 연속 시만 실패
  - Preferences UI에 3가지 라디오 버튼 (RunPod Serverless / Direct vLLM / Wrapper API)
- **Biblio 추출 Qwen3-14B 지원**:
  - `papermeister/biblio.py::extract_biblio_llm()` — `claude`/`qwen` backend 선택
  - Qwen3: `{base_url}/llm/v1/chat/completions` (OpenAI 호환), thinking 모드 OFF
  - `_parse_llm_json()`: `<think>` 태그 제거 + markdown fence + bare JSON 파싱
  - Preferences UI에 Claude/Qwen 라디오 버튼
  - `SOURCE_RANK`에 `llm-qwen: 25` 추가
- **폴더 우클릭 컨텍스트 메뉴** (SourceNav):
  - "Process Folder (OCR → Biblio)" — 하위폴더 재귀 포함, pending PDF 일괄 OCR + 자동 biblio 추출
  - "Upload OCR JSON to Zotero" — 하위폴더 포함 일괄 업로드
- **Wrapper 파이프라인 모드** (ProcessWorker):
  - 서버 큐에 항상 N페이지 이상 유지 (`ocr_min_queued_pages` pref, 기본 6)
  - `_queued_pages()`: 미완료 페이지(total - done) 기준 계산
  - OCR 완료 파일마다 자동 biblio 추출 큐잉 — OCR과 biblio가 병렬 진행
- **OCR 시 PDF 캐시 통합**: `_resolve_filepath()`가 `pdf_cache/`에 저장 → PDF 탭에서 재다운로드 없이 바로 표시
- **Biblio 비교 UI 개선**:
  - Apply 후 사용되지 않은 쪽 dim 표시 (`#555`)
  - `biblio_reflect.evaluate()` 저자 비교 정규화 (`_normalize_names`) — "Oh, Yeongju" vs "Yeongju Oh" 동일 판정
- **기타 UX**: 폴더 전환 시 DetailPanel 초기화, Apply 후 pill 업데이트
- **로깅**: `~/.papermeister/logs/zotero_sync.log`, `ocr.log` — 즉시 flush

**2026-05-10 (세션 15)** — Apply Biblio Zotero write-back hookup
- 문제: 세션 14에서 만든 `apply_merged()` (desktop 비교 UI Apply 버튼)가 Zotero-sourced paper에서도 local Paper/Author 테이블만 업데이트 → 다음 Zotero sync에서 덮어써지는 drift 발생
- 인프라(`papermeister/zotero_writeback.py`)는 세션 9에 이미 있었으나 desktop 경로에서 호출 안 됨. `biblio_reflect.apply()`는 분기하지만 `apply_merged`은 직접 local 쓰기
- **`writeback_overrides()` 신설** (`zotero_writeback.py`): explicit user-choice 정책. 기존 `writeback_biblio`의 empty-slot fill과 달리, 사용자가 비교 UI에서 고른 값은 Zotero 현재 값과 다르면 덮어쓴다. 단, 동일하면 no-op
- **저자 처리**: 콤마/공백 split → Zotero `firstName`/`lastName` 두 필드. 단일 토큰 또는 unsplit CJK는 `name` 단일 필드 fallback. `_compute_patch`는 단일 `name`만 썼던 데서 개선
- **`apply_merged()` 분기** (`desktop/services/biblio_service.py`): `paper.zotero_key` 유무로 `_apply_merged_zotero` / `_apply_merged_local` 갈라짐. Zotero 경로는 PATCH → re-fetch → local refresh, 실패 시 local 미오염
- **dry-run 검증** (paper 6, MF2AFY4V): empty/match/journal-change/author-change 4케이스 모두 patch 모양 정상. 라이브 write 검증은 사용자 손에 남김

**2026-04-14 (세션 14)** — [devlog 028](./devlog/20260414_028_UI_Pipeline_Ingestion_Fixes.md)
- **Paper List UX**: row padding 축소, 폰트 확대, 헤더 클릭 정렬, status pill 재정의 (wait/OCR/done/rev/err/—)
- **우클릭 컨텍스트 메뉴**: status별 다음 액션 (Process OCR, Retry, Extract Biblio, Open PDF, Review Biblio)
- **Detail Panel 탭 재구성**: Metadata+Biblio 통합, PDF 탭 (PyMuPDF 렌더 + Zotero 다운로드 + 캐시), OCR→Text 이름 변경
- **Extract Biblio**: Sonnet 4.6 백그라운드 실행, 확인 다이얼로그, 자동 apply (auto_commit 시)
- **ProcessWindow**: Cancel 버튼, 서버 상태 5초 폴링, 완료 시 pill 실시간 갱신
- **Ingestion 버그 수정**: title fallback 중복 매칭 (66개 misattached file 복구), incremental sync attachment 누락 (children fetch), annotation 필터링 (8개 삭제), PDF-first file 선택
- **PDF 캐시**: `~/.papermeister/pdf_cache/{zotero_key}/{filename}`

**2026-04-12 (세션 13)** — [devlog 026](./devlog/20260412_026_PaperFolder_Sync_SourceNav_Rework.md)
- **PaperFolder junction table**: `Paper ↔ Folder` M2M 관계 도입. `database._migrate()`에서 기존 `Paper.folder`로 9,783건 backfill. `paperfolder_needs_full_sync` 플래그로 첫 full sync 트리거
- **Zotero API `collections` 필드**: `_parse_item_metadata()` + standalone PDF에 `data['collections']` 추가. `get_collection_items()` 내부를 `_classify_raw_items()` + `_build_results()`로 리팩토링
- **Library-wide incremental item sync**: `ZoteroClient.get_all_items(since=version)` — `zot.items(since=N)`으로 변경분만 fetch. `ingestion.sync_zotero_items()`로 Paper/PaperFile/PaperFolder 일괄 처리. orphan attachment 핸들링
- **Desktop Sync 버튼**: Rail에 Sync 액션 추가. `ZoteroSyncWorker(QThread)` — progress/done/failed 시그널, status bar 실시간 표시. Sync 중 아이콘 opacity pulse 애니메이션 (`QPropertyAnimation`). `QThread.finished` safety net으로 animation 해제 보장. 우클릭 → "Full Sync" context menu. 시작 시 자동 sync + Settings 저장 후 re-sync
- **Metadata Collection 경로**: `PaperDetail.collections` — PaperFolder 기반 다중 경로 (`Parent › Child`), fallback으로 `Paper.folder` chain walk
- **Ctrl+click reveal**: `PaperListView.folder_reveal_requested(folder_id)` → `SourceNav.reveal_folder()` — DFS + 탭 전환 + expand + scrollTo (selection_changed 미emit)
- **SourceNav v4 재구성**: 단일 tree → Collections tree (상단, scrollable) + `_StatusPanel` (하단 고정, 접기/펴기). Zotero 탭 이름 `"My Library"`. STATUS 패널은 탭 바깥이라 탭 전환해도 유지

**2026-04-12 (세션 12)** — [devlog 025](./devlog/20260412_025_Detail_Tabs_OCR_Render_Search_Wiring.md)
- **DetailPanel 탭 구조로 재작성**: `QScrollArea` 상속 → `QWidget` + 내부 `QTabWidget#DetailTabs`. 탭 3개 — **Metadata** (기존 카드) / **Biblio** (Apply 버튼 포함, empty state 분기) / **OCR** (markdown 렌더링). 탭별 독립 스크롤, 논문 변경 시 직전 선택 탭 복원, Stub 배너는 탭바 위에 고정되어 탭 전환해도 유지
- **OCR 탭**: `papermeister/biblio.py::load_ocr_pages()`로 `~/.papermeister/ocr_json/{hash}.json` 페치 → 페이지 이어붙이기 (`*— page N —*` + `---` 구분자) → `QTextBrowser.setMarkdown()`. 처리 상태별 empty state 분기 (`no hash` / `not processed` / `cache missing`)
- **OCR 마크다운 sanitizer** 추가 (`_sanitize_ocr_markdown`): Chandra2 OCR 본문을 그대로 `setMarkdown()`에 넘기면 `-qt-list-indent` 누적으로 텍스트가 계속 오른쪽으로 밀리는 버그를 두 단계로 수정
  - 1차: `^(\d+)\.\s` 패턴을 backslash escape + 모든 줄 `lstrip()` → `1. text` 류와 leading-space code block 차단. 20개 샘플 기준 1,310 줄의 4-space prefix + 506 건 numbered marker 발견
  - 2차: 사용자 리포트 ("Life-History and the Evolution of Ontogeny in the Ostracode Genus" 레퍼런스 섹션) 로 누적 원인이 **레퍼런스의 볼륨 번호 단독 줄** (`88.`, `158.`)임 발견. regex를 `^(\d+)\.`로 완화 (trailing `\s` 요구 제거) → `<ol>` 0개, `qt-list-indent` 0, 계단식 밀림 완전 제거
- **검색창 wiring** — `search_bar.returnPressed` → `_on_search_submitted`, `textChanged(empty)` → `_apply_current_selection` (이전 nav 뷰 복원), nav 클릭 시 검색창 `blockSignals` 후 clear. `_current_selection` 상태로 검색↔library 전환 관리
- **`desktop/services/search_service.py`** 신설: `papermeister.search.search()` 래핑 → `PaperRow` 반환. `PaperListView.load_search(query)` 추가
- **`papermeister/search.py` FTS5 LIMIT 버그 수정**: `limit` 파라미터가 **passage row 개수**에 걸려 있어서 `trilobite` (75k passage hits, 1,031편) 검색 시 밀도 클러스터링으로 상위 50 passage가 4편에 몰려 **결과 4편**만 반환되던 문제. SQL에서 GROUP BY로 풀려 했으나 FTS5 `bm25()`가 aggregate 컨텍스트에서 호출 불가 (`unable to use function bm25 in the requested context`) — CTE로도 안 됨. 결국 **Python dict dedupe**로 우회. `limit` 의미를 "distinct paper 수"로 변경, `max_passages=200_000` 안전 상한 추가. 벤치마크: 75k 행 페치 + dedupe 0.18s. docstring에 버그 배경 날짜 박아둠
- **BM25 tie-break 관찰** (미수정): `passage_fts`가 passage 단위라 document-level title boost 표현 불가 → `trilobite` top 결과에 title 매치 없는 논문이 올라오는 이슈. Phase 5로 미룸

**2026-04-12 (세션 11)** — [devlog 024](./devlog/20260412_024_Desktop_Shell_Polish_Rail_SourceNav_Chevrons.md)
- **Windows + Anaconda 환경으로 이동**. 019에서 만든 `desktop/` 스캐폴드를 처음으로 시각 검증. 한 번 띄우자마자 드러난 네 건의 독립 버그를 순차 수정
- **Rail (좌측 아이콘 바)**: (a) 이모지 폰트 부재로 `📚`/`🔍`이 Windows Segoe UI에서 빈칸 렌더, (b) `rail.section_changed` 시그널이 `_wire_events()`에 연결 자체가 누락되어 버튼 무반응. SVG 아이콘 4개(`library`/`search`/`process`/`settings`, Lucide 스타일) + `desktop/theme/icons.py` 런타임 색 치환 헬퍼(`QSvgRenderer` 기반, 3-state) 신설. Rail을 **모드(Library/Search checkable) + 액션(Process/Settings non-checkable)** 두 그룹으로 재구조. `_on_rail_section` / `_on_rail_action` 핸들러 추가, Process/Settings는 **동결된 `papermeister/ui/process_window.ProcessWindow` / `preferences_dialog.PreferencesDialog`를 그대로 재사용** (옵션 A 채택)
- **Rail 사이즈**: 작다는 피드백에 `LAYOUT['rail.width']` 44→52, 버튼 36→44, 아이콘 픽스맵 20→26
- **PaperList**: (a) Authors/Title 컬럼 순서 swap, (b) 모든 컬럼 `Interactive`로 변경해서 사용자 드래그 가능, Title만 `Stretch`로 남겨 남은 공간 채우기, `setStretchLastSection(False)` 필수, (c) Source 컬럼 제거, (d) Status 컬럼 축소(폭 60 + pill 라벨 단축 `processed→done`/`pending→wait`/`failed→err`/`review→rev` + pad 10→6). stub 논문의 `— {title}` prefix 제거 — italic로 이미 stub 표시하고 있는데 빈 필드 플레이스홀더(`—`)와 시각 충돌
- **SourceNav 전면 재작성**: 두 섹션 스택(LIBRARY + SOURCES) → **`QTabWidget`** (source 당 탭 1개). 각 탭은 단일 트리로 Library 필터 6개 → `COLLECTIONS` 구분 헤더 → 계층 컬렉션(source root + 재귀 folders). `selection_changed(kind, value)` 시그니처 호환 유지 → `MainWindow._on_nav_selection()` 무수정. QSS에 Zed/Linear 스타일 탭바(`#SourceTabs::tab:selected`에 accent blue 2px 밑줄)
- **Tree chevron 버그**: 컬렉션이 "flat"하게 보인다는 리포트 → DB/서비스/QTreeWidget 3단 검증으로 데이터는 전부 계층 정상임 확인 → 원인은 `qss.py`의 `QTreeView::branch` 규칙이 `border-image: none`만 걸고 **대체 이미지 누락**. `chevron-right.svg` / `chevron-down.svg` 추가, `qss.py`에 `_icon_url()` 헬퍼(`Path.as_posix()`로 Windows forward-slash 경로)로 절대경로 주입
- 아직 **Apply Biblio / Process / Settings 세 버튼 end-to-end 실증은 미완**. 쉘은 실행되지만 실사용 워크플로우 검증이 Phase 4 hookup의 남은 일

**2026-04-11 (세션 10)** — [devlog 023](./devlog/20260411_023_Phase2_Cleanup_And_Needs_Review_Helper.md)
- `desktop/services/library.py::needs_review_paper_ids()` 공유 헬퍼 신설. `_count_needs_review()`와 `list_by_library('needs_review')`가 모두 이 헬퍼를 호출 → count와 list가 구조적으로 일치 보장. 이전에는 각자 `PaperBiblio.select().distinct().count()` / list 이터레이션으로 독립 쿼리를 돌려서 peewee `.distinct()` 렌더 차이에 취약했음
- 처음 측정 시 count=0, list=0 (일치)이었던 이유: 오늘 세션 동안 real batch reflect(`--dry-run` 아닌)를 한 번도 안 돌렸기 때문. dry-run은 status를 persist하지 않음. `scripts/reflect_biblio.py` (no dry-run) 한 번 실행 → 31편 biblio가 `status='needs_review'`로 스탬프됨 → Library 트리의 "Needs Review" 폴더가 이제 실제로 31편 표시
- P07 매트릭스 갱신: Phase 2의 모든 ❌ 항목 → ✅, 새 항목 추가 (Zotero write-back, Paper.date, 파서 수정, Review 쿼리 헬퍼), Phase 2 완료 기준 전부 체크됨
- P07 "바로 해야 할 일" 섹션 재작성 — Phase 2 관련 항목 제거, Phase 4 hookup + Phase D 위주로
- **Phase 2 완전 종료**. 남은 목표는 Phase 4 (desktop hookup) + Phase D (대량 Haiku 추출)

**2026-04-11 (세션 9)** — [devlog 022](./devlog/20260411_022_Zotero_Writeback_And_Date_Parser.md)
- 021의 "7편 local-only drift" 문제 해결: Zotero를 source of truth로 두는 단방향 sync 경로 구축
- **Drift pull-back**: 021에서 수정한 7편을 Zotero 상태로 in-place 복원 (PaperBiblio 보존, `resync_zotero.py`는 destructive라 사용 금지)
- **파서 버그 발견**: `_parse_item_metadata`가 `"08/2017"`같은 M/YYYY 형식을 못 먹고(`int('08/2')` fail), pre-1900 논문도 range filter로 탈락시키고 있었음. 9,783편 중 4,615편(47%)이 year=NULL이던 원인의 절반 이상
- **Option B 채택**: `Paper.date TEXT` 컬럼 추가 (Zotero 원본 문자열, round-trip 무손실) + `Paper.year int`는 derived index로 유지
- **파서 수정**: Zotero 서버가 제공하는 `meta.parsedDate` (YYYY 또는 YYYY-MM-DD로 이미 정규화된 값) 우선 사용, fallback regex는 safety net
- **Bulk backfill**: `zot.top(limit=100) + everything()` 로 9,871 items을 99 API calls(~7분)에 받아옴. 6,841편 date 채움, **1,671편 year 복구**
- **`papermeister/zotero_writeback.py` 신설**: fresh fetch → empty-slot patch against Zotero state (not local) → update_item → re-fetch → refresh local. network-atomic
- **`force_override` 플래그**: `curated_author_shortfall` 탈출구. batch는 절대 force 안 함, single-paper `--force`만 허용
- **End-to-end 검증**:
  - Case A no-op (paper 5): Zotero version 26116 → 26116 (API write 없음), biblio status=applied, reason=`zotero_already_complete`
  - Case B write (paper 9 --force): Zotero version 25612 → 31052, creators 1→5명, journal 채워짐
- 7편 모두 `applied` 상태 정리. 실제 Zotero API write는 paper 9 한 건만.
- **P08 §3.5 추가** (Zotero-sourced vs filesystem-sourced write path), §8 "write-back은 별도 문서로" 미결 해결

**2026-04-11 (세션 8)** — [devlog 021](./devlog/20260411_021_P08_Reflection_Runner_Verification.md)
- P08 러너 end-to-end 검증 — 019에서 작성했던 `biblio_reflect.py`를 실DB에 처음 적용
- **단일 paper**: paper 4 (year: None → 2017), `scripts/reflect_biblio.py --paper 4` 경유, `biblio.status: extracted → applied`
- **Batch**: paper 5/12/13/16/21 (모두 year fill), `--paper-ids` 경유, `biblio.status: extracted → auto_committed`
- **반례 발견**: paper 9 — curated이지만 authors=1명, biblio=5명 → "journal만 채우고 authors 반쪽으로 두는" 부분 성공 실패 모드
- **P08 §4.2.1 추가** — `curated_author_shortfall` 규칙. `len(P.authors) > 0 AND len(B.authors) > len(P.authors)` → `needs_review`로 short-circuit
- **Paper 9 수동 해결** — direct DB write: authors 5명으로 replace + journal 채움 + biblio 9.status='applied'
- 최종 dry-run: `auto_committed=0, needs_review=31` (override_conflict×21 + 추출 노이즈 10)
- 현 corpus는 Zotero-only라 stub Paper 0건 → P08의 stub 경로는 dead code (1960s standalone이 OCR 완료되기 전까지)
- `applied` vs `auto_committed` 구분이 실제로 유용함 확인 — tie-break에서 applied가 최상위로 와서 사람 결정 보존

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
