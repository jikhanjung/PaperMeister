# 049 — 첨부 확장자 게이트 + `skipped` status

> 세션 43 (2026-06-08), [048](./20260608_048_Failed_PDF_Local_Storage_Recovery.md) 후속.

## 동기

048에서 `failed` PDF를 조사하다, **OCR 대상이 아닌 첨부가 `failed`로 쌓여 노이즈**가 됨을
발견. Zotero 첨부에는 PDF 외에도 보충자료(`.txt`/`.xls`/`.zip`/`.pps`/`.doc`), 책(`.djvu`),
저널 `.doc`, `.htm`/`.mhtml` 등이 섞여 있는데, 기존 sync는 **JSON만 걸러내고 나머지는 전부
`pending`** 으로 만들어 OCR 큐에 넣고 → `ocr_pdf`가 못 읽어 `failed`로 떨어뜨렸다.

사용자 요구: "attachment는 **확장자를 보고 OCR 돌릴지 한 번 판단**을 거쳐야 한다."

## 결정

- **새 status `skipped`** (failed/processed 재사용 안 함) — "OCR 안 했지만 실패도 아님"을 명확히.
- **OCR 대상 = PDF만** (현재 `ocr_pdf`가 PDF 전용. 이미지 등은 별도 코드 필요).
- 기존 비-PDF failed 레코드도 일괄 보정.

## 구현

### 단일 소스 `papermeister/file_utils.py`

- `is_pdf(fn, ct)` / `is_derived(fn, ct)` — contentType 우선, 확장자 fallback
- `attachment_status(fn, ct)` → derived JSON=`processed` / PDF=`pending` / 그 외=`skipped`
- `has_non_pdf_extension(fn)` — **이름에 확실한 비-PDF 확장자가 있을 때만 True**.
  확장자 없는 bare Zotero key는 False (다운스트림 가드용).

### 게이트 = ingestion (단일 chokepoint)

`ingestion.py`의 4개 PaperFile 생성 지점을 `status=attachment_status(fname, ct)`로 통일
(메인 sync / orphan / backfill / collection fetch). contentType이 있어 신뢰성 높음.
`_refresh_existing_attachment`도 비-PDF면 `skipped`로 정리.

**효과**: 비-PDF가 `skipped`가 되면 `status=='pending'`/`'failed'` 쿼리가 자연히 제외 →
어떤 OCR 선택 경로(parallel/wrapper, old/new UI)에도 안 들어감. 별도 필터 추가 불필요.

### 방어 가드 (다운스트림)

선택 경로가 혹시 비-PDF를 넘겨도 막도록 — 단 **`path`만 있고 contentType이 없으므로
`has_non_pdf_extension`을 사용**(`is_pdf` 아님). 핵심 엣지: 다운로드 전 PDF는 `path`가
확장자 없는 bare key("WIZC6QDZ")라 `is_pdf(path)`로 보면 **실제 PDF를 skipped로 오분류**.
`has_non_pdf_extension`은 bare key를 통과시켜 OCR 시도하게 함.

- `text_extract.process_paper_file` 진입 가드 → 확실한 비-PDF면 `skipped` + early return (no raise)
- `process_window` wrapper `_submit_next` → 서버 제출 전 차단
- `_process_one` → 하드코딩 `'processed'` 대신 실제 `pf.status` emit (skipped 오표시 방지)

### UI (desktop)

- `_primary_file` → **PDF 우선** 선택. 기존 "첫 non-json 반환"은 skipped 보충파일(.txt 등)을
  실제 PDF보다 먼저 잡는 잠재 버그였음 → `.pdf` 우선 → non-json → 첫 파일 순.
- `paper_list._STATUS_STYLES`에 `skipped`→`skip`(muted) pill, `status_badge`에 `Skipped`.
- skipped 행 우클릭: 어느 status 분기에도 안 걸려 메뉴 미표시(오해 소지 액션 없음).

### 보정 `scripts/reclassify_attachments.py`

failed/pending 중 `has_non_pdf_extension(path)`인 것 → `skipped` (+failure_reason clear).
dry-run 기본. bare-key PDF는 제외되어 안전.

## 결과

`--execute`: **35편 reclassified → skipped**, 전부 `failed` 출신 (pending 0 = bare-key PDF
오포함 없음 검증). 확장자 분포: `.djvu` 15(책) / `.doc` 8 / `.txt` 4 / `.zip` 2 /
`.pps`/`.xls`/`.blend`/`.htm`/`.ppt`/`.mhtml` 각 1.

## 남은 것 / 메모

- **status 상수 모듈 없음** — 여전히 문자열 리터럴(`pending`/`processed`/`failed`/`skipped`).
  enum화는 별도 정리 과제.
- old UI(`papermeister/ui/`, 동결)는 `skipped` pill을 모름 — 사용자는 desktop 사용이라 보류.
- `_process_one` 반환이 skipped도 True(=processed 카운트)라 run() 요약 카운트만 미세 부정확.
  방어 경로 한정이라 무시.
- linked_url 6편(파일 아닌 URL 링크)은 contentType/확장자 없어 여전히 `failed` 잔존 가능 —
  bare key라 has_non_pdf_extension에 안 걸림. 필요 시 linkMode 기반 별도 분류 검토.
