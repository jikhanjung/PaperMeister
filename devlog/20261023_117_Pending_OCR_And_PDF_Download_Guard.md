# 117 — 대기 PDF 27개 OCR, PDF 다운로드 검사·재시도 (2026-10-23)

코드 변경은 하나(`f931c35`)이고 나머지는 라이브 데이터 작업이다.

## 1. OCR 대기 27개를 받아 OCR

HANDOFF의 "OCR 대기 27개"는 10-22 동기화분 12편(paper 9914~9925)과 6~10월에 들어와 Process를 안 돌린 15편(9899~9913)이었다.
15편은 **실패가 아니었다** — 상태는 모두 `pending`, `failure_reason`은 비어 있고, 로그·`pdf_cache`에 키 흔적이 없었다. 동기화가 행을 만들고 아무도 Process를 안 돌린 것.

Windows Anaconda env로 바깥 드라이버를 돌렸다: PaperFile 20022~20048을 `_resolve_filepath`로 `pdf_cache/<key>/`에 받고, 앞 1024바이트에 `%PDF`가 없으면 지우고
다시 받은 뒤(아래 2의 수정 전이라 바깥에서), 통과한 것만 `cli._run_process`에 넘겼다. 결과는 27/27 `processed`, 본문 498쪽·passage 527, OCR JSON 27.

- 차단 페이지로 온 것은 없었다. 1개(20033 Nam & Jang 2026)는 받다가 `RemoteDisconnected`로 끊겼고 다시 받으니 됐다 — 이것도 2에서 재시도 대상이 됐다
- 부모 없던 PDF 3개(`foraminifera_automated_identification_2019_2026`, `동네 치과의 AX전환기 — 인쇄용`, `1995_Seismic Velocity…`)는
  `auto_promote_standalone`(기본 켜짐)이 파일명을 제목으로 Zotero 부모 항목을 만들었다(`8QRANFQK`·`IWEFWZBQ`·`PFHNXWDC`) — 앱 Process와 같은 동작
- 이 27편은 **OCR까지만**이다. Info·References·도판은 아직. 도판 러너는 끝난 컬렉션에 새로 들어온 PDF를 다시 보지 않는다(HANDOFF)

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
