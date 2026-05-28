# 20260528_037 — DetailPanel lazy 탭/페이지 렌더, Zotero key 표시, OCR submit 페이지 hint

## 컨텍스트

세 가지 사용자 관찰에서 시작:

1. 우측 Detail 패널 Metadata에 paper의 Zotero key가 안 보여서 외부 도구로 cross-reference할 때 불편.
2. 가운데 paper list에서 큰 PDF를 가진 항목을 클릭하면 패널이 뜨기까지 눈에 띄게 지연. 원인은 `show_paper()`가 클릭 즉시 세 탭(Metadata / PDF / Text)을 모두 빌드하면서 **PDF의 모든 페이지를 1.5배 QPixmap으로 동기 렌더**하기 때문.
3. OCR 서버에 동시에 12개 PDF가 in-flight 상태. 서버 mode-aware concurrency가 12라면 보통 1~2개만 떠 있어야 정상 — 무엇인가 큐 깊이 계산을 오인식하고 있음.

## 변경 사항

### 1. Metadata 카드에 Zotero Key 행

`desktop/services/paper_service.py`:

- `PaperDetail`에 `paper_zotero_key: str` 추가.
- `load_detail()`이 `paper.zotero_key or ''`로 채움.

`desktop/views/detail_panel.py::_build_metadata_card`:

- `Source` 행 다음에 `Zotero Key` 행 삽입, **존재할 때만** (디렉토리 소스는 `—`로 채우면 시각적 잡음만 추가됨).
- `Collection` 행이 항상 마지막에 오도록 `next_row` 카운터 도입.

### 2. Lazy 탭 빌드

`desktop/views/detail_panel.py::show_paper`:

기존엔 paper 클릭마다 세 탭을 모두 빌드. PDF 탭이 무거우니 클릭 → 패널 표시 사이에 지연이 들어감.

변경:

- Metadata 탭만 즉시 빌드 (cheap — 폼 그리드 + 옵션 biblio 비교 카드).
- PDF / Text 탭은 빈 `QWidget` wrapper만 만들어두고 `QTabWidget.currentChanged` 시그널로 **첫 활성화 때 한 번만** 실제 내용 빌드.
- `_pdf_built` / `_text_built` 플래그로 재빌드 방지. paper를 바꾸면 (`show_paper` 재호출) 플래그 리셋.
- `setCurrentIndex(prev_idx)`가 이전 탭으로 복원할 때 인덱스가 바뀌지 않으면 `currentChanged`가 안 뜨므로, `_on_tab_changed(self._tabs.currentIndex())`를 명시적으로 한 번 더 호출해서 default 활성 탭의 lazy build도 trigger되도록 함.

`_on_tab_changed`:

```python
def _on_tab_changed(self, idx: int):
    if self._current_detail is None:
        return
    if idx == 1 and not self._pdf_built and self._pdf_wrapper is not None:
        self._pdf_built = True
        self._pdf_wrapper.layout().addWidget(
            self._build_pdf_tab(self._current_detail)
        )
    elif idx == 2 and not self._text_built and self._text_wrapper is not None:
        self._text_built = True
        self._text_wrapper.layout().addWidget(
            self._build_ocr_tab(self._current_detail)
        )
```

PDF download flow (`_build_pdf_download_panel::_on_downloaded`)도 기존엔 `self._tabs.removeTab(idx); insertTab(idx, ...)`로 탭을 통째로 교체했는데, lazy 인덱스 가정이 깨지므로 **wrapper 내부에서 child만 swap**하도록 변경. paper 전환 중 download 완료 race는 `RuntimeError`로 silently 처리.

### 3. Lazy PDF 페이지 렌더

`desktop/views/detail_panel.py`에 새 클래스 `_LazyPdfView(QScrollArea)` 추가.

설계 요점:

- `fitz.Document`를 받아 `len(doc)`만큼 페이지 placeholder `QLabel`을 미리 생성. **크기는 `page.rect.width/height × 1.5`로 즉시 확정** — fitz에서 페이지 rect 조회는 페이지 디코딩 없이 file structure에서 바로 옴, instant.
- 따라서 스크롤바 총 높이는 첫 렌더부터 정확 (placeholder가 자리를 잡으니 사용자가 스크롤 거리 가늠 가능).
- placeholder는 `setStyleSheet('background: #1a1a1a;')`로 다크 배경 — 로딩 중임을 시각적으로 암시.
- `verticalScrollBar().valueChanged` + `resizeEvent`에서 `_render_visible()`을 호출. viewport `[vp_top, vp_bottom]`에 `_LOOKAHEAD_PX = 800px` 마진을 두고 겹치는 placeholder만 `get_pixmap(matrix=Matrix(1.5,1.5))` → `QPixmap` → `setPixmap`.
- 첫 렌더는 `QTimer.singleShot(0, self._render_visible)`로 next event loop iteration에 defer — 그 시점에야 layout pass가 끝나서 `lbl.y()`가 의미 있는 값을 반환함.
- 한 번 렌더된 페이지는 `self._rendered[i] = True`로 표시 후 재렌더 안 함. 메모리는 페이지를 보지 않은 만큼 절약, 보고 나면 그대로 유지 (위로 스크롤 시 re-decode 없음).

`_render_pdf()`는 이제 thin wrapper — fitz open만 시도하고 실패 시 empty panel, 성공 시 `_LazyPdfView(doc)` 반환.

### 4. OCR `wrapper_submit`에 로컬 페이지 hint

이 세션의 가장 큰 발견. `papermeister/ocr.py::wrapper_submit`:

기존:
```python
# First poll to get total_pages (server may need a moment to parse PDF)
try:
    poll = requests.get(f'{_WRAPPER_URL}/ocr/{job_id}', timeout=10).json()
    total_pages = poll.get('total_pages', 0)
except Exception:
    total_pages = 0
return job_id, total_pages
```

서버가 큰 PDF를 아직 파싱하지 못한 시점에 first-poll이 떨어지면 `total_pages = 0` 반환. `process_window.py::_submit_next`의 폴백 `'total_pages': tp or 1`로 인해 그 job은 큐 깊이 계산에서 **1페이지로만 잡힘**.

그러면 `_run_wrapper_pipeline`의 seed loop:
```python
while submit_idx < len(self.paper_file_ids) and _queued_pages() < min_queued_pages:
    _submit_next()
```

`min_queued_pages = 12` (server's recommended_concurrency)인데 각 제출이 1페이지로만 카운트되니 **12개가 연속 제출**됨. → 12 in-flight 현상의 정체.

수정:

```python
# Read page count locally before submission — server's first poll often
# returns 0 for large PDFs that haven't been parsed yet.
local_pages = 0
try:
    import fitz
    doc = fitz.open(pdf_path)
    try:
        local_pages = doc.page_count
    finally:
        doc.close()
except Exception as exc:
    logger.warning('Local page-count failed for %s: %s', ..., exc)

# ... POST with `total_pages` form hint if local_pages > 0 ...

# Server count wins when available (handles cached jobs); otherwise
# fall back to the local count so queue-depth accounting isn't undercounted.
if total_pages <= 0:
    total_pages = local_pages
```

두 가지를 동시에 함:

1. **클라이언트 측 fallback**: 서버가 0을 주면 로컬 카운트를 그대로 반환 → `_submit_next`의 `tp or 1`이 실효적으로 비활성. 첫 제출부터 큐 깊이 정확.
2. **서버 측 hint**: POST form에 `total_pages` 필드를 advisory로 첨부. 서버 코드는 별도 리포에 있어서 클라이언트만 hint를 보내두고, 서버는 추후 자체 파싱 결과로 검증/덮어쓰는 패턴으로 받아주면 됨. 받아주는 코드가 없어도 form의 추가 필드는 무시되니 backwards-compatible.

`fitz.open()`은 PDF 구조만 읽고 페이지 디코드 안 함 — 200페이지 PDF도 ms 단위. submit path에 이 비용을 추가하는 건 무시 가능.

## 영향 범위

- **DetailPanel 응답성**: paper 클릭 즉시 Metadata만 그리니 어떤 크기 PDF든 즉시 반응. PDF 탭 활성화 시점에도 viewport에 보이는 1~3 페이지만 디코딩 → 100페이지 PDF 첫 표시도 거의 즉시.
- **메모리**: 사용자가 PDF 탭을 안 열면 PDF 디코딩 비용 자체가 0. 열어도 viewport 외 영역은 placeholder로만 차지. 스크롤한 만큼만 누적.
- **OCR 파이프라인**: 다음 OCR run부터 적절한 concurrency 유지. 12 in-flight 현상 사라짐. 서버 throughput과 클라이언트 메모리/네트워크 부담 모두 안정화.
- 모두 새 desktop 앱 (`python -m desktop`)에 적용. 기존 `papermeister/ui/`는 lazy PDF 렌더 영향 없음 (별도 코드 경로).

## 미해결 / 다음

- 서버 측 `total_pages` form 필드 핸들링 — 별도 리포에서 작업 필요. 그쪽이 받아주면 첫 GET /ocr listing에서도 정확한 페이지 수가 노출되어 다른 클라이언트의 외부 대기 로직(`ocr_wait_for_others`)이 더 정밀해짐.
- Lazy PDF 렌더가 GUI 스레드에서 `get_pixmap()`을 돌림. 큰 페이지(포스터/풀폭 그래픽) 한 장에 수백 ms씩 걸리는 케이스는 여전히 스크롤이 살짝 끊김. `QThread`로 빼는 풀 버전은 다음 라운드 — 일단 visible-only 렌더만으로도 체감 개선이 큼.
- placeholder가 `#1a1a1a` 하드코딩 — design tokens(`COLORS_DARK`)로 옮기면 라이트 테마 도입 시 자동 대응. 토큰 추가는 큰 변경이라 일단 후속.
