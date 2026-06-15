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

## 후속(저순위)

- 폴더 basename이 같으면 탭 라벨 중복 → 필요 시 부모 경로 suffix로 구분
- directory 소스 탭 우클릭에 "소스 제거/새로고침" 메뉴(현재 Process All/Folder만)
- 가져오기 진행 중 진행률 표시(현재는 상태바 "Importing …" 한 줄; 큰 폴더면 per-file
  progress_callback을 status_bar로 흘릴 수 있음)
