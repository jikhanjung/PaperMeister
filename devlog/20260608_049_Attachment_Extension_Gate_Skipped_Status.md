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
## 후속: linked_url 첨부 보정 (같은 세션)

확장자 게이트 적용 후 `failed`가 80편 남았는데, 조사하니 **75편이 `linked_url`**(URL 북마크,
파일 없음) + 5편이 `imported_file` PDF(진짜 실패)였다. 사용자가 "failed인데 OCR된 것"으로
인지한 것의 정체:

- **표시 버그**: linked_url 첨부가 OCR된 PDF가 있는 paper에 붙어 있는데, 기존 `_primary_file`이
  "첫 non-json"으로 이 링크를 paper 대표로 골라 `err` pill을 띄움 → 이번 `_primary_file` PDF
  우선 수정으로 자연 해소(이제 processed PDF가 대표).
- **status 보정**: linked_url은 bare key(확장자 없음)라 `has_non_pdf_extension`에 안 걸림 →
  `reclassify_attachments.py`로 못 잡음. **zotero.sqlite의 linkMode**(0~3)가 authoritative라
  `scripts/reclassify_linked_attachments.py` 신설 — linked_file(2)+linked_url(3) failed → skipped.
  imported_file 실패는 진짜라 유지.

**forward는 이미 OK**: linked_url은 filename/contentType가 없어 ingestion에서
`attachment_status('', '')` → `skipped`로 떨어짐(게이트가 이미 처리). 기존 75편만 backfill 대상.

**결과**: 75편 → skipped. 최종 분포 **processed 19,887 / skipped 110(확장자 35 + linked 75) /
failed 5**(Segment Anything 등 서버·로컬 둘 다 파일 없는 imported_file PDF). failed 80 → 5.
