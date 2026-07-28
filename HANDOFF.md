# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: 코어 기능 완성 — Phase 1~3 + Phase D 완료 / P11 references 추출 진행 중(본체 잔여 작업) / P12 CitedWork 정규화 + P13 FTS external-content 라이브 반영 완료 / P14 인용 네트워크(통계·export·ego 그래프) 완료 / P15 코드품질·CI 완료 → **v0.1.2 릴리스**(3플랫폼 + 설치본, 프로즌 빌드 스모크 테스트 통과) + **사용자 매뉴얼 en/ko 배포**(2026-07-28)**

> **라이브 DB 실측 (2026-07-23, Windows DB 6/28 사본 스키마 확인)**: P13 FTS 마이그레이션 **적용 완료**(external-content `passage_fts` + standalone `paper_fts` + 트리거 9종, `passage_fts_content` 없음, `pre-p13-backup` 4.3GB 존재, DB 2.3GB, `quick_check=ok`). references 추출 **부분 완료** — `references_checked=1` **1,733/9,889편(17.5%)**, `Reference` 104,755행(held 매칭 13,102 / CitedWork 매칭 58,360). P12 정규화도 라이브 실행됨 — `CitedWork` **49,728노드**. 즉 P11/P12/P13 모두 라이브 반영, references만 나머지 편수 재개 대기.

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
  - **Wrapper 파이프라인 모드**: 서버 큐에 항상 N페이지 이상 유지. `ocr_min_queued_pages` pref가 미설정이면 서버 `/api/stats::recommended_concurrency` 자동 추종 (mode `llm+ocr`=6, `2ocr`=12), 숫자면 override. OCR 완료 파일부터 자동 biblio 추출 (병렬 진행)
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
  - **단건 Extract Biblio도 공유 biblio 큐 경유** (세션 44): 우클릭 단건 추출이 자체 BackgroundTask를 띄워 배치와 동시 실행/`_biblio_task` 덮어쓰기 하던 문제 → `_auto_biblio_queue` enqueue + drain으로 단일화. 단건도 `BiblioWindow.begin(1)`로 진행창 표시 (배치 live면 total 확장). 추출 `task.failed`도 `_on_biblio_failed`로 통일 — error 행 기록 + advance/finish (실패 시 창이 멈춘 듯 보이던 문제 해소)
  - **biblio 상태 정합성** (세션 44): `already_complete` → terminal `auto_committed` stamp ('done' pill, 재평가 제외). needs_review 전용 'rev' pill. OCR JSON meta=applied인데 로컬 PaperBiblio 없는 paper(DB 재구축 케이스)는 skip 시점에 **marker PaperBiblio** 생성 → 타겟 재수집 루프 차단
  - **write-back standalone 가드** (세션 44): promote 시 `lastRead` pop (rename_ocr_json과 동일 버그) + transient-retry 경유. un-promoted standalone(Paper.zotero_key=attachment) write-back 시도는 `ZoteroPatchRejected`로 "먼저 promote" 안내
  - **'My Library' 우클릭 Process All** (세션 45): source 루트 우클릭 → "Process All (OCR → Biblio)" — 라이브러리 전체(uncollected 포함)의 pending/failed PDF OCR + biblio 없는 processed PDF 추출을 한 배치로. `_run_process_scope(folder_ids|None)` 리팩터, None=전체 스코프(PaperFolder join 생략 → multi-collection 중복도 자연 회피). 기존엔 루트 우클릭이 Source.id를 folder_id로 해석해 무동작이었음
  - **로컬 폴더 가져오기** (세션 47): Rail 'import' 액션(아이콘 `import.svg`) → `QFileDialog`로 폴더 선택 → **`ScanWorker`(QThread, dir-walk 사전 카운트 → determinate 진행)** + **`ScanWindow` 진행창**(per-file 로그 + new/linked/total 요약) → `ingestion.import_source_directory`(재귀 스캔 + SHA256 dedup) → SourceNav refresh(폴더명 탭) → 그 소스 pending PDF "지금 OCR?" 확인 → `ProcessWindow` 재사용. 멀티탭(Zotero + 폴더1/2…)은 SourceNav가 소스마다 탭이라 공짜. **핵심: `ingest_pdf`이 `PaperFolder` M2M 링크 생성** — desktop `list_by_folder`가 M2M로만 조회하므로 필수. 이미 Zotero에 있는(hash 동일) PDF는 skip 대신 **그 기존 Paper를 폴더에 링크**(중복 0, 같은 논문이 Zotero 컬렉션+로컬 폴더 양쪽 탭에 표시). 로컬 PDF는 다운로드 없이 PyMuPDF 메타 추출. **탭 우클릭 → "Remove (local folder)"** 로 directory 소스 삭제 가능(`delete_directory_source`: 순수 로컬 논문만 cascade 삭제, Zotero 공유 논문은 링크만 해제, 디스크 파일·OCR 캐시 보존). **end-to-end는 사용자 Windows 검증 대기**. [devlog 062](./devlog/20260615_062_Desktop_Local_Folder_Import.md)

### 진행 중인 것
- **P11 Phase 2 — 외부 문헌 정규화 (CitedWork 노드)** — ✅ **라이브 실행됨** (2026-07-23 DB 실측: `CitedWork` **49,728노드**, `Reference.resolved_work` 매칭 58,360). 코드 검증(코어 16/16, desktop 14/14) 후 Windows에서 normalize_works `--execute` 실행 완료. 계획 [devlog P12](./devlog/20260625_P12_External_Work_Normalization.md) · 구현 [devlog 064](./devlog/20260625_064_External_Work_Normalization_Implementation.md)
  - **목표**: 외부(cited-only) 문헌에 canonical 노드(`CitedWork`) 부여 → 같은 외부 논문이 여러 Reference로 흩어지지 않게 dedup → co-citation / "자주 인용하지만 미보유" 발굴 가능
  - **신규 `CitedWork`** + `Reference.resolved_work` FK. resolved_paper(held) ⊻ resolved_work(외부), 둘 다 null=junk
  - **2-패스**: 패스1 = DOI/title_key **exact dedup**(deterministic, `references.canonicalize_reference`). 패스2 = `(제1저자 surname, year)` blocking으로 후보 ≥2 클러스터만 **LLM 병합 판정**(`biblio.llm_match_works`), `merge_checked`로 resumable. fuzzy는 결정 안 하고 후보 생성 전용 (사용자 결정: "exact면 OK, 아니면 LLM이 fuzzy보다 신뢰")
  - **실행**: 추출 종료 후 Windows에서 `python scripts\normalize_works.py --execute`(패스1) → `--pass 2 --execute`(패스2). 추출 파이프라인(CLI+**desktop**)은 이미 패스1 auto-canonicalize 연결됨. **현재 실행 중인 추출엔 무영향**(옛 코드 메모리 상주)
  - **단계 6 desktop UI 완료**: References 탭 외부 카드 배지(held 초록 / 공동인용 앰버 `◆ also cited by N`→클릭 시 공동인용 논문 메뉴 / 단독 회색) + **Cited Works 브라우저**(Rail `works` 아이콘 → 인용수 desc 테이블 + 인용 논문 리스트, 더블클릭 이동, 필터/≥2 토글). 임시 DB 검증 desktop 14/14·코어 16/16
- **P11 References 추출 + 인용 네트워크 (Phase 1)** — ✅ **라이브 실행됨(부분)** (2026-07-23 DB 실측: `references_checked=1` **1,733/9,889편(17.5%)**, `Reference` **104,755행**, held 매칭 13,102 / cited-only는 P12 CitedWork로 흡수). 나머지 편수는 Process/Extract References 재개로 진행. 계획서 [devlog P11](./devlog/20260625_P11_References_Extraction_Citation_Network.md)
  - **목표**: 논문 본문 맨 뒤 references 섹션을 파싱(ocrserver Qwen3 32B) → `Reference` 테이블 저장 → 보유 Paper와 매칭. held(PDF 보유) vs cited-only(외부) 구분
  - **신규 모델 `Reference`** (`models.py`): citing_paper FK + order_index + raw_text(source of truth) + 파싱 필드(authors_json/year/title/container/volume/issue/pages/doi/ref_type) + resolution(resolved_paper FK nullable/match_method/match_score) + provenance(source/model_version/parse_confidence). `database.py ALL_TABLES`에 등록(create_tables가 멱등 생성). **held vs cited는 `resolved_paper` null 여부**로 판정, 별도 플래그 없음
  - **`biblio.py` 추가**: `extract_references_block(pages)`(뒤에서부터 references 헤딩 탐색 EN+CJK, appendix 등에서 끊기, 미발견 시 마지막 2p fallback+low conf) / `split_reference_entries`(번호형 `[n]`/`n.` 결정적 분할, 3개 미만이면 통째로 LLM에) / `_REFS_PROMPT`(JSON 배열, raw 원문 보존, 환각 금지) / `_parse_llm_json_array` / `extract_references_llm(file_hash, backend)`. `_call_qwen`에 `max_tokens` 파라미터 추가(refs는 8192)
  - **`scripts/extract_references.py`**: `--scope`/`--paper-ids`/`--limit`/`--reextract`, **`--execute`**(기본 dry-run). `(citing_paper, source)` 단위 delete-and-replace 멱등. skip_existing 기본 ON
  - **`scripts/resolve_references.py`**: DOI 정확 일치(Paper.doi+PaperBiblio.doi 정규화) → 제목 토큰 inverted-index 후보 생성 → year+1저자 성 스코어링(`--threshold` 기본 0.7). `--reresolve`, **`--execute`**(기본 dry-run)
  - **`papermeister/references.py`**: `save_references(paper_id, entries, source, model_version)` 공용 저장 헬퍼 — delete-and-replace 멱등. 스크립트+데스크톱이 공유(필드 매핑 단일화)
  - **desktop 우클릭 "Extract References"** (사용자 요청): **Paper(processed/review/done) / 폴더 / My Library** 세 레벨 모두. PaperList `extract_references` 액션, SourceNav `extract_references_folder`/`extract_references_source`. main_window에 biblio와 **분리된** 전용 큐(`_refs_queue`/`_refs_task`/`_refs_window`) + `ReferencesWindow` 진행창(`desktop/windows/references_window.py`, biblio와 동일 UX). 백엔드는 `ocr_pod_url` 있으면 qwen, 없으면 claude. **biblio와 분리 이유**: 다른 LLM 호출 + Zotero apply 없음
  - **`Paper.references_checked` 체크 필드** (사용자 요청): references 섹션 없는 paper가 매 batch 재파싱되던 문제 해결. 추출 시도하면(있든 없든) True stamp → 타겟은 `references_checked==False`인 processed PDF만. `_migrate`가 컬럼 추가 + **기존 Reference 보유 paper 백필**. "no references section"은 실패가 아닌 **checked-empty**(`extract_references_llm`이 ValueError 대신 `[]` 반환, LLM 호출도 생략). ValueError는 OCR 자체 없을 때만(진짜 에러→재시도). `--paper-ids`/`--reextract`는 플래그 우회
  - **헤딩 다양성 보강** (사용자 지적): references 제목이 저널/시대/언어마다 다양 → 헤딩 목록 대폭 확장. 다국어(EN 다수변형/FR/DE/ES/IT/PT/CJK 참고문헌·引用文献·参考文献·主要参考文献…) + 번호(`5.`/`IV.`)·콜론·"and Notes" 접미사 흡수, plain 라인 매치(`#{0,6}`), 줄 앵커로 "Literature Review"·"see references" 오탐 방지. 헤딩 미검출 시 마지막 2p LLM fallback이 2차 안전망
  - **⚠️ OCR이 HTML-flavored임을 실데이터에서 발견** (라이브 캐시 read-only 테스트): 페이지 `markdown` 필드가 Chandra2 HTML(`data-label="Section-Header"/"Bibliography"`, bbox)인 경우가 많음(복잡 레이아웃). 마크다운-헤딩만으론 15편 중 1편 → `data-label` 시맨틱 레이블 활용으로 수정(`_extract_refs_html`: Bibliography div의 `<p>`=엔트리 1개, 번호 없는 서지도 분할). **재검증 30편 중 25편 high-conf, 2,937 엔트리**(영·불·독·중·한·러). [메모리: ocr-json-is-html-flavored]
  - **DetailPanel References 탭** (사용자 요청): 우측 패널 4번째 탭. 해당 논문 references를 **카드**로 나열 — citation(저자·연도·저널 vol/pages) + 제목 + **held(in library, 클릭→`reference_navigate`로 해당 논문 이동) / cited-only 배지**, raw 원문 툴팁, DOI 링크. lazy 빌드. `paper_service.load_references`+`ReferenceRow`, `paper_list.select_paper` 추가
  - **References 탭 cited-by 역방향** (사용자 요청): 탭 상단에 "CITED BY" 섹션 — 이 논문을 인용한 라이브러리 논문들(`Reference.resolved_paper==this`)을 카드로(클릭→이동), 최신순. 아래는 기존 outgoing references. `paper_service.load_cited_by`+`CitedByRow`. 양방향 인용관계를 한 탭에 통합. refs 없고 cited-by만 있어도 표시
  - **추출 직후 자동 resolve** (사용자 요청): resolve 로직을 `references.py`로 통합(`build_resolution_index`/`resolve_one`/`resolve_paper_references`) → 스크립트·데스크톱 공유. **desktop 추출 워커가 save 직후 자동 resolve** (배치당 held-paper 인덱스 1회 빌드·`self._refs_index` 캐시, refs 직렬이라 race 없음, 드레인 시 무효화). 진행창 "N references, M in library" + 완료 후 References 탭 자동 refresh. CLI `extract_references.py`도 추출 후 일괄 resolve(`--no-resolve` opt-out). 즉 **별도 resolve 단계 불필요** — 배지가 바로 채워짐. (판단: DOI 정확일치 → 제목 토큰 후보 + year/1저자 스코어 ≥0.7)
  - **검증 완료(WSL)**: compile OK, 휴리스틱 self-test(헤딩 35종 매치/8종 거부, 번호형/CJK/fallback/JSON 배열), resolve 매칭(DOI/title/external 구분) end-to-end, `save_references` 멱등, **마이그레이션 컬럼추가+백필**, headless 데스크톱 임포트+메서드 배선 전부 통과. **라이브 실행(Windows + ocrserver Qwen3) 완료 — 1,733편 처리됨** (2026-07-23 실측)
  - **다음**: 나머지 ~8,150편 references 추출 재개 → resolve 임계값 튜닝 → 인용 네트워크 export/표시. Level 3(in-text 인용맥락)은 범위 밖
- **P02 PyInstaller 패키징 — 완료** (2026-06-15): `python -m desktop` → onedir `dist\PaperMeister\PaperMeister.exe`. 빌드 성공 + 실행 검증(Qt/SQLite/SSL Zotero sync/PyMuPDF PDF/FTS5 검색 전부 동작). **빌드 방법은 conda 특유의 DLL 함정 때문에 `build_desktop_clean.bat`(플레인 cmd + conda OFF PATH인 venv)** 필수 — `build_desktop.bat`(conda 셸 직접 빌드)는 Qt DLL 오염으로 실패함. 트러블슈팅 전말·최종 레시피는 [devlog 061](./devlog/20260615_061_PyInstaller_Conda_DLL_Troubleshooting.md), 계획·설계는 [devlog P02](./devlog/20260615_P02_PyInstaller_Desktop_Packaging.md). 후속(저순위): 앱 `.ico`/버전정보/코드사이닝, 배포 자동화
- **Phase 4 (hookup)**:
  - **Apply Biblio Zotero write-back 라이브 검증**: 세션 18에서 write 키로 한 번 돌렸음. paper 4315 (bookSection)에서 400 → `ITEM_TYPE_JOURNAL_FIELD` map 픽스 + `ZoteroPatchRejected` 래퍼로 해결. 48편 status=extracted 잔존 (다음 Process 시 재시도 → 일부는 evaluate가 needs_review로 분류한 정상 케이스, 나머지는 bookSection 400으로 멈춘 케이스)
  - batch Reflect 트리거 UI / background worker / StatusBadge delegate — 미완
  - **PaperFolder full sync 미완**: backfill은 Paper.folder 1:1만

### 대기 중
- **Phase D 후처리**: 라이브러리 전체 biblio 완료 후 needs_review 일괄 검토 + non-dry `reflect_biblio.py` 확인 패스
- **1960s standalone OCR**: 226편. 세션 36 이후엔 OCR 완료 시 자동 promote(parent item 생성)되므로 흐름 단순화됨 — 세션 45의 Process All 스코프에 포함되어 함께 처리 중

---

## 다음 할 일

> **현재 우선순위 (2026-07-28)**: 인프라·문서·릴리스는 한 바퀴 정리됨(v0.1.2 + 매뉴얼 배포).
> **본체로 남은 건 references 추출 완주 하나**다. 그 외는 전부 후속·선택 사항.

### ✅ 데이터 경로 이동 + 설치 프로그램 정렬 (2026-07-28) — [devlog 084](./devlog/20260728_084_PaleoBytes_Paths_And_Installer.md)

`~/.papermeister` → **`~/PaleoBytes/PaperMeister/`** (PaleoBytes 규약, Modan2·CTHarvester 공유).
라이브 이동 확인됨 — DB 2.5GB 포함 전부 새 위치, 옛 디렉터리 소멸, 앱이 새 경로에서 정상 가동.
**디렉터리 이름만 바뀌고 내부 구조·파일명은 동일**하다(`shutil.move` 통째 이동, 실측 검증).

경로는 이제 `papermeister/paths.py`가 **단일 소스**(이전엔 23개 파일에 하드코딩).
`PAPERMEISTER_DATA_DIR`로 override 가능. 신규 설치는 새 경로, 레거시가 있고 새 경로가 없으면
레거시를 그대로 쓴다(자동 이동 안 함). 이동 도구는 `scripts/migrate_data_dir.py`.

**설치 프로그램**도 같이 맞췄다 — `AppId` GUID 고정(**절대 변경 금지**: 바꾸면 업그레이드가
별개 프로그램으로 설치됨), `AppPublisher=PaleoBytes`, 설치 위치
`%LOCALAPPDATA%\PaleoBytes\PaperMeister`(Roaming 아님 — 180MB가 프로필 동기화됨),
시작 메뉴 `PaleoBytes` 그룹. Build 워크플로 수동 실행으로 **ISCC 실컴파일 확인**(6.7.3, 성공).
런타임 데이터는 설치/제거가 건드리지 않음 — `[UninstallDelete]` 추가 금지.
⚠️ **실제 설치 동작은 사용자 수동 확인 대기**(스모크는 "기동한다"까지만 보증).

⚠️ **WSL에서 라이브 DB를 볼 때 경로가 바뀌었다**:
`/mnt/c/Users/Jikhan Jung/PaleoBytes/PaperMeister/papermeister.db`

### 🔴 사용자 액션 대기 (다음 세션에서 먼저 확인할 것)

- [x] ~~**앱 재기동**~~ (2026-07-28 완료, 정상 가동 중) — 07-27~28 수정분 반영. 마지막 확인 시점의 실행 빌드는 `a6609e1` 근처였고, 이후 **재시도 낭비 제거(`acee8ab`)·타임아웃 480초(`410425d`)·목차 오탐 루프 차단(`1749b4a`)·탭 유지·로그 날짜/롤오버**가 미반영. 특히 앞의 둘은 **논문당 25분→8분**을 좌우
- [x] ~~**`reset_references.py --scope empty-checked --execute`**~~ (2026-07-28 완료) — `[]` 탈출구 회귀(079)로 잘못 checked된 **77편** 복구
- [ ] **v0.1.2 Windows 설치본 수동 확인** — 스모크 테스트는 "기동한다"까지만 보증. 설치 자체와 실기능은 미검증
- [ ] **peewee 4 / pyzotero 1.13 라이브 확인** — 테스트가 닿지 않는 두 경로: 라이브 DB `_migrate()`, 실제 Zotero API 왕복(`logs/zotero_sync.log`)

### 관찰 중 — 서버 간헐적 사망 → [devlog 083](./devlog/20260728_083_Container_Restart_Recovery_Wait.md)

**07-28 실적 (로그 실측)**: 179편 시도, **PARTIAL 4편(2.2%)**만 발생(timeout 3 / bad JSON 1).
`no_array`·`empty_result`는 **0건** — 079의 가드들이 오탐 없이 조용하다.

5xx는 **밤사이에 집중**(00시 18 / 01시 6 / 03시 18 / 04시 12 / 05시 6 / 07시 12,
**08시 이후 0건**). 502×60 + 500×12 = 엔진 크래시 루프 시그니처.

⚠️ **5xx 재시도는 이 유형을 못 잡았다** — 72회 발동 / 24회 소진 = 3:1, 즉 **24건 전부
재시도 2회(5s+15s)를 다 쓰고 실패**. **사용자 확인: 502는 컨테이너가 죽었다 다시 뜨는 것이라
분 단위가 걸린다** → 20초 backoff로는 구조적으로 불가능.

✅ **수정 (2026-07-28)**: 게이트웨이 계열(502/503/504)은 **in-place 재시도 제외**하고,
대신 **healthz 폴링으로 복구를 기다렸다가 같은 배치를 이어서** 한다(`_wait_for_server`,
15초 간격 · 최대 900초 · `refs_recovery_wait` pref). 500은 프로세스가 살아있는 상태의
오류일 수 있어 짧은 재시도 유지.
**핵심 이득**: 기존엔 502가 나면 그 논문에서 **이미 파싱한 배치를 전부 버리고** 실패했다
(116엔트리 논문이면 재작업이 큼). 이제 진행분이 보존된다. 대기가 상한을 넘기면 그때 실패로
올려 `ServerGuard`가 큐를 pause하도록 넘긴다. 워커 스레드에서 대기하므로 UI는 안 멈추고,
OCR 워커가 이미 같은 인라인 폴링 방식을 쓴다. ⚠️ 대기 중에는 Cancel이 즉시 반응하지 않는다
(상한이 그 한계를 막아줌)

- **근본 원인은 여전히 서버 측**(OOM 유력, devlog 075/076). 확정하려면 서버 vLLM 로그의
  스택 트레이스 필요 — 우리 쪽 대응은 봉쇄까지가 한계

### 진행 중 (본체)

- [~] **references 추출 완주** — 마지막 실측 배치 기준 진행 중. 실패 경로 복원력은 devlog 075~079로 정리 완료(5xx·절단·무참고문헌·오탐 루프 전부 봉쇄). 완주 후 재-resolve + `normalize_works` 재실행(멱등)

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
- [x] ~~**BM25 tie-break 개선**~~ (세션 48): `search.search()`에 Python 재랭킹 추가 — `query_terms`로 토큰화 후 3-tier(모든 term 제목 매치 / 일부 / 없음) 정렬, tier 내부는 BM25. `trilobite` 제목 매치가 본문 다수 매치보다 상위. [devlog 063](./devlog/20260617_063_Search_Title_Boost_And_Highlighting.md)

### 큰 덩어리 (Phase D 대량 운영) — 세션 45부터 desktop Process All 경로로 가동 중
- [x] ~~작은 mixed 폴더 OCR 검증~~ → 세션 43~44에 걸쳐 collection 단위 biblio 배치를 여러 번 돌리며 사실상 검증됨 (devlog 054~059)
- [ ] **라이브러리 전체 Process All 완주** (진행 중, 2026-06-10~) — OCR 잔여(pending/failed) + biblio 없는 processed 전부. 1960s 226편도 이 스코프에 포함 (OCR + auto-promote)
- [ ] 완료 후 **needs_review 일괄 검토** — Library "Needs Review" 필터에서 Biblio 탭 대조 UI로 처리
- [ ] 완료 후 non-dry `reflect_biblio.py` 한 번 — desktop 경로 밖에서 생성된 biblio가 있다면 status stamp 누락 확인용
- [ ] 대량 실행 중 관찰: Zotero API rate limit(429는 재시도 안 함 — devlog 056), 412 version conflict, 진행창 error 행 누적 패턴

### 저순위 백로그
- [ ] 병렬 OCR 실 테스트 (max worker 올린 상태에서 처리 속도 확인)
- [x] ~~검색 결과 매칭 패시지 하이라이트~~ (세션 48): 결과 행 툴팁(snippet, 매치어 bold) + OCR Text 탭 인라인 하이라이트(amber, 첫 매치 스크롤). [devlog 063](./devlog/20260617_063_Search_Title_Boost_And_Highlighting.md)
- [ ] 에러 핸들링 보강 (암호화된 PDF, 파손된 파일 등)
- [ ] 테스트 코드 작성
- [ ] DB 삭제 후 복구 경로 실증 테스트 (Phase 1 잔여)

### Zotero sync 양방향성 보강 (이번 세션에서 별도 작업으로 분리)
- [ ] **PaperFolder remove (컬렉션 멤버십 양방향 sync)** — 현재 `sync_zotero_items`는 `PaperFolder.get_or_create`만 호출 → add-only. 사용자가 Zotero에서 컬렉션 멤버십을 빼거나 다른 컬렉션으로 옮겨도 옛 링크가 잔존. 정책 결정 필요: "Zotero source of truth로 mirror" vs "add-only 보존". 전자라면 item의 `collections` 배열 기준으로 set-difference로 제거
- [x] ~~**영구 삭제 (empty-trash) 핸들링**~~ (세션 43) — `zot.deleted(since=N)` 기반 `apply_permanent_deletions`로 영구 삭제분 로컬 cascade 삭제(미러). worker Phase 3a(trash sync 직전)에 통합 + `zotero_deleted_version` 증분 추적. backlog는 `scripts/purge_deleted_zotero.py`로 청소(2편). [devlog 050](./devlog/20260608_050_Permanent_Deletion_Empty_Trash_Sync.md)
- [ ] **PaperList에서 Trash 복원 UX** — Zotero에서 복원 시 다음 sync에서 자동 clear되지만, desktop 내에서 우클릭 "Restore from trash"로 즉시 Zotero PATCH(`deleted: 0`) + local clear 가능하게 할지 결정
- [ ] **PaperFile MD5 추적** — Zotero가 attachment에 대해 자체 md5를 보관. 우리는 추적 안 해서 사용자가 Zotero에서 PDF를 새 파일로 교체해도 옛 hash 기반 OCR cache를 그대로 사용. Phase 2 sync-centric 데이터 모델 개정과 함께 다루는 게 자연스러움
- [ ] **PaperFile.content_type 컬럼 추가** — 현재 mime은 attachment dict에서 일회성 `is_derived` 판정에만 쓰임. 컬럼 추가 후 sync에서 동기화하면 mimetype 변경(corner case) 추적 가능
- [ ] **itemType 캐시** — write-back에서 `ITEM_TYPE_JOURNAL_FIELD` 분기는 매번 fresh fetch로 itemType을 알아냄. 로컬에 캐시할지는 use case 더 봐야
- [ ] **OCR JSON sibling attachment title 정규화** (세션 42 메모) — 마이그레이션 script가 `data.title`을 filename과 동일하게 박았는데 Zotero 7+ 정책은 attachment title을 generic label("PDF", "EPUB" 등)로 두는 것. items list에서 긴 hash-suffixed filename이 noise. 필요 시 `scripts/rename_ocr_json.py`에 `--retitle-generic "OCR JSON"` 같은 옵션 추가해서 한 번 더 일괄 PATCH. 또는 Zotero 8의 `Tools → Manage Attachments → Normalize Attachment Titles` 활용. 지금은 의도적으로 그대로 둠. 참고: https://www.zotero.org/support/kb/attachment_title_vs_filename

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

**2026-07-28 (세션 52, 마무리)** — **v0.1.2 릴리스 + 매뉴얼 배포** — [devlog 082](./devlog/20260728_082_Release_Smoke_Test_And_Installer_Fix.md)
- **v0.1.2 발행 완료** — 절차대로(CHANGELOG 섹션 → `version.py` 범프 → 태그 push). `test_version_consistency`가 "CHANGELOG에 해당 버전 섹션 없으면 실패"라 순서를 강제함. 자산 4개+SHA256, 릴리스 노트는 CHANGELOG에서 자동 추출. 빌드번호는 커밋수(`build238`)
- 🔴 **1차 발행에서 구멍 2개 발견 → 수정 후 재발행**:
  - **설치본이 빌드되고도 첨부 안 됨** — `installer/Output/*.exe`로 업로드해 그 경로가 아티팩트에 보존됨 → `release-files/**/*.exe`가 **4단계 깊이에 못 닿음**(zip·AppImage는 2단계라 걸림). **v0.1.1도 같은 상태였음**(설치본 도입 이래 계속 누락). 업로드 전 zip 옆으로 이동해 같은 깊이로
  - **릴리스 파일을 한 번도 실행해보지 않았음** — 형제 리포는 빌드 직후 프로즌 실행 파일을 `--self-test`로 띄우는데 우리에겐 없었음. **프로즌 실행 파일은 자기 번들의 Python·라이브러리를 쓰므로 소스 테스트가 구조적으로 못 보는 부류**(빠진 `--add-data`, 번들 안 된 네이티브 라이브러리, 누락된 Qt 플러그인/SQLite 드라이버)가 있음 — **devlog 061 conda DLL 사고가 정확히 그것**("빌드 성공, 실행 시 사망")
- ✅ **`--self-test` 도입** (`desktop/app.py`): 정상 기동 경로 전부 타고 3초 뒤 exit 0. **argparse 미사용**(유일한 플래그인데 `-h`를 가져가고 Qt가 넘기는 `-platform` 등에 에러). 종료 전 top-level 위젯 close(모달 중첩 루프가 `quit()`보다 오래 살아 러너를 매다는 것 방지). 3레그 스모크 단계 — Windows `Start-Process -Wait`(windowed 앱이라 필수) / Linux `timeout 120` / **macOS는 러너에 `timeout`이 없어 앱 내부 워치독이 상한**. 패키징 *전에* 실행(깨진 번들이 AppImage/DMG로 감싸지기 전에 실패). `tests/test_self_test_flag.py` 4케이스 — **self-test가 조용히 안 걸리면 CI가 아무것도 검사하지 않으면서 통과**하므로(081 mypy와 같은 실패 방식) 양쪽 고정
  - **라이브 검증**: 3플랫폼 스모크 전부 통과, 자산 4개(설치본 **처음 첨부됨**)
  - **남은 한계**: 스모크는 "기동한다"까지만 보증. 설치본 실제 설치·기능 동작은 **사용자 수동 확인 영역**
- **문서 일괄 갱신** (`35d1063`): README(상세패널 3탭→**4탭**, Rail 버튼 누락 3개, OCR 1→3 backend, Python 3.11→**3.12**, **릴리스 존재 자체가 누락돼 있었음**, 참고문헌·개발 워크플로 추가, 로드맵 현행화) / CLAUDE.md(같은 탭 오류, P14 스크립트 5개, 매뉴얼·릴리스·CI 섹션, **mypy 함정 명문화**) / TODOs(완료분 표시 + 인프라 섹션 신설) / CHANGELOG(`[Unreleased]` 신설)
- **매뉴얼 한국어 번역 + 언어 스위처** (`53bb902`, `6e8a056`): 259개 중 **227개 번역**(나머지 32개는 경로·파일명 등 리터럴이라 원문 유지). 스위처는 Modan2 이식하되 **JS `onclick` 대신 실제 `<a href>`** — Sphinx가 `pagename`을 알고 두 언어가 형제 디렉터리라 빌드 시점에 경로가 정해짐 → 새 탭/가운데 클릭/키보드/JS-off 모두 동작. 전제: **두 언어 트리가 평평해야 함**(하위 디렉터리 생기면 `pathto()` 필요, README에 기록). 배포본에서 링크 20개 전부 실재 파일 확인
  - ⚠️ **한국어 RST 함정**: 닫는 `**` 뒤에 조사가 바로 붙으면 마크업이 통째로 사라짐 → `**강조**\ 조사` 이스케이프 공백 필요. CLAUDE.md·매뉴얼 README에 기록

**2026-07-28 (세션 52, 계속)** — **의존성 일괄 업그레이드** — [devlog 081](./devlog/20260728_081_Dependency_Upgrade_Sweep.md)
- 080에서 Dependabot을 켜자 한 시간 만에 **PR 8건**. 각 버전을 **실제로 설치해 우리가 쓰는 API 면을 훑어** 검증 후 전부 머지 (CI 그린만으론 부족 — 커버리지 19.6%이고 실패 경로는 테스트가 안 닿음)
- 🔴 **pyzotero 1.5→1.13은 코드 수정 필요** (`c630fb3`): (1) 에러 클래스 전면 개명(`UserNotAuthorised`→`UserNotAuthorisedError`) → 옛 이름 `except`가 **진짜 에러 전파 도중 AttributeError**를 냄 (2) **requests→httpx 전환** → 연결 blip이 httpx 타입으로 와서 재시도 판정에 안 걸림. 둘 다 **실패하는 순간에만** 드러나 CI로는 안 잡힘. 수정: 이름 여러 개로 조회 + **빈 튜플 폴백**(미래 개명 시 degrade), 재시도에 `httpx.TransportError` 추가(status 에러는 제외). **1.5.28/1.13.2 번갈아 설치해 전체 통과 확인** + `tests/test_zotero_compat.py` 6케이스
- 🟢 **peewee 3.17→4.2 안전**: 우리 API 면 전체(FTS5 원시 SQL·트리거·snippet·bm25 포함)를 두 버전에서 나란히 돌려 **출력 동일** 확인. ⚠️ **CLAUDE.md의 "Peewee 4.x"가 그동안 사실과 달랐음**(실제 3.17.9) — 이 머지로 비로소 맞음
- 🟢 **PyMuPDF 1.24→1.28 안전**(쓰는 API 6종 전부 동작, `fitz` 별칭 생존 확인) / requests·PyQt6는 **하한만 상향**(설치물 변화 0) / actions 3건은 표준 업그레이드 — 그중 `upload-artifact 4→7`과 pages 액션 2건은 **어제 내가 만든 불일치를 Dependabot이 잡아준 것**
- **운영 지식 2건**: 워크플로 파일 PR은 토큰 `workflow` 스코프 없이 **API 머지 불가**(SSH push는 제약 없음 → #2·#9·#10은 main에 직접 적용, Dependabot이 자동 close) / **lock은 머지마다 충돌**하므로 `@dependabot rebase`→승인→머지를 한 건씩 반복. `dependabot-lock-refresh`는 **첫 실전에서 정상 작동**(#4·#5 `refresh-locks` 통과)
- ⚠️ **드러난 것 — mypy 게이트가 보이는 것보다 약함**: lint 잡이 `ruff mypy`만 설치하고 **프로젝트 의존성을 안 깔아서** peewee를 `Any`로 처리 중. peewee 4는 타입 주석이 있는데 **암묵적 `id`/`<fk>_id`를 모델링 안 해** 로컬에선 오탐 28건(테스트 117개는 통과 = 실제 버그 아님). **같은 세션에서 해결** (081 갱신): 28건 전수 분류 → 26건은 peewee가 *생성하는* `id`/`<fk>_id` 미선언(→ `TYPE_CHECKING` 선언), 1건은 자기참조 FK 오버로드(→ 좁은 ignore), **2건은 우리 코드의 이종 dict 느슨함**(→ `TypedDict`). **`id`는 `int`가 아니라 `peewee.AutoField`로 선언해야 함** — 필드가 디스크립터라 클래스=쿼리표현식/인스턴스=값. **`x_id` 대신 `x`를 쓰는 건 금지**(mypy는 통과하지만 행마다 관계 fetch = N+1). CI는 lint에 **의존성 설치 + mypy 버전 핀**(Modan2 관례) 추가 → 게이트가 표방하는 일을 실제로 함. 검증: 수정 전 코드는 28건 검출, 수정 후 0건
- **배포 후 확인 필요**(테스트 미도달 영역): peewee 4 → 라이브 DB `_migrate()` 경로 / pyzotero 1.13 → 실제 Zotero API 왕복(`logs/zotero_sync.log`)
- 소소한 UX 변경 (devlog 없음, 커밋 메시지에 근거 기록): **SourceNav 탭 유지**(`a7020cd` — `refresh()`가 `tabs.clear()`로 선택을 잃어 동기화·Apply 후 첫 탭으로 튀던 것. **인덱스가 아니라 소스 신원으로 복원** — refresh 이유 자체가 소스 목록 변화라 인덱스 복원은 다른 소스로 착지 가능) / **진행창 로그에 날짜**(`465e0bc`) / **`biblio_YYYYMMDD.log` 자정 롤오버**(`971109d` — 핸들러가 import 때 한 번 생성되는데 배치가 며칠씩 도므로 파일명 고정 시 전부 시작일에 쌓임 → 레코드마다 날짜 확인)

**2026-07-27 (세션 52, 이어서)** — **Modan2/CTHarvester 프로세스 정렬** — [devlog 080](./devlog/20260727_080_CI_Docs_Parity_With_Sibling_Repos.md)
- 사용자 요청: 두 형제 리포의 테스트·CI·릴리스 프로세스를 충실히 따를 것 + 매뉴얼도 만들 것. 073에서 한 번 맞춘 뒤 벌어진 **격차 차분** 작업
- **CI 추가** (`bdcd3d2`): `dependabot.yml`(pip+actions 주간) / `dependabot-lock-refresh.yml`(requirements 변경 PR에서 lock 자동 재생성 → lock-check 통과) / `manual-release.yml`(workflow_dispatch 릴리스, 프리릴리스·재컷용, 커밋수 build number 일관) / **커버리지 최초 측정 19.6% + floor 18% ratchet**(Linux leg, `papermeister`+`desktop` 스코프, coverage.xml 아티팩트) / C901 복잡도 리포트(비게이팅)
  - **P15 판단 뒤집음**: Dependabot을 "1인 도구 과잉"으로 뺐었는데, 오늘 그 부재로 pytz lock 드리프트가 CI를 red로 만듦(074) → 채택. Modan2와 달리 우리는 `--universal` lock 2개라 워크플로 조정
  - **미채택(근거 기록)**: `test-full.yml`(전체 111개가 2초라 분리할 느린 테스트 없음, 주간 스케줄은 security/codeql이 이미 담당) / `ruff format --check`(대량 format 커밋 선행 필요, P15부터 보류 중)
- **Sphinx 매뉴얼 + Pages 배포** (`6a0989e`): `docs/manual/`(index/installation/quick_start/user_guide/faq/troubleshooting/developer_guide/changelog) + `docs.yml`(en/ko 빌드 → Pages). **내용은 새로 작성** — troubleshooting은 이 프로젝트가 실제 겪은 장애(502/500 크래시 루프, PARTIAL 사유 읽기, Zotero 403/400, conda DLL, WSL 라이브 DB 인덱스 손상)로 구성. `conf.py`가 `version.py`에서 버전 읽음 + `changelog.rst`가 루트 CHANGELOG.md include → **둘 다 single-source**. 한국어는 sphinx-intl 스캐폴딩(미번역 시 영어 폴백이라 ko 빌드도 완전), en/ko 로컬 빌드 확인
  - **후속**: ko `.po` 번역 / **GitHub 저장소 설정에서 Pages source를 "GitHub Actions"로 지정 필요**(안 하면 첫 배포 실패) / `LOCK_REFRESH_TOKEN` 시크릿(선택)

**2026-07-27 (세션 52)** — 상태 점검 + CI 그린 복구 — [devlog 074](./devlog/20260727_074_Lock_Check_Pin_Preference_Fix.md)
- 상태 점검: main clean, `pytest` 81 passed, v0.1.1 릴리스 완료. **본체로 남은 건 references 추출 완주** (마지막 실측 1,733/9,889편, 17.5%). 라이브 DB는 오늘도 쓰이는 중 — WSL에서 read-only 조회는 WAL/NTFS로 `disk I/O error`라 현재 수치 미확인, Windows에서 `scripts/refs_progress.py`로 볼 것
- **`make lock-check`가 upstream 릴리스마다 red 되던 문제 수정**: `lock`은 기존 lock 파일을 핀 선호로 읽는데 `lock-check`는 빈 temp에 컴파일해 전부 fresh 해석 → pytz가 7/25에 2026.3.post1을 내자 소스 변경 0인데 실패. temp를 커밋된 lock으로 seed해 양쪽 해석 조건을 일치시킴 + 의도적 업그레이드용 `make lock-upgrade` 분리. **lock 파일 자체는 stale하지 않아 손대지 않음**. 검증: lock-check 통과 + `tabulate` 임시 추가 시 정상 실패(게이트 살아있음)
- **Qwen 5xx(엔진 재시작)에 짧은 재시도 추가** — [devlog 075](./devlog/20260727_075_Qwen_5xx_Transient_Retry.md). 추출 중 `500 EngineCore encountered an issue` → `502 upstream: All connection attempts failed` 반복 보고. **502는 증상, 진범은 vLLM 엔진 워커 크래시**(OOM 유력, 확정은 서버 로그). `_call_qwen`이 5xx를 `HTTPError`로 그냥 올려보내 논문 하나가 통째로 실패하던 것을 **5xx 전용 예산**(`server_retries=2`, backoff 5s→15s)으로 흡수. 타임아웃 예산과 분리 — 타임아웃은 "배치를 줄여라", 5xx는 "같은 배치를 기다렸다 다시"라 대응이 정반대. **지속 장애는 그대로 raise**(ServerGuard가 pause해야 하므로 — `complete=False`+record_ok로 바꾸면 스트릭이 리셋돼 죽은 서버로 남은 편수를 헛돌게 됨). `tests/test_qwen_retry.py` 6케이스, 87 passed
- ~~실행 중인 앱이 7/24 이전 코드~~ (로그의 `read timeout=240`이 증거) → **세션 말미에 재시작 완료** — 360초 타임아웃 + 5xx 재시도 반영됨. 서버 쪽에도 사용자가 crash 대비 조치를 넣음
- **다음에 엔진이 또 죽으면 확인할 것**: 서버 vLLM 로그의 스택 트레이스(`CUDA out of memory` / `EngineDeadError` / `illegal memory access` / Xid 중 무엇인지) + 그 시각 GPU 메모리 + OCR 동시 실행 여부. 이게 있어야 대응(배치 상한 축소 / `--gpu-memory-utilization` 조정 / refs 도는 동안 OCR 모드 분리)을 고를 수 있음. 우리 쪽 5xx 재시도는 크래시가 논문 실패로 번지는 것만 막을 뿐 크래시 자체는 못 막음
- references 진행률 실측(7/27 12:17 사용자 로그): 배치 **2,188/8,036**, 편당 평균 250초(레퍼런스 1건당 ~4.3초), 표본상 PARTIAL 약 18%
- **PARTIAL 원인 진단** — [devlog 076](./devlog/20260727_076_References_Partial_Cause_Diagnosis.md). 재시작 후 새 배치(6,027편) 첫 5편 중 4편 PARTIAL. ⚠️ **"급증"이 아님(사용자 지적)** — `_refs_targets`가 `references_checked==False`를 **`paper.desc()`** 로 훑으므로, 지난 런에서 checked를 못 받은 PARTIAL/실패분이 **다음 배치 맨 앞에 그대로 재등장**한다. 즉 앞부분은 무작위 표본이 아니라 **재시도 큐**. 배치 크기 역산(8,036−2,188=5,848 vs 새 6,027)으로 **모집단 PARTIAL+실패 ≈ 8~9%**가 11편 표본의 18%보다 신뢰할 만한 추정. 구조적 문제: **재시도 give-up 조건이 없어** 파싱 불가 논문은 매 배치 선두에서 영원히 재시도됨. PARTIAL 발생 지점은 **A) floor에서 타임아웃(서버 무응답)** / **B) HTTP 200인데 JSON 파싱 실패(잘린 출력)** 둘뿐이고, **5xx는 원인이 아님**(075 이후 5xx는 논문 전체 failed로 감). 타임아웃은 WARNING이라 콘솔에 반드시 찍히는데 해당 시간대 `Read timed out`이 없었음(사용자 확인) → **B로 판정**
  - ⚠️ **desktop 앱은 `biblio` 로거에 핸들러/레벨을 안 붙임** — `basicConfig`는 CLI 스크립트에만 있음. 그래서 배치별 사유(`bad JSON for batch N (…)`)가 INFO라 **전부 폐기**되고 WARNING/ERROR만 lastResort로 stderr에 나옴. 파일 로그가 있는 건 `ocr` 로거뿐(`logs/ocr.log`)
  - 가설(미확정, **근거 약화됨**): 생성 도중 vLLM 엔진이 죽으면 프록시가 **부분 응답을 200으로** 반환 → 잘린 JSON = B. 단 위 정정으로 "급증"이라는 설명할 현상 자체가 사라져, 서버 동작 변화보다 **그 논문들 고유 성질**(레퍼런스 블록 구조/언어/OCR 품질 — 목록에 독일어 대문자 제목, 합자 섞인 제목 등)이 더 유력. `max_tokens` 산식상 단순 토큰 초과로도 설명이 약함
  - ✅ **후속 구현 완료** — [devlog 077](./devlog/20260727_077_Biblio_Log_And_Partial_Attribution.md): (a) `biblio` 로거에 `ocr.py`와 같은 파일 핸들러(`~/.papermeister/logs/biblio.log`, DEBUG, 즉시 flush) (b) `extract_references_llm` 반환 4-tuple → **5-tuple**(`skipped={'timeout','bad_json','refs_lost'}`), 호출자 2곳(desktop 워커·`scripts/extract_references.py`) 갱신, `describe_skips()` 헬퍼 → 진행창이 `34 refs PARTIAL (bad JSON x2, 17 refs lost)`로 표시 (c) 파싱 실패 시 **응답 본문 head/tail 400자 + max_tokens를 DEBUG로 기록** — 잘린 응답인지 딴소리인지 구분용 (d) 두 스킵 로그 INFO→WARNING. `tests/test_refs_partial_reporting.py` 5케이스, **92 passed**
  - **재현 절차 불필요**: PARTIAL 논문이 다음 배치 선두에 다시 오므로, 로그 켠 채 다음 배치를 돌리면 바로 원인 확정됨. 데이터 유실은 없으나(unchecked로 남아 재파싱) 버려진 배치만큼 재작업이 쌓이는 중
  - ✅ **레퍼런스 없는 문서의 영구 PARTIAL 루프 수정**(077 §4): `0 refs PARTIAL` 관측(`SVP-Letter-to-Editors` 등, **88초/243초로 끝나 타임아웃일 수 없음**) → 원인은 **레퍼런스가 애초에 없는 문서**. 헤딩 미검출 → 마지막 2p fallback(산문) → 프롬프트에 "없으면 `[]`" 지시가 없어 모델이 산문 응답 → 파싱 실패 → PARTIAL → checked 안 찍혀 **매 배치 선두에 영구 재등장**(서버가 건강해도 영원히 수렴 안 함). 수정: (1) 프롬프트에 "참고문헌 없으면 빈 배열, 산문 금지" (2) `no_array`(배열 부재) vs `bad_json`(배열 절단) **분리 집계** — `JSONDecodeError`가 `ValueError` 서브클래스라 `isinstance`로 명시 판별 (3) **fallback(low) + 배열부재 + 파싱 0 + 타임아웃/절단 없음** 네 조건 모두 만족 시 `complete=True`(checked-empty). high-confidence 블록·부분 파싱·타임아웃은 전부 PARTIAL 유지(보수적)
  - ✅ **토큰 예산 보정 + 절단 에스컬레이션** — [devlog 078](./devlog/20260727_078_Refs_Token_Budget_And_Truncation_Escalation.md). 077 반영 후 첫 PARTIAL(`bad JSON x1, 3 refs lost`)의 `biblio.log`가 **절단을 확정**(파싱 사망 위치=본문 맨 끝 char 6544, tail이 값 중간에서 끊김, `max_tokens=2322`). 실측: 2.8자/토큰, 레퍼런스당 ~107토큰 → **필요 출력 ≈ 입력문자 × 0.87**인데 산식은 `in_chars//2`(0.5배)라 **1.7배 과소**. 수정: (1) `in_chars//2` → `in_chars` (2) 절단 시 **같은 배치를 `_MT_CEILING`(8192)로 1회 재시도** (3) 그래도 안 되고 배치>1이면 **축소 후 재시도**, 엔트리 1개가 상한으로도 안 될 때만 skip. `boost_at`으로 루프 방지, 축소는 `size>MIN`일 때만이라 종료 보장. **상한 8192는 의도적으로 안 올림** — `max_tokens`가 vLLM KV 캐시 헤드룸에 들어가는데 엔진 OOM 정황(075/076)이 있어 압력을 키우지 않으려고, 추정만 정확하게 하고 상한은 실패 시 드문 재시도 경로로만. **왜 중요한가**: 배치 분할·예산이 입력에 대해 결정적이라 skip하면 재시도해도 매번 똑같이 잘려 **영구 PARTIAL**(077 §4 편지 케이스와 같은 비수렴 구조). 테스트 10케이스, **97 passed**
  - ✅ **라이브 검증**: 재기동 후 같은 DETR 논문이 `34 refs PARTIAL (3 refs lost)` → **`53 references, 6 in library`** 로 통과. **+19개** — "3 refs lost"가 실제로는 레퍼런스 19개였음(엔트리 3개 × blob당 6~7개, 절단 응답 6,544자 ≈ 22개 분량과 일치). **blob 가설 실측 확정**
  - 따라서 지표명 `refs_lost` → **`entries_lost`** 로 정정(표시도 `3 entries lost`). 엔트리 수를 세면서 "refs"라 부르면 **심각도를 6배 축소 보고**하게 됨. 실제 손실 레퍼런스 수는 파싱을 못 했으니 알 수 없으므로 아는 척하지 않는 쪽이 정직
  - 배처 거동은 건강함 확인(`1건 42.7s → 8건 62.4s` 정상 워밍업) — 이 논문의 PARTIAL은 서버 문제가 아니었음
  - 🔴 **`[]` 탈출구 회귀 발견 + 수정** — [devlog 079](./devlog/20260727_079_Empty_Array_Escape_Hatch_Regression.md). 077 §4에서 넣은 프롬프트 줄("참고문헌 없으면 `[]`")을 모델이 **CJK 서지에서 남용** → `complete=True` → `references_checked=True` → **레퍼런스 0건으로 영구 확정**(PARTIAL 무한재시도라는 *복구 가능한* 상태를 **조용한 영구 유실**로 바꿔버린 최악의 교환). 라이브 증거: 한국어 논문(엔트리 **47개**, 실제 서지 목록)이 배치당 **0.05초/엔트리**로 응답 — 같은 런 정상 속도 4.4초/엔트리 대비 물리적으로 불가능 → `[]` 확정. 영향 논문 2편(로그상 9/115 배치)
    - 수정: (1) 프롬프트에서 `[]` 조건 축소 + **OCR 잡음·낯선 언어·축약 저널명은 포기 사유 아님** 명시 (2) **코드 가드**: `high` confidence 블록(진짜 섹션을 찾음)인데 파싱 결과 0건 = 모순 → `complete=False`로 UNCHECKED 유지(`empty_result` 집계). 비대칭 근거 — 잘못 checked는 영구 유실, 잘못 unchecked는 재시도 1회. **fallback(`low`)의 `[]`는 checked-empty 유지**(편지 케이스 보존) (3) `refs: block confidence=…, N entries` 로깅 추가 (4) **복구**: `scripts/reset_references.py --scope empty-checked` — `references_checked=1`인데 Reference 0건인 논문의 플래그 해제(지울 데이터 0이라 안전, 진짜 무참고문헌은 같은 판정 재확인). 테스트 12케이스, **105 passed**
  - 🔵 **범위 결정 (2026-07-27, 사용자)**: **참고문헌 헤딩 탐지 정확도 개선은 하지 않는다** — "일반적인 학술지 논문만 잘 처리해도 오케이". 오작동 대상(코스 가이드북·도판·목차·부고·편지)이 애초에 인용 네트워크에 기여하지 않는 문서들이고, 휴리스틱을 더 쌓으면 본류 경로에 회귀 위험만 는다. 보류 항목: 목차 줄 배제(점선 리더+페이지번호), 매치 블록 최소 크기 요구, `low` 블록 추가 가드. **단 077~079의 가드는 유지** — 그건 이상 문서를 *잘 처리*하려는 게 아니라 **조용한 유실·무한 루프를 봉쇄**하는 것이고, 무한 루프는 이상 문서 하나가 매 배치 선두를 점유해 일반 논문 처리량을 갉아먹으므로 **본류를 지키는 비용**임
  - 🔵 **Treatise류(단행본·합본) — 검토 후 보류** (079 §e): fallback이 색인 페이지를 참고문헌으로 변환(`Titanocarcinus`를 저자로). **피해는 갇힘** — `canonicalize_reference`가 제목·DOI 없는 항목을 거부해 `CitedWork` 미생성, 인용 네트워크에 가짜 엣지·노드 없음, 한 번 완료되면 배치 선두도 점유 안 함. 제안했던 규칙 = **`low` + 페이지 수 >~60이면 LLM 없이 checked-empty**(fallback은 짧은 문서에서만 정당; 단 **페이지 수 단독 컷은 금지** — 100~200쪽 계통 개정판은 `high`로 잘 처리됨). 사용자 결정 "일단 그냥 두자, 어떻게 처리해도 애매" → 미구현, 필요해지면 재개. **명시적 기각**: 장별 추출(합본을 컨테이너→챕터로 쪼개는 건 "PDF 하나=Paper 하나" 전제를 갈아엎음). 방향 정리: Treatise류는 **나가는 인용보다 들어오는 인용**이 가치 있고, 그건 biblio 메타데이터 정확도의 문제
  - **미해결**: 일반적 재시도 give-up 카운터는 여전히 없음. 위 수정들이 확인된 두 원인(레퍼런스 없는 문서 / 절단)을 제거하므로 새 로그로 잔류분 규모를 본 뒤 필요성 판단
- 라이브러리 정리: `papermeister.db.corrupt-20260625` / `.pre-p13-backup` 삭제(사용자, ~9GB 회수)
- 미반영이던 **devlog 073**(lockfile + CodeQL + 버전 일치 테스트, Modan2 CI 패리티)을 HANDOFF에 편입

**2026-07-24 (세션 51)** — CI 패리티 — [devlog 073](./devlog/20260724_073_CI_Parity_Lockfiles_CodeQL_Version_Test.md)
- `requirements.lock` / `requirements-dev.lock`(uv `--universal --generate-hashes`) 도입, CI·release는 `pip install --require-hashes`로 설치 → 배포본이 CI가 테스트한 그 wheel임이 증명됨. `Makefile`의 `lock`/`lock-check` + `security.yml`의 lock-check job
- `codeql.yml`(자체 코드 data-flow SAST, push+주간+PR) 추가. ruff `S`(bandit)는 P15부터 이미 보유
- `tests/test_version_consistency.py` — `version.py` 단일 소스 일치 검증

**2026-07-23 (세션 50)** — 상태 점검 + **P14 계획/착수** (references 진행 모니터 + 인용 네트워크) — [devlog P14](./devlog/20260723_P14_Citation_Matching_And_Network.md)
- HANDOFF 상단이 세션 49(P11 "라이브 대기")에 멈춰 있어 git log(P12/P13/065~068)와 어긋남을 발견 → **Windows 라이브 DB(2.3GB)를 WSL 로컬로 복사 후 스키마·카운트 실측**으로 실제 진행 확정
- **P13 FTS 마이그레이션 적용 완료 확인**: `passage_fts` external-content + standalone `paper_fts` + 트리거 9종, `passage_fts_content` 부재, `pre-p13-backup`(4.3GB) 존재, `quick_check=ok`. DB 4.3→2.3GB
- **P11 references 부분 실행 + P12 CitedWork 정규화 라이브 확인**: `references_checked` 1,737/9,828편(17.7%), `Reference` 104,889행(held 13,123 / external 58,473), `CitedWork` 49,728노드
- **P14 계획서 커밋** (`2a0dc35`): 참조 매칭 품질(A1 증분 재-resolve / A2 감사) + 인용 네트워크(L0 통계 / L1 export / L2 ego-view / L3 공동인용). 착수 순서 L0→A2→L1→A1→(L2/L3 추출 후)
- **구현·검증·커밋 (read-only, Windows 실행 전제)**:
  - `scripts/refs_progress.py` — 추출 진행률/처리율/ETA 모니터(`--watch`)
  - `scripts/citation_stats.py` (L0, `1d01402`) — held→held 그래프 통계(3,831노드/12,038엣지 @17.6%)
  - `scripts/export_citation_graph.py` (L1, `1d01402`) — nodes/edges CSV + GEXF(Gephi), `--with-external`
  - `scripts/audit_matches.py` (A2, `8ed8591`) — 매칭 감사. **실측 발견**: title 매칭 12,925 중 4,279 의심(FP, 예: "On Growth and Form" 오연결), 제목이 보유논문과 일치하는데 미연결 4,403(FN, 예: 완전일치인데 unresolved)
- **A2 후속: `resolve_one` 스코어러 보강 완료** (`4f27773`): containment(inter/min) 단독 → **containment+Jaccard 블렌드**(짧은 제목이 긴 제목에 박혀 1.0 나던 FP 차단) + **near-exact 토큰셋 강신호**(year mismatch veto 면제, exact-title FN 회수). 오프라인 A/B(라이브 스냅샷, fresh 재-resolve 동반): held 9,339 유지 · **FP 3,225 제거** · 597 재연결 · **FN 7,697 회수**(일부는 재-resolve 효과). ⚠️ **라이브 추출은 OLD 코드 메모리 상주** — 새 스코어러는 **추출 재시작 후** 신규 논문에 적용, 기존 refs 반영엔 **재-resolve 패스(A1) 필요**
- **references 진행창 Cancel 버튼 추가** (`7734da1`, 사용자 요청): 대기 큐 비우고 진행 중 1편만 마무리(LLM 호출 중단 불가). `ReferencesWindow.cancel_requested` 시그널 + `mark_cancelling`, main_window `_ensure_refs_window`/`_cancel_refs`. `_active` 플래그로 begin() extend 오판 수정. offscreen 스모크 통과
- **서버 다운 견고성 2건** (사용자 지적):
  - **부분 파싱을 checked로 안 찍기** (`8c15cdc`): 데스크톱 워커가 `extract_references_llm`의 `complete` 플래그를 무시하고 `references_checked=True`를 무조건 찍던 버그 → 서버 죽으면 부분/빈 결과인데 done 처리돼 재파싱 영영 안 됨(조용한 데이터 유실). CLI(`extract_references.py`)처럼 `complete=True`일 때만 stamp, 부분결과는 unchecked로 남겨 재파싱(save_references delete-and-replace라 중복 없음). **적용하려면 소스(`python -m desktop`) 재시작 필요 — 옛 .exe 아님**
  - **서버 다운 시 자동 정지→일시정지+자동복구로 진화** (`f12b03c`→`bb1d7b1`→`31c6e35`→`0859040`): 연속 실패 3회 → LLM 엔드포인트 직접 핑(`biblio.references_server_alive`, max_tokens=1로 slow≠down 구분) → 죽었으면 **큐 유지한 채 Pause**, 60초마다 백그라운드 폴링 → 서버 복구 시 **자동 Resume**(무인 실행 대응). 일시적 blip이면 스트릭 리셋 후 계속. Cancel은 pause 중에도 동작. `complete=True`(파싱 or no-ref)가 스트릭 리셋해 오탐 방지
  - **공유 `ServerGuard` 추출** (`31c6e35`, `desktop/workers/server_guard.py`): streak+확인핑+복구폴링+pause/resume 콜백 상태머신. 큐는 호출자 소유, guard는 "언제 멈출지/복구됐는지"만. references 이관(behavior-preserving) + 유닛 스모크 통과
  - **biblio에도 적용** (`0859040`): BiblioWindow에 Cancel + pause/resume, `_biblio_guard`. `biblio_server_alive()`는 **qwen 백엔드만 폴링**(claude는 폴링할 서버 없어 True 반환→pause 안 함). 유효 pred=record_ok(다운스트림 apply 실패해도), 추출 err/task.failed=record_fail
  - **OCR에도 적용 완료** (`fe4e691`, `papermeister/ui/process_window.py`): ProcessWorker에 연속실패 streak + `_pause_if_server_down()` — 3연속 실패 시 `ocr.is_ready()` 확인 → 죽었으면 **워커 루프 안에서 30초 폴링하며 대기**, 복구 시 resume, Cancel 시 탈출. `_run_parallel`(pool)·`_run_wrapper_pipeline`(제출) 두 루프 모두. **`ServerGuard` 미사용** — OCR은 자체 QThread 루프라 인라인 `sleep+is_ready()`가 더 단순(메인스레드 QTimer 불필요). `is_ready()`가 백엔드별(pod/wrapper/serverless) 분기라 새 헬스프로브 불필요. 진행 메시지는 기존 progress 시그널로 ProcessWindow 로그에 표시. **"동결" ProcessWindow지만 OCR 워커는 실질 활성 유지 엔진이라 일관** (사용자 승인). 유닛 스모크 통과(no-op/blip리셋/down→resume/cancel)
- **코드 품질 인프라 도입 (P15, ../Modan2 가이드 기반)** — [R01 검토](./devlog/20260723_R01_Code_Quality_Guide_Adoption.md) · [P15 계획](./devlog/20260723_P15_Code_Quality_Adoption_Plan.md)
  - **CLAUDE.md에 `R##`(리뷰/감사) devlog 타입 추가**. R01(판단)→P15(실행계획)→999(기록) 3단 구조
  - **Phase 1 (ruff)** `7e110ca`: `pyproject.toml` curated 룰셋(base+DTZ+RUF012+S; 스타일 SIM/RET/PIE/A는 후속 패스), Qt camelCase·의도적패턴 ignore(사유 명시), 61파일 자동+수동 수정. **`ruff check` clean**, 전 모듈 import OK, **requires-python ≥3.12**
  - **Phase 2 (pytest)** `1afde45`: pytest 설정(markers unit/ui/integration) + `requirements-dev.txt` + `tests/`(conftest headless Qt) — test_references(P14 스코어러 회귀)·test_paper_service(CJK 저자)·test_server_guard·test_smoke(전 모듈 import). **72 passed**. "픽스마다 회귀 테스트" 관례 시작
  - **Phase 3 (CI + 서버 패키징·릴리스)** `c3f3f3f` — **Modan2 미러**. `.github/workflows/`: `test.yml`(ruff lint 게이트 + {ubuntu,windows}×3.12 매트릭스, import 스모크+pytest, `workflow_call` 노출), `reusable_build.yml`(Windows 전용 clean-pip PyInstaller onedir→portable zip), `build.yml`(수동 `workflow_dispatch`만—커밋 잦아서), `release.yml`(태그 `v*.*.*`→test→build→gh-release+SHA256). `version.py`(0.1.0) + build_number=commit count. **라이브 미검증**: windows-latest `pyinstaller PaperMeister.spec` 실빌드는 첫 CI가 확인(spec conda 가드로 pip-CI 표준빌드 기대). 후속: Inno Setup 설치본/아이콘/mac·Linux 레그/CHANGELOG
  - **Phase 3 라이브 검증 완료**: CI(test.yml) Linux·Windows 그린, Windows PyInstaller 빌드 그린(portable zip), 액션 버전 Node24로 최신화(`a468131`). `pythonpath=["."]` 픽스(`885adf4`)로 plain `pytest`의 import 해결 — CI가 잡은 실버그
  - **첫 릴리스 태그 `v0.1.0`** push → release.yml(test→build→공개 Release+SHA256) 트리거
  - **Phase 4 (excepthook + pre-commit)** `cc94e4a`: `desktop/app.py`에 전역 `sys.excepthook`(미처리 슬롯 예외 로깅+비치명 다이얼로그, KeyboardInterrupt는 위임) + `.pre-commit-config.yaml`(ruff --fix + 파일위생; ruff-format은 format 패스까지 보류) + excepthook 회귀 테스트. **73 passed**
  - **Phase 5 (deps 보안 + mypy 코어, vulture 제외)** `592996b`: pip-audit로 Pillow 10(CVE 다수)·requests 2.31·python-dotenv 발견 → **python-dotenv 제거**(미사용—main.py가 .env를 plain open()으로 읽음), Pillow≥12.3.0·requests≥2.33.0 버전업(pip-audit clean). `security.yml`(pip-audit push/PR/주간, Modan2 미러). mypy 설정 + **references/search/biblio 3모듈 mypy-clean → CI lint 게이트**(점진 확장). ⚠️ **사용자: Windows env에서 `pip install -r requirements.txt --upgrade` 후 OCR 이미지(Pillow) 동작 확인 필요**
  - **Phase 6 (인코딩 + 패키징 체크리스트)** `c9e5441`: 텍스트 `open()` 잔여 3곳(main.py .env, refs_progress state json)에 `encoding='utf-8'` — 이제 미명시 text open() 0건. `docs/RELEASE.md`(릴리스 런북 + 프로즌 아티팩트 스모크 체크리스트)
  - **✅ P15 전 6단계 완료**. **미실행(의도적)**: `ruff format` 대량-diff 커밋, vulture(데드코드, 사용자 제외), 엄격 coverage gate/Dependabot/코드사이닝(1인 도구 과잉)
  - **P15 후속 추가**: `scripts/verify_image.py`(OCR Pillow 경로 1-커맨드 검증 — Windows Pillow 12.3.0 PASS 확인) + **크로스플랫폼 패키징 3레그 완성** (`8cc7fd7` Inno Setup, `47b584b` Linux AppImage, `b6c563f` macOS DMG):
    - **Windows**: portable zip + Inno Setup 설치본(`installer/*.iss.template`, per-user)
    - **Linux**: AppImage(`packaging/linux/create_appimage.sh`, appimagetool `EXTRACT_AND_RUN`)
    - **macOS**: DMG(`packaging/macos/create_dmg.sh`, onedir→.app→hdiutil, **미공증**)
    - reusable_build 3 job, release가 4종(zip/exe/AppImage/dmg)+SHA256 첨부. **수동 Build로 3플랫폼 전부 빌드 검증 완료**
  - **인용 네트워크 그래프 시각화** (P14 L2, [devlog 072](./devlog/20260724_072_Citation_Network_Ego_Graph.md), `828bb4e` 등): 논문 우클릭 "Show in citation network" → ego-network(선택 논문 1~2홉) `QGraphicsView` force-directed. **전체 네트워크**(held `resolved_paper` + 외부 `CitedWork` `resolved_work`). 2채널: **채움색=방향**(피인용 초록/인용 앰버/상호 시안/2홉 회색), **테두리=보유**(굵은실선 PDF보유/얇은실선 held/점선 external). 클릭=재중심(held만), Open in list=리스트 reveal. `paper_service.load_ego_network`. 라이브 확인 대기
  - **v0.1.1 릴리스** (`e49fa39` + 태그 `v0.1.1`): `CHANGELOG.md`(Keep a Changelog) 신설 + release.yml이 **CHANGELOG 섹션을 awk 추출해 릴리스 노트로** (Modan2 방식). 3-OS 아티팩트 + 노트로 **release 파이프라인 end-to-end 검증 완료**. 다음 릴리스: CHANGELOG 섹션 추가 → version.py 범프 → 태그 push
  - **구현 기록**: [069](./devlog/20260723_069_Citation_Matching_And_Network_Implementation.md)(P14) · [070](./devlog/20260723_070_Server_Down_Resilience.md)(서버 복원력) · [071](./devlog/20260724_071_Code_Quality_And_Cross_Platform_Release.md)(P15+릴리스) · [072](./devlog/20260724_072_Citation_Network_Ego_Graph.md)(그래프)
  - 릴리스 후속 잔여(저순위): 앱 아이콘, macOS 코드사이닝/공증. 다음 실질 작업: **references 추출 완주**(진행 중) → 완료 후 재-resolve/normalize 재실행
- **A1 재-resolve + 정규화 라이브 실행 완료** (Windows, 앱 닫은 상태): `resolve_references.py --reresolve --execute` → `normalize_works.py --pass 1 --execute` → `--pass 2 --execute`(~61분, LLM 병합). **효과(라이브 DB 실측)**: unresolved **31.7%→4.3%** 급감, held 13,123→**17,671**, external 58,473→**83,388**, held→held 엣지 12,038→**17,089**, active CitedWork 49,728→**59,963**(pass1이 미분류 인용을 canonicalize → 순증, pass2가 near-dup 5,989 제거). `quick_check=ok`
  - **병합 품질 spot-check 통과**: `match_method='work-llm'` 7,955 refs 샘플 검사 — 전부 같은 문헌의 OCR/철자/음차 변형(키릴 혼입까지 정상 병합), Hupé 1953/1955 Part1/2를 연도로 구분 유지(과대병합 없음). borderline 1건(work#20427 Whittington), out-degree 이상치 1건(Education 2005, 367)만 관찰 대상
  - **다음**: PaperMeister 재시작(새 스코어러 + Cancel 버튼 반영) → 추출 재개. 추출이 더 진행되면 재-resolve 한 번 더(멱등). 증분 재-resolve 훅(sync 콜백)·L2/L3(인앱 ego-view / 공동인용)은 이후
- 참고: `.papermeister/papermeister.db.pre-p13-backup`(4.3GB, 6/26)는 검증 종료 후 삭제 가능 → **세션 52에서 `corrupt-20260625`와 함께 삭제됨**

**2026-06-25 (세션 49)** — [devlog P11](./devlog/20260625_P11_References_Extraction_Citation_Network.md)
- **P11 References 추출 + 인용 네트워크 (Phase 1) 설계 + 코드 작성** — 논문 본문 references 섹션을 파싱해 인용 네트워크의 토대 구축. held(PDF 보유) vs cited-only(외부) 구분이 핵심 요구
- **결정** (사용자 확정): Phase 1만 먼저(`Reference` 테이블, 외부노드 dedup `CitedWork`는 Phase 2로 분리) / 파싱 엔진은 ocrserver Qwen3 32B 단독(claude -p 불가, 무료·CJK 강건) / devlog 계획서 작성 후 구현
- **프레이밍**: references는 "파생 레이어" — OCR JSON이 source of truth라 언제든 재생성 가능. raw 문자열만 보존하면 됨(PaperBiblio식 전버전 보관 불필요). 추출↔해소 2패스 분리(extract_biblio↔reflect_biblio 철학)
- **산출물**: `Reference` 모델 + `biblio.py`(섹션 위치 휴리스틱/엔트리 분할/Qwen 배열 파싱) + `scripts/extract_references.py` + `scripts/resolve_references.py`(DOI→FTS-style 토큰 후보→year+저자 스코어). 모두 `--execute` 컨벤션
- **검증(WSL)**: compile + 휴리스틱/resolve self-test 통과. **라이브(Windows+ocrserver)는 사용자 검증 대기**

**2026-06-17 (세션 48)** — [devlog 063](./devlog/20260617_063_Search_Title_Boost_And_Highlighting.md)
- **검색 품질 — document-level title boost**: `passage_fts`가 passage 단위라 title×10 가중치가 문서 전체엔 안 먹던 "trilobite 문제" 해결. `search.search()`에 Python 재랭킹(별도 paper_fts 없이) — `query_terms` 토큰화(CJK 보존) 후 3-tier(전부 제목 매치/일부/없음) 정렬, tier 내부 BM25. 검증: 본문 8회 vs 제목 1회 → 제목 매치 1위
- **매칭 패시지 하이라이트**: (a) 검색 결과 행 툴팁 — `PaperRow.snippet`(FTS snippet→HTML, 매치어 bold) 추가, `_populate`가 툴팁 설정. (b) OCR Text 탭 인라인 하이라이트 — `DetailPanel.set_search_terms` + `_apply_search_highlight`(QTextDocument.find → ExtraSelection amber 오버레이, 문서 무손상, 첫 매치 스크롤). main_window가 검색 시 term 전달, 이탈 시 클리어
- 검증: 토크나이저(영문/구문/boolean/CJK), snippet HTML escape+bold, 하이라이트 2매치→2 selection+클리어, search_papers snippet 부착

**2026-06-15 (세션 47)** — [devlog 062](./devlog/20260615_062_Desktop_Local_Folder_Import.md)
- **desktop 앱에 로컬 폴더 PDF 가져오기 추가** — Zotero 아닌 local directory를 DB화. 백엔드(`import_source_directory` + OCR/biblio directory 지원)는 이미 완비, 빠진 UI 트리거만 추가
- Rail에 'import' 액션 + `import.svg`(folder-plus, Lucide 스타일) / `MainWindow._import_folder`(QFileDialog → `BackgroundTask` 스캔 → SourceNav refresh → 그 소스 pending "지금 OCR?" 확인 → ProcessWindow 재사용)
- 멀티탭은 SourceNav가 이미 소스마다 탭 생성이라 추가 작업 0 (Zotero 'My Library' + 폴더명 탭들)
- worker는 ORM 객체 대신 plain tuple 반환(peewee thread-local), 루트 직속 PDF도 `_scan_dir`이 루트 Folder 먼저 만들어 join 누락 없음
- 검증: compile/import OK, headless Rail 빌드 + import 아이콘 렌더 확인. **실제 폴더 스캔→OCR end-to-end는 사용자 Windows(RunPod) 검증 필요**

**2026-06-15 (세션 46)** — [devlog P02](./devlog/20260615_P02_PyInstaller_Desktop_Packaging.md) · [devlog 061](./devlog/20260615_061_PyInstaller_Conda_DLL_Troubleshooting.md)
- 라이브러리 전체 biblio 작업 완료 보고받음 (Phase D 대량 운영 마무리)
- **PyInstaller 패키징 완료**: `python -m desktop` → onedir `dist\PaperMeister\PaperMeister.exe`. 빌드 성공 + 실행 검증(Qt/SQLite/SSL/PyMuPDF/FTS5 동작)
- 산출물: `run_desktop.py`(entry), `PaperMeister.spec`(onedir, `PM_ONEFILE`/`PM_CONSOLE` 토글), `build_desktop_clean.bat`(검증된 클린 빌드), `build_desktop.bat`(conda 직접 — 권장 안 함), `.gitignore`에 build/dist/.build-venv
- 번들 대상: **SVG 아이콘 7개가 유일한 소스-상대 리소스**(코드 수정 0). `claude` CLI는 외부 의존(biblio만 영향), `~/.papermeister`는 런타임 생성
- **conda DLL 함정 트러블슈팅(devlog 061)**: conda 셸 직접 빌드 → 프로즌 앱이 `QtWidgets` DLL "procedure not found"로 사망. 원인은 conda의 Qt-의존 DLL이 번들에 섞임(VC런타임 셰도잉은 헛다리, onefile도 동일). **해결: conda OFF PATH인 venv에서 빌드**(플레인 cmd + conda env python을 venv base로). 그랬더니 conda가 `Library\bin`에 숨긴 `sqlite3.dll`/openssl 누락으로 "SQLite driver not installed" → spec이 `sys.base_prefix\Library\bin`에서 stdlib 지원 DLL만 콕 집어 보강. 최종 정상 동작
- **빌드는 conda 직접(`build_desktop.bat`) 금지, `build_desktop_clean.bat` 사용** — HANDOFF/devlog에 명문화

**2026-06-10 (세션 45)** — [devlog 060](./devlog/20260610_060_Library_Wide_Process_All.md)
- **'My Library' 우클릭 Process All** (commit `2bf9519`): source 루트 우클릭이 Source.id를 folder_id로 해석해 무동작이던 버그 → `_run_process_scope(folder_ids|None)` 리팩터. None=라이브러리 전체(PaperFolder join 생략, uncollected 포함). pending/failed PDF OCR + biblio 없는 processed PDF 추출을 한 배치로
- **라이브러리 전체 biblio 작업 가동 개시** — OCR 99.9% 완료 상태라 사실상 biblio 추출 + auto-apply가 본체. 중단돼도 Process All 재실행이 곧 resume

**2026-06-09 (세션 44)** — [devlog 057](./devlog/20260609_057_Single_Biblio_Queue_Unification_Status_Consistency.md) · [devlog 058](./devlog/20260609_058_OCR_Force_Retry_Empty_Failed_Legacy_Cache.md) · [devlog 059](./devlog/20260609_059_Writeback_Standalone_Guards_Execute_Flag.md)
- **단건 Extract Biblio 큐 단일화** (`d38027b`, `4c0f632`): 우클릭 단건 추출이 자체 BackgroundTask로 배치와 동시 실행되던 문제 → 공유 `_auto_biblio_queue` enqueue + drain. 단건도 BiblioWindow 진행창 (배치 live면 total +1)
- **추출 실패 표면화** (`1a827bf`): biblio `task.failed`가 큐만 drain하고 진행창을 안 건드려 멈춘 듯 보이던 문제 → `_on_biblio_failed`로 통일 (error 행 + advance/finish)
- **레거시 OCR 캐시 rename** (`1a827bf`): 1970s 5편(캐시 8개)이 옛 `{sha256}.json` 이름 잔존 (세션 42 마이그레이션이 JSON sibling 없는 케이스를 스킵) → `load_ocr_pages` glob 미스매치로 "No OCR pages found". `scripts/rename_legacy_cache.py` 신설 (cache-only, idempotent)
- **marker PaperBiblio** (`3b753d8`): OCR JSON meta=applied인데 로컬 PaperBiblio 없는 paper(DB 재구축 케이스)가 매 run마다 `BiblioAlreadyApplied` skip으로 영원히 done이 안 되던 문제 → skip 시점에 Paper의 현재 메타데이터로 marker PaperBiblio 생성
- **write-back standalone 가드** (`d301652`, `c8a932f`): promote의 `lastRead` echo 거부(세션 43 rename_ocr_json과 동일 버그) → pop + transient-retry 경유. un-promoted standalone에 write-back 시 `'date' is not a valid field for type 'attachment'` 400 → attachment 타입이면 `ZoteroPatchRejected`로 "먼저 promote" 안내
- **scripts `--execute` 통일** (`a781ae7`, `c8a932f`): `reflect_biblio` / `rename_ocr_json` / `upload_ocr_json`의 옛 `--dry-run` 관례 + `promote_processed_standalones`의 `--apply`를 전부 `--execute`(기본 dry-run)로. CLAUDE.md에 관례 명문화
- (force=true 재OCR `09e233d`, 빈 OCR failed `d73f221`, already_complete done stamp `eccf754`, needs_review pill `b0920a7`은 세션 43 항목에 선반영되어 있음 — devlog 057/058에 상세 기록)

**2026-06-08 (세션 43)** — [devlog 047](./devlog/20260608_047_OCR_JSON_Rename_Resume_LastRead_Fix.md)
- 세션 42에서 창 닫아 **중단된 OCR JSON 파일명 마이그레이션 완주** (`{hash}.json` → `{pdf_basename}.{hash[:8]}.json`)
- idempotent 재실행으로 이어감: 1차 7,816 성공 + 6 Zotero failures, 2차 재시도로 잔여 클리어. 최종 **9,924/9,935** 마이그레이션 완료
- **`lastRead` PATCH 버그 픽스** (`scripts/rename_ocr_json.py`, commit `3c297aa`): 일부 attachment의 서버 read-only 필드 `data.lastRead`를 fetch한 item dict 그대로 `update_item`에 echo → Zotero가 `Invalid keys present in item 1: lastRead`로 거부. PATCH 직전 `item['data'].pop('lastRead', None)`. `numPages` 등은 보존(쓰기 가능 필드일 수 있어 `lastRead`만 제거)
- **orphan 8개 cleanup 완료**: 처리 불가 레거시 `{hash}.json` 8편 (id `3178/3996/4053/4059/4082/4164/4201/7230`) — PDF 교체로 남은 stale 중복(hash=empty, 논문은 이미 현재 PDF의 정상 JSON 보유). `scripts/cleanup_stale_ocr_json.py` 신설(기준 재계산 + 논문 유일 OCR 보호 가드 + dry-run 기본)로 Zotero 첨부 8 + DB row 8 삭제, PDF/정상JSON 무손상 검증. 최종 9,924/9,935 새 형식, 레거시 0
- 실행 메모: 라이브 DB/캐시/preferences는 Windows 홈(`C:\Users\Jikhan Jung\.papermeister`), 실제 실행은 Windows native Python(Anaconda). WSL에선 `/mnt/c`의 DB를 read-only 조회만
- 시행착오: read-only 진척 쿼리 휴리스틱 `GLOB '[0-9a-f]*' AND length=69`이 69자+hex로 시작하는 새 이름 3개를 레거시로 오탐. 점 개수(`{64hex}.json`은 점 1개) 검증으로 정정
- **404 PDF 진단 + 로컬 storage 복구** ([devlog 048](./devlog/20260608_048_Failed_PDF_Local_Storage_Recovery.md)): failed PDF 13편을 로컬 Zotero storage + zotero.sqlite linkMode로 대조. 로컬 PDF 실재 2편(WIZC6QDZ/3MK6XEI2)은 서버에 이미 있었고(`unchanged`) 원래 failed가 stale → status 리셋 재시도로 OCR 성공. `scripts/upload_missing_zotero_files.py` 신설(로컬 PDF→Zotero 업로드, PDF만)
- **첨부 확장자 게이트 + `skipped` status** ([devlog 049](./devlog/20260608_049_Attachment_Extension_Gate_Skipped_Status.md)): 비-PDF 첨부(보충자료/책/.doc 등)가 OCR 큐에 들어가 `failed`로 쌓이던 문제. `papermeister/file_utils.py` 신설(`attachment_status`/`has_non_pdf_extension`), ingestion 4개 생성 지점이 JSON→processed/PDF→pending/그외→`skipped` 분류. process_paper_file·wrapper 방어 가드(bare-key PDF 오분류 방지 위해 `has_non_pdf_extension` 사용). desktop pill `skip` 추가 + `_primary_file` PDF 우선. `scripts/reclassify_attachments.py`로 기존 35편(.djvu15/.doc8/.txt4/...) failed→skipped 보정. 후속: failed 잔존 80편 = linked_url 75(URL 링크, bare-key라 확장자로 분류 불가) + imported_file PDF 5(진짜 실패). `scripts/reclassify_linked_attachments.py`(zotero.sqlite linkMode 기반)로 linked_url 75→skipped. 최종 **processed 19,887 / skipped 110 / failed 5**(서버·로컬 둘 다 파일 없는 ML PDF). `_primary_file` 수정으로 linked_url이 paper 대표가 되어 `err` 뜨던 표시 버그도 해소
- **Zotero 영구 삭제(empty-trash) 미러** ([devlog 050](./devlog/20260608_050_Permanent_Deletion_Empty_Trash_Sync.md)): trash에서 영구 삭제한 item이 PaperMeister에선 restore되던 갭(영구삭제 vs 복원 구분 불가). `zot.deleted(since=N)` 기반 `apply_permanent_deletions`(worker Phase 3a, trash sync 직전) + `zotero_deleted_version` 증분. cascade 삭제 + passage_fts 수동 정리, OCR 캐시 보존. backlog 2편(Segment Anything/Triplet Loss, 이미 silently restore됨)은 `scripts/purge_deleted_zotero.py --since 0`로 청소. failed 5→3
- **failed PDF 재OCR 시 `force=true`**: 서버가 `force=true` 폼 옵션(기존 JSON 무시하고 재OCR) 지원하게 수정됨에 맞춰, failed PDF를 OCR할 때 이를 전달. `wrapper_submit(force)` → POST `force=true`, `ocr_pdf`/`process_paper_file(force)`는 로컬 캐시·sibling JSON도 무시. `ProcessWorker.force_ids` 셋으로 전달 — desktop 우클릭 Retry(단건) + Process Folder의 failed_ids가 force 대상. pending/일반 Process는 캐시 사용(force 안 함)
- **OCR 빈 결과 'failed' 처리**: OCR이 0페이지/텍스트 없음 반환 시 `process_paper_file`이 'processed' 대신 'failed'(failure_reason='ocr_empty'). 기존 4편은 `scripts/reset_empty_ocr.py`로 빈 캐시 삭제+pending 리셋
- **already_complete를 done으로 stamp**: `evaluate`가 `already_complete`(추출값이 Zotero와 완전 일치 → skip)로 본 fresh biblio는 status가 `extracted`로 남아 'OCR' pill이었음. reflect_all + desktop이 이를 terminal `auto_committed`(review_reason='already_complete')로 stamp → 'done' pill + 재평가 대상에서 제외. (already_applied/already_committed는 이미 terminal이라 손 안 댐)
- **목록 pill에 needs_review/auto_committed 반영**: 기존 `_row_from_paper`는 processed면 `applied` biblio만 'done'으로 바꾸고 needs_review는 'OCR'과 동일하게 보임. 이제 `{applied, auto_committed}` → 'done', `needs_review` → 'review'(rev, 주황) pill. desktop `_on_biblio_extracted`의 needs_review 분기가 `biblio.status='needs_review'` stamp(+refresh_row)하도록 추가 → 목록 pill·Library "Needs Review" 필터 일관. (reflect_all로 적용된 auto_committed 98편도 이제 'done'으로 보임)
- **batch biblio 견고성** ([devlog 056](./devlog/20260609_056_Batch_Biblio_Robustness_Zotero_Transient_Errors.md)): (1) `_on_biblio_extracted`가 ZoteroWriteAccessDenied/PatchRejected만 잡아 다른 예외(예: Zotero 503)가 Qt 슬롯 밖으로 빠지면 큐 drain이 끊겨 배치 멈춤/크래시 → try/except/finally로 감싸 항상 drain. (2) write-back Zotero 호출(fetch/update/item_template)에 transient 재시도(`_zotero_retry`: 500/502/503/504/연결/타임아웃만 2회 backoff, **429 rate-limit은 의도적 제외**). 메인 스레드라 재시도 bounded(~7s)
- **biblio 추출 프롬프트에 PDF 파일명 힌트** ([devlog 055](./devlog/20260608_055_Biblio_AutoCommit_Policy_Relaxation_And_Filename_Hint.md)): 파일명에 저자/연도가 인코딩된 흔한 패턴(`Smith2023.pdf`, `Brock & Holmer 2004.pdf`)을 활용. `extract_biblio_llm(file_hash, backend, filename)` 파라미터 추가 → 프롬프트에 `--- SOURCE FILENAME ---` 블록("evidence, not a guess; 본문이 명확하면 본문 우선"). desktop 두 추출 경로가 `os.path.basename(pf.path)` 전달. 기존 추출분은 재추출해야 적용됨(reflect는 재평가만)
- **evaluate 소프트 게이트 완화 (stub/placeholder)**: 기존엔 `missing_year`/`visual_review_flag`/`confidence!=high`면 promoted standalone(title=파일명)도 needs_review로 빠짐. `relaxable = _is_stub_paper(paper) or title_is_filename_placeholder(...)`(헬퍼 public화)이면 **missing_year·visual_review_flag·medium-confidence 모두 통과 → auto_commit**. 단 hard gap(missing_title/authors/unknown_doctype) + low-confidence는 여전히 보류, curated 논문은 full 게이트 유지
- **(아래 desktop biblio batch 항목들 → [devlog 054](./devlog/20260608_054_Desktop_Biblio_Batch_Workflow.md))**
- **biblio 진행 창 (`desktop/windows/biblio_window.py`)**: 폴더 batch biblio 추출 시 OCR ProcessWindow처럼 팝업으로 per-paper 요약(`[n/N] applied — "제목" · 저자 et al. · 연도`, 종류별 색상) + 진행바 + 집계 표시. main_window의 기존 직렬 biblio 큐가 구동(begin/set_current/record/finish), post-OCR auto-biblio 합류 시 `add_total`로 total 동기
- **컬렉션 Process Folder가 biblio extraction까지 처리**: OCR이 다 끝난 폴더에서 우클릭 Process가 pending/failed만 보고 빈 목록→무동작이던 문제. 이제 `processed` PDF 중 PaperBiblio 없는 paper를 수집해 `_auto_biblio_queue`로 넣어 추출(이미 biblio 있는 건 skip). 다이얼로그에 OCR/Biblio 카운트 분리 표시, 둘 다 없으면 "Nothing to do" 안내
- **biblio apply 후 PaperList 행 갱신**: 우클릭 Extract Biblio 자동 적용/수동 Apply 후 목록의 status pill만 갱신되고 Title/Authors/Year는 stale하던 문제. `paper_service.row_for_paper(paper_id)` + `PaperList.refresh_row(paper_id)`(행 전체 재조회·재기록) 신설, `_on_biblio_extracted`(auto/skip 분기) + `_on_apply_completed`에서 `update_status` 대신 호출
- **write-back 저자 firstName/lastName 분리**: 자동 write-back이 single-field `name` 대신 가능하면 firstName/lastName 분리(`_author_creators` + CJK 포함 `_split_first_last`: 일본 4→2/2, 한국 3→1/2, mononym/조직은 single-field). `_compute_patch` + itemType 승격 payload + override 경로 모두 적용. desktop `split_author_name`과 동일 휴리스틱
- **write-back itemType 자동 승격 + volume/issue/pages 추출** ([devlog 053](./devlog/20260608_053_Biblio_ItemType_Upgrade_And_Volume_Issue_Pages.md)): promoted standalone(`document`)에 Extract Biblio 시 journal이 추출돼도 안 들어가던 문제(document엔 journal 필드 없음). `DOC_TYPE_TO_ITEM_TYPE` + `_build_type_upgrade_payload`(template 기반)로 doc_type→실제 itemType 승격(placeholder 제목일 때만) → journal/volume/issue/pages 유효해짐. `PaperBiblio`에 volume/issue/pages 컬럼 + 마이그레이션, 3개 프롬프트(biblio.py/extract_biblio/vision) + 4개 create 지점 갱신. `_compute_patch`는 `f in data`로 타입별 필드 유효성 자동 판정(400 방지). 기존 auto_committed는 재추출 필요
- **biblio write-back 파일명 placeholder 제목 덮어쓰기** ([devlog 052](./devlog/20260608_052_Biblio_Title_Override_For_Filename_Placeholder.md)): promoted standalone(title=PDF 파일명)에 Extract Biblio 시 authors/year/journal만 반영되고 제목은 파일명 잔존하던 문제. `zotero_writeback._compute_patch`의 empty-slot title 규칙에 `title_overridable` 추가 — 현재 title이 PDF 파일명(base/stem)과 일치하면 추출 제목으로 덮어씀. `_title_is_filename_placeholder` 헬퍼. 일반 curated 제목은 보존
- **Phantom 부모 promote 복구** ([devlog 051](./devlog/20260608_051_Refix_Phantom_Promoted_Standalones.md)): Zotero 9892 vs PM 9889 차이 추적 → standalone auto-promote(세션 36)가 만든 parent를 사용자가 Zotero에서 삭제(`/deleted` 보존창보다 오래돼 050으로도 못 잡음) → PM에 phantom parent 잔존. `scripts/refix_promoted_standalones.py`(zotero.sqlite로 실재 안 하는 Paper.zotero_key 탐지 → demote → `promote_standalone_with_filename` 재promote → PDF/JSON 재parent). 2편(Temple1980 4WWSF34U, Holloway1981 DMGQHSKW) 복구. **차이는 데이터 누락 아니라 promote key 드리프트였음**

**2026-06-05 (세션 42)** — [devlog 046](./devlog/20260605_046_OCR_JSON_Filename_Migration.md)
- OCR cache + Zotero sibling attachment 파일명을 hash 기반 `{hash}.json`에서 PDF-name 기반 `{pdf_basename}.{hash[:8]}.json`으로 통일
- 결정: cache + Zotero 둘 다 적용, hash 8자 suffix (BIRTHDAY 9700편에서 2×10⁻⁹), legacy fallback 없이 일괄 마이그레이션 (사용자: OCR 거의 끝났으니 한 번에)
- 헬퍼 함수 `ocr_json_filename(paper_file)` 신설 → 10개 hot spot 통일 (text_extract / biblio / scripts / 양쪽 UI). `biblio.load_ocr_pages` 시그니처는 hash 그대로 유지, 내부 `_find_cache_by_hash` glob 검색
- 마이그레이션 script `scripts/rename_ocr_json.py`: 3-layer (cache rename → DB update → Zotero PATCH). 1:N cache 케이스(207개)는 `shutil.copy`로 sibling별 복제
- 시행 착오: (1) pyzotero `update_item` payload shape — full fetched item dict 통째로 받음, (2) `data.title`도 같이 박아야 GUI 표시, (3) Zotero 7+ 정책은 title을 generic label("PDF" 등)로 두는 게 정공법 — 현재는 title=filename으로 박혀있고 향후 정규화는 TODO로 분리
- WSL/NTFS WAL 충돌로 사용자가 Windows native Python(Anaconda)에서 script 직접 실행
- 영향 카운트: 9,920 JSON PaperFile rename, 9,700 unique hash, 204 1:N. 전체 apply 30~60분
- TODO 추가: "OCR JSON sibling attachment title 정규화" (Zotero 7+ 컨벤션 맞추기)

**2026-06-05 (세션 41)** — [devlog 045](./devlog/20260605_045_Items_Backfill_Removal.md)
- 세션 40 끝의 timing 로그로 Phase 2 items가 변경 0건인데 25.91s 발견. items 내부 phase별 logging 추가해서 `backfill (29 papers checked, 0 new) took 25.91s`로 hotspot 확정 — PaperFile 없는 reference-only paper 29편에 매번 `zot.children()` API call
- Git archaeology: commit `857a6d8` (devlog 029, 2026-04-16)에 도입. 당시 "9,877편 중 1편의 historical case"를 잡기 위한 임시 안전망. 그게 매 sync마다 무기한 돌면서 누적 overhead
- 사용자 지적: cold/incremental 어느 시나리오에서도 정상 sync면 backfill 불필요 — 누락 발생은 main loop 버그라 거기서 fix해야
- backfill 로직을 별도 함수 `backfill_missing_paperfiles(zotero_client, ...)`로 추출 후 sync_zotero_items에서 호출 제거. 미래에 진짜 필요 시 script/REPL에서 명시적 호출 가능. dormant 이유 docstring에 박음 (도입 이력 + 측정 수치 + git ref)
- **세션 40+41 통합 결과**: 전체 sync 31s → **5s** (83% 절감). Phase 1 11.40s→1.99s, Phase 2 26s→~1s, Phase 3 (trash) 2s 유지

**2026-06-05 (세션 40)** — [devlog 044](./devlog/20260605_044_Collections_Incremental_Sync.md)
- Phase 1 collections sync가 547개 collection에서 매번 11s. logging 추가로 hotspot 잡음: `get_collections()` API call 7.21s + `sync_zotero_collections` 2회 호출 4.19s
- **Incremental 전환**: `get_collections(since=last_col_ver)` 활용. 이미 코드는 있었는데 worker가 since를 안 넘김. 별도 pref `zotero_collections_version` 신설 (items phase의 `zotero_library_version`과 race 없도록 분리). 변경 없으면 sync(fresh) 호출 자체 생략
- 결과 (A만): 11.40s → **4.00s** (변경 없는 일반 sync 기준). `get_collections` 7.21s → 0.77s
- **B도 같이 적용**: `load_cached_collections` + `sync(cached)` 통째 제거. 사용자 확인 — 예전 DB migration 시 들어간 잔재, Folder 테이블이 persistent라 cold-start UI 응답성 가치 0. 추가 2s 절감으로 phase 1 total ~2s 예상 (검증 보류)
- 남은 후보: `get_library_version()` 추가 round-trip ~1s, `sync_zotero_collections` 내부 bulk pre-fetch — 둘 다 micro-optimization으로 보류

**2026-06-05 (세션 39 후속)** — [devlog 043](./devlog/20260605_043_Trash_UI_Hide_And_Library_Filter.md)
- 042에서 `trashed_at` 컬럼만 박았더니 사용자 지적: "collection별 item 목록 보여줄 때 trashed_at 체크 안 하는 것 같은데?". 4개 데이터 소스 (`list_by_library` / `list_by_folder` / `list_by_source` / FTS5 `search`) 모두 필터 없었음
- **숨김 정책**: 모든 일반 목록에서 trashed paper 자동 제외 (Zotero GUI 표준 동작). Library 트리에 `('trash', 'Trash')` 항목 신설 — `trashed_at IS NOT NULL` 전용 뷰. `paper_service.list_by_library('trash')`도 추가
- 모든 카운트 함수 (`_count_all`, `_count_status`, `_count_recent`, `needs_review_paper_ids`) 도 trashed 제외 — 트리 카운트와 list가 구조적으로 일치 보장
- FTS5 검색은 post-hoc 필터 (FTS 인덱스 자체엔 trash 신호 없음). `seen_papers` dedupe 루프에서 `paper.trashed_at` 체크 후 skip + `skipped_trashed` 캐시로 중복 페치 방지
- 검증: 사용자 DB 사본에서 All Papers 9,888 → 9,887, Trash 항목 카운트 1 (Segment Anything), 같은 제목의 다른 paper(id=9891)가 검색 top 1로 올라옴. 모든 hot path에서 정확히 trash 1건 제외
- UI 변경 없음(Library 트리 자동 노출), 우클릭 "Restore" 액션은 TODO로 남김 (현재는 Zotero에서 복원 후 다음 sync로 자동 clear 경로만)

**2026-06-05 (세션 39)** — [devlog 042](./devlog/20260605_042_Zotero_Trash_Flag_Sync.md)
- Zotero 서버에서 trash로 보낸 item이 우리 DB에 영구 잔존하던 빈틈 메움. `Paper.trashed_at` + `PaperFile.trashed_at` (DateTimeField, null) 추가. NULL=정상, datetime=trash 들어간 시점
- `ZoteroClient.get_trash_keys()` 신설 — `zot.trash()` everything 페이지네이션 wrap, uppercase key set 반환. Zotero는 `/items/trash`에 `since` 지원 안 하므로 full snapshot
- `papermeister.ingestion.sync_trash_state(zotero_client)` 신설 — Paper/PaperFile에 양방향 sync (in trash & flag NULL → set, flag NOT NULL & not in trash → clear). 영구 삭제는 restore와 sync 입장에서 구분 불가 → silently clear로 두는 게 현재 한계 (PaperBiblio cascade 보호 위해 영구 삭제 핸들링은 별도 작업)
- `desktop/workers/zotero_sync.ZoteroSyncWorker._sync()` Phase 3로 추가, try/except로 best-effort (실패해도 메인 sync는 성공). 상태바에 `Trash sync: trashed N papers / M files, restored ...` 출력
- CLI sync에는 hook 안 함 (CLI sync는 collections만 다루는 다른 경로)
- 마이그레이션 검증: 9,888 papers / 19,983 paperfiles DB 사본에 적용 → 컬럼 추가 OK, 초기값 NULL, 기존 데이터 무손상
- UI 표시(숨김/회색/별도 필터)는 미정 — 데이터만 박아두고 사용자 결정 대기

**2026-06-05 (세션 38)** — [devlog 041](./devlog/20260605_041_Sync_Refresh_Attachment_Path.md)
- 캐시 점검: OCR 사실상 완료 (9,923 / 9,933 PDF processed, 99.9%). 잔존 10편 PDF 분석 — HTTP 404 (Zotero web storage에 file 없음) 7편 + Windows 파일명 문제 1편 (CDTGJND5, z-lib 책) + pending 2편
- **`sync_zotero_items`의 attachment filename 갱신 누락 fix**: 기존엔 `existing_pf` 발견 시 `continue`로 skip → 사용자가 Zotero에서 attachment를 rename해도 우리 `PaperFile.path`는 영구 옛 값. `_refresh_existing_attachment(existing_pf, att)` 헬퍼 신설, 3 hot path(메인 loop / orphan / backfill) 모두에서 `continue` 직전 호출
- **`failed + hash==''` 자동 리셋**: path가 바뀌었고 hash가 비어있었다면 (= 한 번도 OCR 시작 못함) status='pending'으로 리셋 + `failure_reason` clear. hash가 있는 failed (OCR 자체 실패)는 path 변경과 무관해서 자동 리셋 대상 아님
- 라이브 검증 통과 (CDTGJND5): Sync → path 갱신 + status `failed→pending` 자동 전환 → Process → OCR 성공
- HANDOFF.md "Zotero sync 양방향성 보강" 섹션 신설: PaperFolder remove / Trash 처리 / MD5 추적 / `content_type` 컬럼 / itemType 캐시 5개 TODO
- 조사 중 확인: `Folder.name`과 `Folder.parent` 변경은 이미 `sync_zotero_collections`에서 처리되고 있음 (line 127-129, 150-152)

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
