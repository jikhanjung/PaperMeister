# HANDOFF.md

세션 간 인계용. 새 세션은 이 파일을 먼저 읽는다. **현재 상태와 남은 일만** 둔다 — 지난 일은 `devlog/`(아래 "기록 찾기")에 있고,
2026-10-22 정리 전의 전문(세션 요약·운영 일지 포함)은 `git show da5689b:HANDOFF.md`.

---

## 현재 상태 (2026-10-26)

- **최신 릴리스 v0.2.3**(2026-10-07, 3플랫폼). 코어(Phase 1~3 + D), references(P11~P14), 4월 배치 재OCR([114](./devlog/20261022_114_April_Batch_ReOCR_And_Fragment_Guard.md)), **P16 도판 1차 완주**까지 끝났다
- **라이브러리**(10-26, 휴지통 제외): 논문 9,766, PDF 9,823, 도판 97,982. **대기 0** — 대기하던 27개(10-22 동기화분 12 + 6~10월에 들어와 Process를 안 돌린 15,
  실패 이력 없음, paper 9899~9925 / PaperFile 20022~20048)를 10-23에 OCR → Info → References → 도판까지 끝냈다
  (Info는 Zotero에 쓴 것 1·쓸 것 없음 1·검토 대기 16·이미 같음 9, references 1,881·보유 논문 연결 195, 도판 218·캡션 190·분할 75). 부모 없던 PDF 3개는 `auto_promote_standalone`이 Zotero 부모 항목을 만들었다.
  그중 이미 있던 논문의 중복 항목 5개는 10-26에 옛 항목으로 병합했다(새 항목은 휴지통). 논문이 아닌 문서(검토 노트 등)는 **그대로 둔다**(사용자 결정 10-26 — 이것 말고도 꽤 있다).
  같은 날 **라이브러리 전체의 같은 DOI·제목 중복 142항목(135묶음)도 같은 방식으로 병합**했다 — PDF 내용을 대조해 같은 문서인 것만. [118](./devlog/20261026_118_Library_Wide_Duplicate_Merge.md)
  PDF 다운로드는 이제 `%PDF` 검사 + 재시도를 거친다(KOPRI 차단 페이지). 전부 [117](./devlog/20261023_117_Pending_OCR_And_PDF_Download_Guard.md)
- **P16 도판** — 1차 완주(10-21 05:05, [115](./devlog/20261022_115_P16_Unattended_Run_First_Pass.md)): ≤200쪽 파일 9,554/9,554, 도판 99,041, 캡션 88,762(89.6%), 분할 35,181.
  작업 스케줄러 `PaperMeister Figure Queue`(5분 틱)는 그대로 돌지만 할 일이 없다. **새 컬렉션**은 다음 틱이 잡지만 **이미 끝난 컬렉션에 새로 넣은 PDF는 안 잡는다**
  (`figure_queue.json`의 `files_cache`·`done_batches` — 앱 우클릭 Process Figures로 처리하거나 그 키를 두 곳에서 지울 것)
- **논문 라이선스 데이터는 figsplit이 관리한다**(사용자 결정 10-22) — 첫 조사 [R04](./devlog/20261021_R04_Paper_License_Survey.md), 표·조사 도구는 jikhanserver figsplit
  (`/mnt/disk1/figsplit-data/licenses/`, figsplit 저장소 `data/licenses/`·`data/scripts/licenses/`). figsplit 학습·공개 범위 결정도 그쪽에서
- **백업**: DB는 매일 04:00 jikhanserver `/mnt/disk1/backups/papermeister/`(24개 보존). 데이터 디렉터리 전체는 **한 번만** 떠 두었다 —
  `/mnt/disk1/backups/papermeister-full/20261022-1628/`(10-22 Zotero 정리 **전** 상태, 63.9 GB). figsplit용 라이브러리 사본(DB+PDF+OCR JSON, 정리 뒤)은
  `/mnt/disk1/figsplit-data/papermeister/`(주인 figsplit) — [116](./devlog/20261022_116_Library_Copy_Backup_And_Zotero_Cleanup.md)

## 결정 대기

- **P16 범위 밖 200쪽 초과 ~379파일**(초록집·합본, 도판 ~6만 추정) — 돌릴지
- **재OCR 뒤 references 재추출 여부** — 본문이 새로 나왔으므로 파싱이 달라질 수 있다. 511k행을 버리는 큰 결정이라 몇 편 비교 후
- **references 잔여 130편**(give-up 48 — Treatise·化石 합본·단행본 / 직전 PARTIAL 53 / 처리된 PDF 없음 67) — "Retry Failed References…"로 한 번 볼지 영구 제외할지
- **같은 DOI·제목인데 다른 문서인 5묶음**(118 §2, 병합 안 함) — 본문/부록이 항목 둘로 나뉜 2쌍(`10.1098/rsbl.2004.0194` 1746·1745, `10.1038/s41559-020-01291-1` 2315·2314)은 부록을 본문 항목 밑으로 옮길지 그대로 둘지.
  메타데이터가 틀린 3묶음은 고칠 것 — diva 1615(Stein 2008)·190(Kesidis 2020) 학위논문, molbev 925(Tel Aviv 석사논문), Fossils and Strata 4의 챕터 셋 2440·538·2159(`book` → `bookSection`)
- **처리된 PDF가 둘 이상 붙은 논문 79편**(10-26 실측, 병합 전부터) — 같은 논문의 다른 판본이 한 항목에 둘이면 도판·본문이 두 번 나온다(예: 2765, 4479, 2777, 5069). 하나만 남길지
- **needs_review 일괄 검토**(실측 5,066편, 10-26) — Library "Needs Review" → Metadata 탭 Info 대조. 끝나면 non-dry `reflect_biblio.py` 확인 패스 한 번
- **DOI 필드의 JSTOR SICI 링크 148 + 인코딩된 SICI 3** — 10-22에 그대로 두기로 함(사용자). 진짜 DOI는 대개 JSTOR `10.2307/…`라 Crossref 제목 검색으로 찾을 수 있다(1편 1요청, 천천히)
- **6355 Manuel 2009(Early evolution of symmetry…)의 Zotero 첨부 `732NKRFK`는 PDF가 아니라 ScienceDirect 페이지 HTML이다**(md5 일치, 117) — 본문 8 passage와 JSON 사이블링 `472HNXXQ`가 그 내용.
  진짜 PDF를 Zotero에 넣으면: `pdf_cache/732NKRFK/` 삭제 → PaperFile 8388 hash 비우고 `pending` + passage 삭제 → JSON 사이블링 휴지통 → 재OCR
- **6988 Barraclough & Nee 2001은 PDF가 없다** — 붙어 있던 건 다른 논문(Zimkus 2010)이라 10-22에 뺐다. 진짜 PDF는 라이브러리에 없다
- **RunPod Reserved Pod 이미지 재빌드·push**(10-22 요청, 멈춤) — `deploy/chandra2-vllm-pod`의 PyMuPDF → pypdfium2 반영분. 이미지 이름·레지스트리가 저장소에 없고(README는 자리표시자) Docker Desktop이 꺼져 있었다

## 사용자 액션 대기

- [ ] **설치본 수동 확인** — CI 스모크는 "기동한다"까지만 본다. 제자리 업그레이드(AppId 고정)와 **프로즌 빌드에서 PDF 탭이 그려지는지**(PyInstaller 번들의 `pdfium.dll`)
- [ ] **백업 신선도 감시를 서버에** — 백업은 이 PC가 깨어 있을 때만 돈다. 실패 모드가 "조용히 안 돎"이라 서버 쪽에서:
  `find /mnt/disk1/backups/papermeister -name 'papermeister-*.db.gz' -mtime -2 | grep -q . || echo stale`
- [ ] **서버의 옛 `~/backups` 정리** — retention은 새 디렉터리만 청소한다(10-22 기준 9월 파일 3개, 3.3 GB): `ssh jikhanserver "ls -t ~/backups/papermeister-*.db.gz"` 확인 후 삭제

## 남은 일

### P16 후속
- **쌍둥이(같은 PDF가 여러 Zotero 부모에) 처리** — panels 레인이 해시로 합치지 않아 양쪽이 따로 받는다(link는 `propagate_link`로 복사). 그 결과 쌍둥이끼리 DB 도판 결과가 갈린다
  (10-22에 본 39개 중 31개). 캐시 JSON은 하나라 마지막에 쓴 쌍둥이 것이 들어간다
- reading set 확장 방아쇠에 "얇은 답"(`plate_no_entries`·`caption_shared`·`entries_shrank`) 추가 여부 / 항목 설명에 산지·층준 포함(권고: 포함) / 무게 상한 상향
- 러너: 논문 단위 `--status` 표, 서버 `paused_reason` 백오프
- 앱: 상자 수정·라벨 교정 UI 미연결(`figure_curation`), 도판 목록에서 Figures 탭 해당 블록으로 점프(`FiguresTab.show_figure`는 있음)
- `push_sibling_json`은 같은 이름 사이블링 중 `.first()`에만 올린다(10-22에 중복 0으로 정리했지만 구조는 그대로)

### 앱·동기화 백로그
- `extracted` 잔존분 재시도(7/29 실측 10편 — 해당 폴더 Process 한 번) / Process 시작 시 모드 라벨 상시 표시 여부
- 프레임리스 메인 창: Windows 실물에서 최대화 시 작업표시줄 가림·스냅 동작 미확인, `"native_title_bar": true`의 UI 토글 없음
- 앱 Process 창이 `/api/stats` 몫을 **배치 시작 때 한 번만** 읽는다 — 다른 클라이언트가 붙고 떨어지면 12↔6으로 움직이므로 주기 재조회(`reocr_legacy_ocr.py::follow_the_share`가 60초마다 따라가는 형태로 먼저 구현돼 있다)
- Apply Biblio write-back 추가 검증(Zotero version 증가 + `papermeister_meta` in-place, 다른 머신에서 `BiblioAlreadyApplied`로 스킵되는지) / source·folder 단위 batch Reflect + 결과 다이얼로그
- Zotero 동기화: **컬렉션 멤버십 제거가 반영 안 됨**(`PaperFolder.get_or_create`만 — mirror냐 add-only냐 정책) / 앱에서 휴지통 복원 / PaperFile md5 추적(Zotero에서 PDF를 바꿔도 옛 hash 캐시를 씀) /
  `content_type` 컬럼 / itemType 캐시 / OCR JSON 사이블링 attachment title 정규화(지금은 의도적으로 파일명 그대로) / systematic pull sync(지금은 on-demand) / 컬렉션 수준 메타데이터
- **`ocr_json/`(2.0 GB)에 정기 백업이 없다** — 일일 백업은 DB만. OCR 비용 전체가 여기 있다
- **데이터 경로 설정 가능화** — 착수 전제: 프로덕션 20여 곳의 `from .paths import DB_PATH`(import 시점 바인딩)를 접근자로. 규약 원본은 `.guides/desktop/file-locations.md`(§5·§7), 예시는 `../CTHarvester/utils/paths.py`.
  경로 부재 가드(`check_configured_data_dir()`)는 이미 있다
- 저순위: 병렬 OCR 실측, 암호화·파손 PDF 처리, DB 삭제 후 복구 실증, 커버리지(floor 18%)

---

## 환경·운영 상수 (CLAUDE.md에 없는 것)

- **라이브 DB를 WSL에서 읽기**: `/mnt/c/Users/Jikhan Jung/PaleoBytes/PaperMeister/papermeister.db`를 `?mode=ro`(앱·러너가 쓰는 중이면 `&immutable=1`).
  러너가 DB를 여닫는 순간에 걸리면 `disk I/O error`/`unable to open database file` — 잠시 뒤 다시
- **데이터를 바꾸는 스크립트는 Windows Anaconda env에서** — WSL에서 `"/mnt/c/Users/Jikhan Jung/anaconda3/envs/PaperMeister/python.exe" scripts/…`로 직접 부를 수 있다(Windows 설정·client_id·DB writer 그대로). `--execute` 전엔 앱이 닫혀 있는지(`figure_queue.py`는 예외)
- **ocrserver(jikhanserver, 172.16.112.150)는 이 PC 혼자 쓰지 않는다** — OCR 몫은 `?client_id=`로 물어야 내 몫이 온다(서버 전체 12 vs 내 몫 6), 페이지 단위로 하한을 채워 둔다([114](./devlog/20261022_114_April_Batch_ReOCR_And_Fragment_Guard.md)).
  502/503/504는 컨테이너 재기동이라 분 단위 — healthz 폴링으로 기다렸다 이어서([083](./devlog/20260728_083_Container_Restart_Recovery_Wait.md)·[088](./devlog/20260729_088_Refs_Server_Outage_Visible_In_UI.md)).
  도판 워커 수·호출 간격은 **서버가 Codex 사용량에 맞춰 조절**한다 — 러너는 손댈 것 없다
- **jikhanserver SSH**: 별칭과 known_hosts가 Windows 쪽에만 있다 — 한 줄짜리는 `/mnt/c/Windows/System32/OpenSSH/ssh.exe jikhanserver "…"`,
  큰 전송은 WSL `rsync -e "ssh -o UserKnownHostsFile=<CR 뺀 한 줄> -p 2022 -i ~/.ssh/id_ed25519_kopri_desktop"`(Windows known_hosts가 CRLF라 그대로는 실패)
- **기관망(KOPRI)**: TLS 가로채기(CLAUDE.md, `nettls`)에 더해 **웹 필터가 Zotero 파일 다운로드를 가끔 413바이트 차단 페이지로 바꾼다** — "성공"해도 내용이 HTML일 수 있다(116)
- **도판 러너**: 상태 `<data>/figure_queue.json`, 로그 `<data>/logs/figure_queue.log`, **일시정지 = `<data>/figure_queue.stop`**(지우면 재개), 해제 `install-figure-tick.ps1 -Remove`. 재부팅해도 로그온하면 이어진다. 앱은 켜 둬도 된다
- **Zotero 사이블링 푸시 실패**는 로그에서 찾아 다시 올린다: `grep -oh 'not pushed to the Zotero sibling for [0-9a-f]*' logs/figure_queue*` → `paperfile.hash LIKE '<접두>%'` → `figure_share.py --export --paper-ids … --execute`(115).
  쌍둥이가 있으면 단계가 가장 새로운 쌍둥이에서 내보낼 것(116)
- **Zotero 항목을 휴지통으로**: pyzotero `update_item`이 `deleted`를 거부한다 → Web API `PATCH /items/{key}` `{"deleted": 1}` + `If-Unmodified-Since-Version`. 앱 동기화가 trash를 로컬에 미러한다
- **CI는 push에서만 돈다** — 오래 쉰 뒤 첫 push는 결과를 반드시 확인([090](./devlog/20260813_090_Dependency_Sweep_And_CI_Red_Fortnight.md)). lock 설치는 `python -m pip`(Windows `pip.exe`는 자신을 못 바꾼다)
- **새 런타임 의존성**: `papermeister/about.py` 표에 넣어야 테스트가 통과하고(copyleft 차단), Windows Anaconda env에도 설치해야 라이브가 안 죽는다

## 운영 규칙

- **biblio 추출 뒤 non-dry reflect 한 번** — `reflect_biblio.py --dry-run`은 `status`를 저장하지 않는다. "Needs Review"가 비어 보이면 이 단계가 빠진 것
- **Zotero 출처 Paper를 로컬에서 직접 쓰지 않는다**(P08 §3.5) — 타겟 refresh는 `client._zot.item(key)` → `_parse_item_metadata`
- **`resync_zotero.py`는 위험** — `Paper` drop이 `PaperBiblio`를 cascade 삭제한다. 쓰려면 먼저 PaperBiblio 백업
- **preferences.json을 세션에 노출하지 않는다** — 평문 키. 필요한 값은 `get_pref('key')`로 그 값만
- **세션 마무리**: 이 파일의 "현재 상태"·"남은 일" 갱신 → devlog(결정 과정과 근거) → commit(논리 단위) + push → CI 확인(red면 그 위에 쌓지 않는다)

## 기록 찾기

| 기간 | 무엇 | 어디 |
|---|---|---|
| 03-30 ~ 06-26 | MVP, Zotero, LLM 서지, desktop 앱, 패키징, references 설계, FTS | devlog 001~068 · P01~P13 |
| 06-27 ~ 08-15 | 인용 네트워크, CI·코드 품질, 설정 위치, 백업, 라이선스 감사(v0.1.6·0.1.7), refs 병렬·큐 위생 | 069~092 · P14·P15 · R01~R03 |
| 08-28 ~ 09-09 | TLS, Text 탭 레이아웃, 4월 배치 재OCR·조각 가드 | 093·094 · **114** |
| 09-14 ~ 09-22 | P16 설계·구현(조립·연결·분할·검수·Figures 탭·머신 간 동기화) | P16·P17 · 095~113 · `docs/figure_pipeline_guide.md` · `docs/figure_server_spec_v2.md` |
| 09-23 ~ 10-21 | P16 무인 운영 1차 완주 | **115** · `docs/figure_runner_processing_log.md` |
| 10-21 ~ 10-22 | 논문 라이선스 조사, PDFium 잠금, 백업·사본, Zotero 정리 | R04 · **116** |
| 10-23 | 대기 PDF 27개 OCR~도판, PDF 다운로드 검사·재시도, "et al." 저자 자동 반영 차단 | **117** |
| 10-26 | 라이브러리 전체 같은 DOI·제목 중복 142항목 병합(PDF 내용 대조, 다른 문서 5묶음 제외) | **118** |

릴리스별 변경은 `CHANGELOG.md`, 결정된 설계·규약은 CLAUDE.md와 각 P 문서.
