# 20260526_036 — OCR 로그 파일 영속화, Zotero 다운로드 에러 wrap, DB 통계 스크립트

## 컨텍스트

세션 36 종료 시점에 미커밋 상태로 남아있던 진단/관측성 관련 변경들 + 이번 세션에 추가된 OCR 로그 파일화를 함께 정리. 모두 "지금 무슨 일이 벌어지고 있는지 보이게 한다"는 같은 테마.

배경:
- OCR 작업 메시지가 `ProcessWindow` 내 `QTextEdit`에만 표시되고 stdout/파일 어디에도 영속화되지 않음 → 세션 종료 후엔 무엇이 처리됐는지 추적 불가.
- 세션 18에서 Zotero web storage에 attachment가 없는 케이스(과거 머신에서 업로드 안 했거나 사용자가 GUI에서 분리)에서 `client._zot.file()`이 빈 bytes를 조용히 반환 → 이후 cache write까지 성공해서 0바이트 PDF를 OCR에 보내고 의미 없는 에러로 실패.
- DB 상태를 한눈에 보기 위한 진단 스크립트가 없어서 매번 ad-hoc SQL을 짰음.

## 변경 사항

### 1. `ProcessWindow`에 일별 OCR 로그 파일 (이번 세션)

`papermeister/ui/process_window.py`:

- `_get_log_path()` — `~/.papermeister/logs/ocr_YYYYMMDD.log` 경로 반환, `logs/` 디렉토리 자동 생성.
- `_write_log_file(msg)` — append, `[YYYY-MM-DD HH:MM:SS] msg` 한 줄 포맷. `try/except Exception: pass`로 파일 IO 실패가 UI를 막지 못하게.
- `_log_message()` 끝에서 `_write_log_file()` 호출 → 모든 진행 메시지가 자동으로 파일에도 기록.
- `start()` 직후 회색으로 `Log file: <path>` 한 줄 UI 표시.

**왜 `_log_message()` 한 곳만 손대면 충분한가:**
- `ProcessWorker.progress` 시그널 → `_on_progress()` → `_log_message()` (모든 worker progress)
- `_on_file_done()` → `_log_message()` (Done/Failed per file)
- `_on_finished()` → `_log_message()` (Complete/Cancelled 배너)
- 그래서 funnel 한 군데서 잡으면 OCR 파이프라인의 모든 메시지가 자동으로 파일로 흘러감.

**왜 새 desktop 앱에도 자동 적용되는가:**
`desktop/windows/main_window.py`가 동결된 `papermeister.ui.process_window.ProcessWindow`를 재사용 (lazy-init). 한 번 손대면 두 앱 모두 커버됨.

**날짜별 rotation:**
파일명에 `YYYYMMDD`만 박아서 자정 넘어가면 새 파일로 분리. 같은 날 여러 run은 같은 파일에 누적. 실패 swallow 정책상 디렉토리/디스크 문제로 로깅이 망가져도 OCR은 계속 진행.

### 2. Zotero 파일 다운로드 에러 wrap

`papermeister/text_extract.py::_resolve_filepath` (Zotero-sourced PaperFile 경로):

기존:
```python
content = client._zot.file(paper_file.zotero_key)
os.makedirs(cache_dir, exist_ok=True)
with open(cached_path, 'wb') as f:
    f.write(content)
```

→ 변경:
```python
try:
    content = client._zot.file(paper_file.zotero_key)
except Exception as e:
    raise RuntimeError(
        f'Zotero file download failed for key={paper_file.zotero_key} '
        f'path={paper_file.path!r}: {e.__class__.__name__}: {e}'
    ) from e
if not content:
    raise RuntimeError(
        f'Zotero returned empty content for key={paper_file.zotero_key} '
        f'path={paper_file.path!r} — attachment likely missing from web storage'
    )
```

두 가지 케이스 분리:
- **예외 발생** (네트워크/403/404 등) → 키와 경로를 메시지에 박아서 어느 attachment인지 즉시 식별 가능.
- **빈 응답** (`b''`) → pyzotero가 attachment storage entry는 있지만 실제 파일 데이터가 없을 때 발생. "attachment likely missing from web storage" 힌트로 사용자가 Zotero에서 file presence 직접 확인 유도.

이전엔 0바이트 파일이 cache에 박혀서 같은 hash의 다음 retry 때도 corrupt 데이터가 그대로 재사용되던 위험이 있었으나, 이제 cache write 전에 raise → 잘못된 캐시 오염 차단.

### 3. `scripts/db_stats.py` 신규

전체 DB 상태를 한 번에 찍어주는 read-only 스냅샷 스크립트. 섹션:

- **Sources / Folders** — Source 수, Folder 총수, zotero_key 보유 Folder 수
- **Papers** — total / zotero-sourced / local, stub 비율
- **PaperFile status** — pending/processed/failed 카운트 (PDF vs JSON sibling 분리)
- **Standalone PDFs** — `Paper.zotero_key == PaperFile.zotero_key` 잔존분 (auto-promote 미진행)
- **Multi-PDF parents** — 한 paper에 PDF 2개 이상 매달린 케이스 (per-PDF JSON sibling 추적 fix 검증용)
- **PaperBiblio pipeline** — extracted → needs_review / auto_committed / applied 단계별
- **Passage / FTS row counts**

사용:
```bash
python scripts/db_stats.py
```

진단/회귀 체크용 — Phase D 대량 운영 시작 전 baseline 찍어두는 용도. 200 LOC, side-effect 없음.

## 영향 범위

- **OCR 로그**: 다음 OCR run부터 `~/.papermeister/logs/ocr_YYYYMMDD.log`에 자동 누적. 코드 경로 외 동작 변경 없음.
- **Zotero 에러 wrap**: 정상 케이스는 동작 동일. 실패 케이스에서 더 명확한 메시지 → ProcessWindow 로그 + 이제 파일에도 그대로 기록되니 사후 디버깅 가능.
- **db_stats.py**: 읽기 전용, side-effect 없음.

## 다음

- 세션 36 잔여 작업(48편 extracted 재시도, 1960s standalone 226편 Process Folder)에 들어가면 이번 로그 파일이 cross-session 검증 근거로 작동.
- 로그 파일이 너무 커질 경우(수만 페이지 batch 운영) compression/rotation 정책 필요할 수도 — 일단 일별 분리로 충분히 작을 것으로 가정.
