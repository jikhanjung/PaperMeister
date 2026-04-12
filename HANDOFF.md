# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: P07 Phase 2 완전 종료 / Phase 3 완료 + 기본 사용 가능 / Phase 4 진행 중 / Phase D 대기**

### 안정적으로 돌아가는 것
- 기존 GUI (`papermeister/ui/` — **동결**, 신규 개발 없음). Process/Preferences 다이얼로그는 새 desktop 앱에서 재사용 중
- CLI (`cli.py`) — import/process/search/list/show/config/zotero
- RunPod OCR 파이프라인 (serverless + 병렬)
- Zotero 양방향 동기화: pull(기존) + **push/write-back(`papermeister/zotero_writeback.py`)**
- Haiku/Sonnet 서지 추출 파이프라인 + PaperBiblio 저장
- P08 반영 러너 (`scripts/reflect_biblio.py`): single / batch / `--force` 세 경로 모두 실DB에서 검증됨
- **새 desktop 앱** (`python -m desktop`, Windows + Anaconda):
  - 좌측 Rail (Library/Search 모드 + **Sync**/Process/Settings 액션)
  - **SourceNav 2-section**: 상단 Collections tree + 하단 STATUS 패널 (접기/펴기, 항상 하단 고정)
  - 중앙 PaperList (Status/Authors/Year/Title 컬럼, **인용 스타일 저자**: `Smith et al.` / `정직한 외`) — **Ctrl+click → SourceNav에서 컬렉션 reveal**
  - 우측 DetailPanel — **탭 3개**: Metadata / **Biblio (대조 비교 UI — 라디오 선택 + 편집 + Apply)** / **OCR (markdown 렌더링, sanitized)**
  - **상단 검색창 동작** (Enter로 FTS5 검색, Clear로 이전 뷰 복원, Nav 클릭으로 검색 취소)
  - **Zotero incremental sync** (시작 시 자동 + Sync 버튼 + 우클릭 Full Sync, progress 표시 + 아이콘 pulse 애니메이션)
  - **PaperFolder** M2M junction table — Zotero multi-collection membership 지원

### 진행 중인 것
- **Phase 4 (hookup)**:
  - **Apply Biblio 대조 비교 UI 완성** (세션 14): 필드별 라디오 선택 + 편집 가능 + apply_merged() 연결. NameError 버그 수정됨
  - **Zotero 저자 이름 형식 수정** (세션 14): `"Last First"` → `"Last, First"` 쉼표 구분. DB 마이그레이션 완료 (20k+건). biblio-applied 저자 복원 완료
  - **P08 evaluate `already_complete`** (세션 14): 모든 필드 동일한 curated paper는 `skip` 처리 → needs_review에서 제외
  - Process 액션: Rail → ProcessWindow 연결 완료. 실제 pending 논문 OCR 트리거 검증 미완
  - Settings 액션: Rail → PreferencesDialog 연결 완료. **저장 후 Zotero 재동기화 연결됨 (세션 13)**
  - batch Reflect 트리거 UI / background worker / StatusBadge delegate — 미완
  - **PaperFolder full sync 미완**: backfill은 Paper.folder 1:1만. 우클릭 "Full Sync"로 multi-collection 채울 수 있으나 실행 미완

### 대기 중
- **Phase D (대량 운영)**: OCR 완료 ~2,000편에 Haiku biblio 추출 → `reflect_biblio.py`로 일괄 반영. 현재 writeback 모듈은 end-to-end 1편만 검증된 상태라 Phase D가 진짜 batch 시험대가 됨
- **1960s standalone OCR**: 226편 RunPod 처리 중 (세션 6부터 진행, 현재 상태 미확인)

---

## 다음 할 일

### 즉시 착수 가능 (Phase 4 hookup)
- [ ] **Apply Biblio Zotero write-back 실증** — 로컬 apply_merged는 동작 확인됨. Zotero-sourced paper에서 Apply 후 Zotero 쪽까지 반영되는지 확인 필요
- [ ] **Process 액션 end-to-end 검증** — pending 논문이 있는 상태에서 Rail의 Process 버튼 → 확인 다이얼로그 → `ProcessWindow`가 실제 OCR 돌리는지 + status bar 카운트가 갱신되는지
- [ ] **Settings 액션 실증** — Rail의 Settings 버튼 → PreferencesDialog → 값 저장 후 Zotero 재동기화 실증 (코드 연결됨, 미검증)
- [ ] desktop: source/folder 단위 batch Reflect 트리거 + 결과 다이얼로그
- [ ] desktop: background worker (biblio 추출 / OCR 트리거) — QThread 기반, 기존 `papermeister/ui/` 패턴 참고
- [ ] desktop: PaperList 상태 셀에 StatusBadge delegate (현재는 축약 pill — done/wait/err/rev. 필요 시 풀 라벨로 복원 또는 아이콘화 검토)
- [ ] **BM25 tie-break 개선** (Phase 5 경계): 현재 `passage_fts`는 passage 단위라 title 가중치가 document-level boost로 작동 안 함. 예: `trilobite`로 검색하면 title에 trilobite가 없는데 본문에 많이 나온 논문이 top에 올라옴. 해결안: 별도 `paper_fts` (title/authors)와 합산 or Python post-processing boost. 지금은 alerting 수준

### 큰 덩어리 (Phase D 대량 운영)
- [ ] OCR 완료된 ~2,000편에 Haiku biblio 추출 (`scripts/extract_biblio.py`)
- [ ] 추출 직후 **반드시 non-dry `reflect_biblio.py` 한 번 돌리기** → biblio status stamp (아니면 Library "Needs Review" 폴더가 비어 보임)
- [ ] `reflect_biblio.py` 대량 실행 — Zotero API rate limit, 412 version conflict 자동 재시도, 진행률 표시 필요 (현재는 pyzotero backoff에만 의존)
- [ ] 1960s 컬렉션 standalone PDF 226편 OCR 완료 확인 → Haiku biblio → promote → 결과 검토

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
