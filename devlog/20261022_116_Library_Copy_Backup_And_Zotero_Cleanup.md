# 116 — PDFium 잠금, 라이브러리 사본·전체 백업, 동기화가 덮은 캐시, Zotero 정리 (2026-10-22)

하루 동안 한 일. 코드 변경은 둘(`44a390e`, `efdf685`)이고 나머지는 데이터·Zotero 작업이다. Zotero를 바꾼 것은 모두 사용자가 요청·승인한 것이고,
지운 것은 전부 **휴지통**(영구 삭제 아님)이다. 일회성 스크립트는 저장소에 넣지 않았다.

## 1. PDFium은 문서가 달라도 스레드 안전하지 않다 (`44a390e`)

Text·Figures 탭의 crop 워커, OCR, PDF 탭이 동시에 PDFium을 부른다. 잠금 없이 8스레드 동시 렌더 테스트를 돌리면 프로세스가 3/3 죽었다(segfault/abort).
`pdfdoc.LOCK`(RLock) 하나를 모든 호출이 거치고, 열어 두는 문서는 호출마다 잠금을 스스로 잡는 `pdfdoc.Document`(닫기는 `weakref.finalize`, 이것도 잠금 안에서).
PDF 탭·`extract_biblio_vision.py`·`rehash_file.py`가 이걸 쓴다. 대가는 백그라운드 렌더 중 PDF 탭이 한 쪽(~0.1 s)쯤 기다릴 수 있다는 것.
`tests/test_pdfdoc.py`가 모든 PDFium 호출이 잠금 안에서 일어나는지 검사한다. 같은 날 RunPod Reserved Pod용 `deploy/chandra2-vllm-pod/batch_ocr.py`의
PyMuPDF도 pypdfium2로 바꿨다(`87bc2fa`, 마지막 PyMuPDF 사용처). 그 이미지를 다시 빌드해 push하는 일은 **이미지 이름(레지스트리)을 몰라 멈춰 있다** — 저장소에는 자리표시자뿐이고 Docker Desktop이 꺼져 있었다.

## 2. 라이선스 데이터는 figsplit으로

[R04](./20261021_R04_Paper_License_Survey.md)의 조사를 도판 서버에 보낸 PDF 단위로 펼친 표(8,934 PDF, 키는 `file_hash` + 저자 성·연도·제목)를 만들어
jikhanserver의 figsplit으로 보냈다. 사용자 결정으로 **라이선스 데이터는 figsplit이 관리**한다 — 표·조사 스크립트(`collect`/`lookup`/`textlic`/`classify`/`sent_list`)·
Crossref/OpenAlex 캐시를 `/mnt/disk1/figsplit-data/licenses/`로 옮겼고, figsplit이 자기 저장소(`data/scripts/licenses/`, 얼린 표 `data/licenses/<날짜>/`)로 이어 받았다.
figsplit은 미국 정부 기관 표지 규칙(+22편 PD), HTML 이스케이프 DOI 해제, 휴지통 제외를 더했다.

## 3. 라이브러리 사본과 전체 백업

- **figsplit용 사본** `/mnt/disk1/figsplit-data/papermeister/` — DB 스냅샷(SQLite 온라인 백업, journal_mode=delete) + `pdf_cache`의 PDF 9,933개(58 GB) + `ocr_json` 9,832개 +
  `by_hash/<sha256>.pdf`·`ocr_by_hash/<sha256>.json` 상대 심볼릭 링크(서버에서 sha256을 다시 계산해 `PaperFile.hash`와 같은 것만, 불일치 0). 주인은 figsplit, README 있음
- **데이터 디렉터리 전체 백업 1회** `/mnt/disk1/backups/papermeister-full/20261022-1628/`(63.9 GB, 그대로 데이터 디렉터리로 쓸 수 있다). 빠진 것: 데이터 폴더의 옛
  `preferences.json`(7/28 이전 사본, 평문 키)과 `figure_queue.lock`. 일일 retention은 `papermeister/`만 청소하므로 안전. PDF·OCR JSON은 rsync `--copy-dest`로 서버 안에서 복사해 네트워크로는 3.65 GB만
- WSL `ssh`/`rsync`는 Windows `known_hosts`가 CRLF라 호스트 키 확인에서 실패한다 — `\r`을 뺀 한 줄짜리 known_hosts를 `UserKnownHostsFile`로 주면 된다(`~/.ssh`는 건드리지 않음)
- OCR JSON 캐시 이름은 `{pdf 파일명}.{hash[:8]}.json`이다 — CLAUDE.md의 `{hash}.json`은 낡은 설명이라 고쳤다(`0858957`)

## 4. 🔴 동기화가 더 새 OCR 캐시를 옛 Zotero 사본으로 덮었다 (`efdf685`)

백업 뒤 Zotero 동기화(새 논문 11편, 컬렉션 2)에서 "OCR JSON refreshed from Zotero" 67개. 16:28 백업과 대조하니 28개는 내용이 같고 바이트만 달랐는데,
**39개는 로컬이 더 새것**이었다(도판 내보내기 `exported_at`이 더 늦고 패널·캡션·항목이 달랐다). `_refresh_sibling_json`이 md5가 다르면 무조건 받아 덮었기 때문.

- **DB는 무사**했다 — `import_figures`는 단계 시각이 더 새로울 때만 반영해서 전부 `unchanged`. 도판·항목·패널 테이블이 동기화 전후로 행 단위 해시까지 같았다
- **Zotero가 뒤처진 이유**: 이 PC의 push 실패. 예외로 실패한 것 117건은 `figure_queue.log`에 있었지만(10건 DNS, 107건 빈 메시지), `replace_attachment_file`이
  예외 없이 `None`을 돌려주는 거부는 아무 기록도 없었다 → 이제 `push_sibling_json`이 경고를 남긴다
- **고침**: `_cache_is_newer()` — OCR 실행(`processed_at`)이 먼저 결정하고(재OCR이면 그 뒤 것이 이긴다), 같은 OCR이면 `figures.exported_at`·`papermeister_meta.biblio_applied_at` 중
  로컬이 늦은 게 하나라도 있으면 캐시를 둔다. 둘 때도 Zotero 쪽의 더 새 단계(`import_figures`)와 더 새 서지 표시는 받고, 행이 바뀌면 캐시를 다시 쓴다.
  옛 코드에서 실패하는 테스트 2개 포함 3개 추가
- **복구**: 39개는 모두 같은 PDF가 여러 Zotero 부모 밑에 있는 쌍둥이였고, 31개는 **쌍둥이끼리 DB의 도판 결과가 달랐다** — 캐시 파일은 하나라 처음 다시 내보낼 때 마지막에 쓴 쌍둥이(때로 더 오래된 것)가 들어갔다.
  그래서 파일마다 단계 시각이 가장 새로운 쌍둥이에서 내보냈다(동기화 전보다 오래된 단계 0, 30행은 그보다도 새 패널). 그 파일을 Zotero 사이블링 82개(쌍둥이 부모마다)에 올려 md5 일치 확인

## 5. Zotero 정리

- **같은 이름 JSON 사이블링 중복** 4곳 9개 — `push_sibling_json`은 `.first()`에만 올리므로 나머지가 뒤처진다. 5개 휴지통(4개는 Zotero에 파일이 없는 404 껍데기, 1개는 같은 내용). 남은 중복 0
- **figsplit이 찾은 "한 PDF가 여러 항목에" 의심 6건**(191 PDF 중) — PDF의 OCR 첫 쪽과 PDF에서 읽은 서지로 진짜 주인을 판정해 figsplit `data/licenses/owners.json`에 넘김.
  잘못 붙은 PDF 2개와 그 JSON 휴지통: 4692(돌고래 2016)에 붙은 Streng & Geyer 2019 PDF(진짜 주인 4370, CC BY), 6988(Barraclough & Nee 2001)에 붙은 Zimkus 2010 PDF
  (진짜 주인 6430 — 파일 이름은 "Barraclough, Nee - 2001"). **6988은 이제 PDF가 없다**. 중복 항목 2개는 Zotero "Merge Items"처럼 남는 쪽에 컬렉션을 합친 뒤 휴지통:
  2612 → 3578(MCMC Intuition for Everyone, +Science / Statistics), 4142 → 4301(Walcott 1920, +1. SSF / Chancelloriid). 3196·3550(책/글 관계)은 그대로
- **DOI** — HTML 이스케이프 2개(3118·5044, Zotero 원본 필드에 `&lt;…&gt;`로 저장돼 있었다) + paperbiblio 사본 2개. 비정형 23개: URL 형태 → `10.…` 11, arXiv → `10.48550/arXiv.…` 2,
  Crossref 제목 일치 확인 후 3(7991 Elsevier PII, 6730 `10:1167` 오타, 3939 BMC Biology), DOI 아닌 값 비움 3(`null`·ISSN·`www.nature.com`), 페이지 주소는 URL 필드로 4.
  **남긴 것**(사용자 결정): DOI 필드의 JSTOR SICI 링크 148 + 인코딩된 SICI 3 — 진짜 DOI는 대개 JSTOR `10.2307/…`라 Crossref 제목 검색으로 찾을 수 있다(1편 1요청). Crossref가 확인 못 한 PII 2(159, 5114), 뜻 모를 숫자 3(4450, 5046, 9882)
- 휴지통은 pyzotero `update_item`이 `deleted` 키를 거부해서 Web API `PATCH {"deleted": 1}` + `If-Unmodified-Since-Version`으로 했다. 모든 변경을 서버에서 다시 읽어 확인했다
- **KOPRI 웹 필터가 Zotero 파일 다운로드를 가끔 가로챈다** — 204번의 JSON이 413바이트 차단 페이지(`warning.html…광고차단정책`)로 왔다가 다시 받으니 통과. 동기화는 JSON이 아니면 덮지 않으므로 안전하지만, 다운로드가 "성공"해도 내용이 HTML일 수 있다
