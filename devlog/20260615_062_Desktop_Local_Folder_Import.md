# 062 — desktop 앱에 로컬 폴더 PDF 가져오기

> 세션 47 (2026-06-15). Zotero가 아닌 **로컬 폴더의 PDF를 DB화**하는 흐름을 새 desktop
> 앱에 추가. 백엔드(ingestion/OCR/biblio)는 이미 directory 소스를 완전 지원하고 있었고,
> 빠진 것은 **데스크톱 UI 트리거** 하나뿐이었다.

## 사전 조사 결론 (이미 되어 있던 것)

- 데이터 모델이 소스 무관: `Source.source_type='directory'`, `Folder.path`, `Paper.folder`,
  `PaperFile.hash`(SHA256) 모두 directory용으로 작동
- `ingestion.import_source_directory(dir_path)` — 폴더 재귀 스캔 + 해시 dedup + Source/
  Folder/Paper/PaperFile(status=pending) 생성. **CLI(`cli.py import`)와 구 GUI가 쓰던 함수**.
  절대경로 기준 get-or-create라 폴더마다 Source 하나
- `text_extract.process_paper_file`이 로컬 PDF 처리: `is_zotero = bool(zotero_key)` 분기로
  **다운로드 없이** 로컬 경로 직접 읽고 메타데이터는 PyMuPDF로 추출. biblio(`claude`)도 동일
- `desktop` SourceNav는 이미 **소스마다 탭** 생성(`load_source_tree()`가 전 소스 반환,
  `for src in sources: addTab`). Zotero는 'My Library', directory는 폴더명 라벨. 즉
  **멀티탭(Zotero + 폴더1 + 폴더2…)은 추가 작업 없이 동작**

## 추가한 것 (UI 트리거)

1. **Rail 액션 'import'** (`desktop/components/sidebar.py`): ACTIONS 맨 위에 추가
   (import / sync / process / settings 순). 일회성 액션이라 `action_triggered('import')` 발사
2. **아이콘** `desktop/theme/icons/import.svg`: 기존 Lucide 스타일(24x24, `stroke=currentColor`,
   width 1.8) 맞춘 folder-plus. PyInstaller spec의 `datas=('desktop/theme/icons', ...)` glob에
   자동 포함 → 빌드 변경 불필요
3. **핸들러** `MainWindow._import_folder` (`desktop/windows/main_window.py`):
   - `QFileDialog.getExistingDirectory` → `BackgroundTask`(기존 `desktop/workers/background.py`)로
     `import_source_directory` 백그라운드 실행. **worker는 ORM 객체 대신 plain
     `(source_id, name, new_count)` 반환** (peewee 연결은 thread-local이라 객체 cross-thread 금지)
   - `_on_import_done`: SourceNav refresh(새 탭 등장) + 카운트 갱신 → 그 소스의 `pending` PDF를
     모아 **"N개 발견, 지금 OCR 처리?" 확인 다이얼로그**(구 GUI 동작 그대로) → Yes면 기존
     `ProcessWindow.start(ids)` 재사용. 이후 OCR 완료분은 기존 auto-biblio 큐로 합류
   - `_on_import_failed`: 상태바 + 경고 다이얼로그
   - `self._scan_task` 가드로 중복 스캔 방지

## 설계 메모

- **처리 범위**: 가져온 직후 *그 소스의* pending PDF만 처리 대상으로 모음(전역 pending이
  아니라). 같은 폴더 재가져오기 시 새 파일(dedup) + 이전에 안 끝난 pending까지 포함.
  루트 직속 PDF도 `_scan_dir`이 루트 Folder를 먼저 만들어 `Paper.folder`가 채워지므로
  `join(Folder)`에서 누락 없음
- **Zotero와 다른 점(자연 비활성)**: zotero_key 없음 → write-back/JSON 업로드/standalone
  promote 안 함. 한 방향(로컬→DB)
- 구 GUI(`papermeister/ui`)의 `ScanWorker`를 포팅하지 않고 범용 `BackgroundTask`로 대체

## 검증

- 변경 모듈 compile + import OK, `import.svg` valid XML
- headless(QT offscreen) Rail 빌드 → 액션 버튼 `[import, sync, process, settings]`,
  `rail_icon('import')` non-null 렌더 확인
- **실제 폴더 선택 → 스캔 → OCR end-to-end는 사용자 Windows 환경(RunPod) 검증 필요**

## 후속 작업 (같은 세션) — 진행창 + M2M 링크 정합성

첫 구현 후 실사용에서 두 문제가 드러나 보강:

### 1. 진행 상황이 status bar 한 줄뿐 → progress 창

`desktop/workers/scan.py::ScanWorker`(QThread) + `desktop/windows/scan_window.py::ScanWindow`
신설. 사용자 제안대로 **먼저 dir walk로 PDF 총개수를 세고**(`counted` 시그널) **determinate
X/N 진행바**로 진행. per-file 로그 + 최종 요약(new/linked/total). pre-count는 `_scan_dir`과
동일한 선택 규칙(dotfile skip, `*.pdf` case-insensitive, 권한오류 skip)으로 세어 총계 일치.
`BackgroundTask`(progress 없음) → 전용 `ScanWorker`로 교체.

### 2. "하나도 import 안 됨" + folder 탭에 안 보임 → **PaperFolder M2M 링크**

증상: 이미 Zotero에 있는 PDF들이 든 폴더를 import하니 **0건**. 원인 2겹:
- **content hash dedup이 전역**(`ingest_pdf`이 `PaperFile.hash`를 DB 전체에서 조회) → Zotero에
  이미 있는 동일 내용은 "기존"으로 보고 skip → new=0
- 게다가 desktop **`list_by_folder`는 `PaperFolder`(M2M)로만 조회**(`Paper.folder`는 legacy
  1:1, fallback 없음)인데 `ingest_pdf`은 `Paper.folder`만 세팅 → **새로 import한 directory
  논문조차 폴더 탭에 안 뜸**

해법(사용자 직관대로 — 같은 Paper가 Zotero 컬렉션 + 로컬 폴더에 동시 소속): `ingest_pdf`이
**양쪽 브랜치에서 `PaperFolder.get_or_create(paper, folder)` 링크 생성**.
- 신규 내용: Paper/PaperFile 생성 + 폴더 링크 (`is_new=True`)
- 기존 내용(hash 매칭): **skip 대신** 그 기존 Paper를 폴더에 링크(`is_new=False`).
  중복 Paper/PaperFile 안 만듦
- 백워드 호환: 반환값 `(paper_file, is_new)` 유지 → CLI/구 GUI 무영향(오히려 M2M 링크가
  생겨 desktop 조회와 정합)

검증(임시 DB+파일): Zotero 논문과 동일 내용 PDF를 로컬 폴더로 import →
new_files=0, 그 Paper의 folder 멤버십 2개(Zotero 컬렉션 + 로컬 폴더), Paper row 총 1개(중복 0).
→ 같은 논문이 양쪽 탭에 표시됨. import 요약/다이얼로그도 "linked from existing" 문구로 갱신.

주의(향후): Zotero collection-membership 양방향 sync(현 add-only)를 set-difference 제거로
바꾸면 **directory 소스 PaperFolder 링크는 건드리지 말 것**(Zotero 폴더로 스코프 한정).

## 후속(저순위)

- 폴더 basename이 같으면 탭 라벨 중복 → 필요 시 부모 경로 suffix로 구분
- directory 소스 탭 우클릭에 "소스 제거/새로고침" 메뉴(현재 Process All/Folder만)
- 대용량 폴더에서 per-file 시그널 폭주 시 진행 로그 throttle (현재 QTextEdit blockCount 3000 cap)
