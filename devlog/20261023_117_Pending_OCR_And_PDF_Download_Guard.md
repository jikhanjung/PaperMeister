# 117 — 대기 PDF 27개 OCR~도판, PDF 다운로드 검사·재시도 (2026-10-23)

코드 변경은 셋(`f931c35` 다운로드 검사, `5a512f5` references 출력 인코딩, `a884573` "et al." 저자)이고 나머지는 라이브 데이터 작업이다.

## 1. OCR 대기 27개를 받아 OCR

HANDOFF의 "OCR 대기 27개"는 10-22 동기화분 12편(paper 9914~9925)과 6~10월에 들어와 Process를 안 돌린 15편(9899~9913)이었다.
15편은 **실패가 아니었다** — 상태는 모두 `pending`, `failure_reason`은 비어 있고, 로그·`pdf_cache`에 키 흔적이 없었다. 동기화가 행을 만들고 아무도 Process를 안 돌린 것.

Windows Anaconda env로 바깥 드라이버를 돌렸다: PaperFile 20022~20048을 `_resolve_filepath`로 `pdf_cache/<key>/`에 받고, 앞 1024바이트에 `%PDF`가 없으면 지우고
다시 받은 뒤(아래 2의 수정 전이라 바깥에서), 통과한 것만 `cli._run_process`에 넘겼다. 결과는 27/27 `processed`, 본문 498쪽·passage 527, OCR JSON 27.

- 차단 페이지로 온 것은 없었다. 1개(20033 Nam & Jang 2026)는 받다가 `RemoteDisconnected`로 끊겼고 다시 받으니 됐다 — 이것도 2에서 재시도 대상이 됐다
- 부모 없던 PDF 3개(`foraminifera_automated_identification_2019_2026`, `동네 치과의 AX전환기 — 인쇄용`, `1995_Seismic Velocity…`)는
  `auto_promote_standalone`(기본 켜짐)이 파일명을 제목으로 Zotero 부모 항목을 만들었다(`8QRANFQK`·`IWEFWZBQ`·`PFHNXWDC`) — 앱 Process와 같은 동작
- 이 단계에서는 OCR까지만 했다. 나머지 단계는 4에 있다. 도판 러너는 끝난 컬렉션에 새로 들어온 PDF를 다시 보지 않으므로(HANDOFF) 손으로 돌렸다

## 2. PDF 다운로드를 캐시 전에 검사하고, 아니면 재시도 (`f931c35`)

KOPRI 웹 필터가 Zotero 파일 요청에 ~413바이트 HTML 차단 페이지를 가끔 돌려주고, 다시 받으면 통과한다(116). JSON 사이블링은 `json.loads`가 걸러 왔지만
PDF를 받는 세 곳 — `text_extract._resolve_filepath`(OCR·도판 레인·Process 창), PDF 탭의 `detail_panel._download_zotero_pdf`, `ZoteroClient.download_attachment`(vision 스크립트) — 은
받은 바이트를 그대로 썼다. 그 페이지가 `pdf_cache`에 `.pdf`로 남으면 해시가 그걸로 찍히고, 캐시가 있으면 다시 받지 않으므로 PDF 탭·도판까지 계속 그 파일을 쓴다.

- `file_utils.looks_like_pdf(bytes)` — 앞 1024바이트에 `%PDF-`. 리더가 헤더를 찾는 범위라 앞에 잡음이 붙은 PDF도 통과한다
- `ZoteroClient.download_pdf_content(key)` — PDF가 아니면 `NotAPdfError`(크기와 "HTML — block page?"/"empty — missing from web storage")를 내고,
  그걸 끊긴 연결·5xx와 **같은 규칙으로 재시도**한다. 재시도는 `zotero_writeback._zotero_retry`(3회, 2 s·5 s)를 그대로 쓰고 `retry_on` 인자 하나를 더했다.
  4xx(404 = 업로드 안 된 파일)는 바로 실패 — `_resolve_filepath`의 404 메시지는 그대로다. 빈 응답 전용 분기는 `NotAPdfError`가 맡아 지웠다
- `tests/test_pdf_download_guard.py` 13개. `_resolve_filepath` 두 개는 옛 코드에서 실패하는 것을 확인했다(차단 페이지가 캐시에 남는다)
- 쓰기 중 중단으로 잘린 파일(헤더는 정상)은 이 검사로 못 잡는다. 캐시 쓰기를 임시 파일 + `os.replace`로 바꾸는 것은 범위 밖으로 남겼다

## 3. 기존 캐시 점검 — PDF 아닌 것 1개, 그건 Zotero 원본이 HTML

`pdf_cache` 10,009개의 앞 1024바이트를 읽었다. `%PDF`가 없는 것은 **1개**:
`732NKRFK/Manuel - 2009 - Early evolution of symmetry and polarity in metazoan body plans.pdf`(58,481 B, 5/21 수신).

- 413 B 차단 페이지가 아니라 **ScienceDirect 기사 페이지 HTML**("Screen reader users, click here to load entire article…")이다. md5가 Zotero 첨부의 `md5`(`cda67a6f…`)와 같다 —
  **Zotero에 저장된 첨부 자체가 HTML**이고 이름·contentType만 PDF다. 처음 Zotero에 넣을 때 PDF 대신 페이지가 저장된 것
- `PaperFile` 8388(paper 6355)은 그 HTML의 sha256(`4df6cd0e…`)을 해시로 가진 채 `processed`, passage 8개는 웹페이지 내용, OCR JSON 사이블링 `472HNXXQ`도 같은 내용으로 Zotero에 있다. 도판·참조 0
- 그 자리에서 같은 파일을 연달아 세 번 받으니 1회차는 58 KB HTML, **2·3회차는 413 B KOPRI 차단 페이지**였다 — 필터는 반복 요청에서도 막는다. 진짜 PDF라면 이번 수정의 3회 재시도로 충분했는지는 표본이 없다
- 데이터는 건드리지 않았다(진짜 PDF를 구하는 것이 먼저). 이제 이 항목을 새로 받으면 `NotAPdfError`(HTML)로 실패한다 — 캐시가 있는 동안은 캐시를 쓴다

## 4. OCR 다음 단계 — Info, References, 도판

ocrserver를 OCR 모델에서 LLM(Qwen)으로 바꾼 뒤 같은 27편(paper 9899~9925)에 앱과 같은 경로로 돌렸다. Windows Anaconda env에서 바깥 드라이버를 썼고,
LLM 호출은 스레드 4개, DB 쓰기는 메인 스레드에서 했다.

- **Info**(`biblio_backend=qwen`) — 27/27 추출, 실패 0. 이어서 `reflect_biblio.py --execute`를 돌렸다:
  - 자동 반영 3: 9925 Christensen & Mooney 1995는 Zotero에 썼다. 9901은 Zotero가 이미 완전했다(`zotero_already_complete`). 9923은 아래 4.2에서 되돌렸다
  - 검토 대기 15(`override_conflict` 12 — 대개 이름 대소문자나 학술지 약어 차이 / `missing_authors` 2 / `visual_review_flag` 1)와 이미 같음 9
  - 검토 대기 중 사람이 봐야 할 것: 9909는 추출한 제목이 Zotero와 다르다(hemeroscopid ↔ heterostichid). 9912는 PDF 오타(McNmara)를 그대로 읽었다.
    9899는 책 항목에 챕터(Huss)를 읽었다
- **References**(qwen) — 27/27 checked, references 1,881, 보유 논문 연결 195, CitedWork 1,673. 9924는 "no references section"이다.
  첫 실행은 13편을 저장한 뒤 죽었다(4.1). 남은 14편은 고친 스크립트로 다시 돌렸고, 죽은 실행이 건너뛴 resolve 패스는 저장된 13편에 따로 돌렸다
- **도판**(`figure_pipeline.process_file`, 앱 Process Figures와 같은 경로) — 도판 218, 캡션 190, 분할 75(패널 388). 도판이 없는 문서는 3개(9901, 9915, 9923)다.
  캡션이 연결되지 않은 28개 중 20개는 9924(논문이 아닌 문서)에 있다. 20039(9916)는 같은 PDF가 paper 212에 이미 있어서 캐시 JSON의 결과를 가져왔다

### 4.1 `extract_references.py`가 cp949로 출력하다 죽었다 (`5a512f5`)

출력을 로그 파일로 보내면 한국어 Windows의 Python은 cp949로 쓴다. cp949에는 en dash가 없다. 그래서 `[13/27] 9908 Pliocene–Pleistocene… ok`를 출력하다가
`UnicodeEncodeError`가 났다. 그 논문은 출력 전에 이미 저장됐지만 실행 자체가 끝났다. 그 시점에 돌고 있던 14편은 `with ThreadPoolExecutor`를 빠져나가는 동안
LLM 호출은 끝까지 했지만 결과가 버려졌고(약 40분), resolve 패스도 돌지 않았다. stderr의 로그 줄은 Python 기본값인 `backslashreplace`라 `–`으로 찍히며 살아남았다.
`assemble_figures.py`와 같은 `_print_utf8()`을 넣었다. 테스트는 `PYTHONIOENCODING=cp949` 서브프로세스로 돌리며, 옛 코드에서는 실패한다.
제목을 출력하면서 UTF-8로 바꾸지 않는 스크립트가 28개 더 있다. 지금은 그대로 두었다.

### 4.2 "et al." 저자가 Zotero에 자동 반영됐다 (`a884573`)

9923 `foraminifera_automated_identification_2019_2026`은 저자 없는 3쪽짜리 한국어 문헌 검토 노트다. 첫 줄 "Hsiang et al. (2019) Endless Forums 이후의 발전"을
Qwen이 저자와 연도로 읽었다(confidence medium). 제목이 파일명인 임시 항목은 confidence 관문이 느슨해서(medium 통과) 그대로 자동 반영됐고, Zotero `8QRANFQK`는
journalArticle, 저자 "Hsiang et / al.", 2019가 됐다.

- `biblio_reflect.evaluate`: 저자 하나라도 `\bet\.?\s*al\b`에 맞으면 `needs_review/et_al_author`로 보낸다. 인용을 저자로 읽었거나 목록이 잘린 경우인데,
  어느 쪽이든 사람이 보기 전에 쓰면 안 된다. 테스트 6개 중 옛 코드에서 실패하는 것이 5개다
- 데이터: `8QRANFQK`를 자동 승격 직후 모양(document, 저자·날짜 없음)으로 되돌렸고, 추출한 제목만 남겼다. 로컬 Paper·Author는 Zotero에서 다시 읽었다.
  PaperBiblio는 `needs_review/et_al_author`로 옮겼다. OCR JSON의 `biblio_state`/`biblio_source`/`biblio_applied_at`을 지우고 사이블링에 다시 올렸다
  — 그대로 두면 다른 머신이 "이미 적용됨"으로 건너뛴다

### 4.3 이번에 보인 것

- 27편 중 5편은 이미 있던 논문의 중복 Zotero 항목이다. 9903→4627과 9916→212는 PDF가 같고, 9904→2945·9917→1346·9922→7344는 DOI가 같다. 병합 여부는 사용자가 정한다(HANDOFF)
- 논문이 아닌 것 3개: 9923·9915(문헌 검토 노트)와 9924("동네 치과의 AX전환기 — 인쇄용", 도판 21개 중 캡션 1개)
