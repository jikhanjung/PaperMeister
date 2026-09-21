# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: 코어 기능 완성 — Phase 1~3 + Phase D 완료 / **P11 references 추출 완주**(2026-08-28) / P12 CitedWork 정규화 + P13 FTS external-content + P14 인용 네트워크 라이브 반영 완료 / P15 코드품질·CI 완료 → **v0.1.8 릴리스**(3플랫폼, 자산 5종, `build291`) + 사용자 매뉴얼 en/ko 배포 + PaleoBytes 데이터·설치 경로 정렬 + 라이선스 명시(GPL-3.0)**

> **라이브 DB 실측 (2026-08-28, WSL read-only)**: Paper **9,895**.
> references 추출 — `references_checked` **9,765편(98.7%)**, `Reference` **511,338행**(held 매칭 79,736),
> `CitedWork` **264,169노드**. **완주로 본다**(사용자 판단, 2026-08-28).
> 남은 130편의 내역: give-up 48 / 직전 PARTIAL 53 / 처리된 PDF 없음 67 (겹침 있음) —
> 어느 쪽도 배치를 계속 돌려서 줄어드는 종류가 아니다.
>
> **본체 잔여 작업은 이제 references가 아니라 [4월 배치 재OCR](#4월-배치-재ocr-신규-2026-08-28)이다**
> — 2,048편 / 58,401페이지. ocrserver가 놀고 있으므로 지금이 그 창이다.

### 안정적으로 돌아가는 것

- **기존 GUI** (`papermeister/ui/` — **동결**, 신규 개발 없음). Process/Preferences 다이얼로그는 desktop 앱에서 재사용 중
- **CLI** (`cli.py`) — import/process/search/list/show/config/zotero
- **OCR 3-backend**: RunPod serverless / Direct vLLM pod / Wrapper API. Wrapper는 **파이프라인 모드** — 서버 큐에 항상 N페이지 유지, `ocr_min_queued_pages` 미설정이면 서버의 `/api/stats::recommended_concurrency`를 자동 추종
- **Zotero 양방향**: pull(컬렉션·아이템 incremental sync, trash + 영구삭제 미러) + push/write-back(`papermeister/zotero_writeback.py`)
  - `zotero_writeback_enabled` pref **기본 OFF** — OFF면 Apply Biblio가 local-only 경로로 우회한다(다음 pull sync에서 덮어쓰일 수 있음)
  - `zotero_upload_ocr_json`(OCR JSON sibling 업로드) / `auto_promote_standalone`(standalone PDF → Zotero parent 자동 생성, 기본 ON)
  - OCR JSON 안의 `papermeister_meta`가 "이 논문 biblio는 이미 적용됨"을 머신 간에 전달 → 다른 머신에서 LLM 호출을 건너뛴다
  - OCR 진입 시 로컬 캐시 miss면 같은 paper의 `{hash}.json` sibling을 Zotero에서 먼저 받아 재OCR을 회피
- **서지 추출**: Haiku/Sonnet(claude) + Qwen3 → `PaperBiblio`에 비파괴 보관 → `biblio_reflect`가 평가(auto_commit / needs_review) → Zotero 반영
- **References 추출(P11) + CitedWork 정규화(P12) + 인용 네트워크(P14)** — 추출 완주만 남음(아래 "진행 중인 것")
- **검색**: FTS5 external-content(P13) + document 단위 `paper_fts` + 제목 부스트 3단 재랭킹 + 결과·본문 하이라이트
- **desktop 앱** (`python -m desktop`, Windows + Anaconda):
  - Rail(Library/Search 모드 + Sync·Import·Process·Settings·Works 액션) / SourceNav(소스마다 탭 + 컬렉션 트리 + 하단 STATUS 패널) / PaperList(헤더 정렬·인용 스타일 저자·Ctrl+click reveal) / DetailPanel 4탭(**Metadata / PDF / Text / References**, lazy 빌드)
  - status pill: `wait`(pending) → `OCR`(processed) → `done`(applied·auto_committed) / `rev`(needs_review) / `err`(failed) / `skip`(비-PDF 첨부) / `—`(no PDF)
  - 우클릭 — **Paper**: Process OCR·Retry·Extract Biblio·Extract References·Open PDF·Review Biblio·Show in citation network / **폴더·My Library**: Process All(OCR→Biblio)·Extract References·**Retry Failed References…**·Upload OCR JSON (하위폴더 재귀)
  - 진행창 3종(Process / Biblio / References) — Cancel + 서버 다운 시 `ServerGuard`가 큐를 유지한 채 pause → 복구되면 자동 resume.
    References 창은 **동시에 파싱 중인 논문마다 진행바 한 줄**(제목·엔트리 수·%; 엔트리 수를 모르는 동안은 busy)
  - **로컬 폴더 가져오기**(Rail import): 재귀 스캔 + SHA256 dedup. 이미 있는 hash면 새 Paper를 만들지 않고 그 논문을 폴더에 링크한다. 탭 우클릭으로 directory 소스 제거(디스크 파일·OCR 캐시는 보존)
  - **PyInstaller 패키징**: `build_desktop_clean.bat`만 사용한다 — conda 셸 직접 빌드(`build_desktop.bat`)는 Qt DLL 오염으로 실패한다([devlog 061](./devlog/20260615_061_PyInstaller_Conda_DLL_Troubleshooting.md))
- **데이터·로그**: `~/PaleoBytes/PaperMeister/` 아래 `papermeister.db` · `ocr_json/` · `pdf_cache/{zotero_key}/{filename}` · `logs/{ocr,zotero_sync,biblio_YYYYMMDD}.log`

### 진행 중인 것

- **P11 references 추출 완주** — 유일한 본체 잔여 작업 (진행률과 재개는 아래 "다음 할 일")
  - 파이프라인 자체는 완성됐다: 추출(ocrserver Qwen3) → `Reference` 저장 → **추출 직후 자동 resolve**(보유 논문 매칭) → `CitedWork` 정규화(P12 패스1 auto-canonicalize). desktop 우클릭(Paper / 폴더 / My Library)과 `scripts/extract_references.py` 양쪽에서 돈다. 계획 [P11](./devlog/20260625_P11_References_Extraction_Citation_Network.md) · [P12](./devlog/20260625_P12_External_Work_Normalization.md)
  - **held vs cited-only는 `Reference.resolved_paper`의 null 여부**로 판정한다(별도 플래그 없음). 외부 문헌은 `resolved_work`(`CitedWork`)로 dedup되어 공동인용·"자주 인용하지만 미보유" 발굴이 가능해진다
  - `Paper.references_checked`가 재파싱을 막는다. **"참고문헌 없음"은 실패가 아니라 checked-empty**
  - **범위 결정(2026-07-27, 사용자)**: 일반적인 학술지 논문만 잘 처리하면 된다 — 가이드북·도판·목차·부고 등의 헤딩 탐지 정확도는 개선하지 않는다. 단 **조용한 유실·무한 루프를 봉쇄하는 가드(077~079)는 유지**한다
  - ✅ **give-up 카운터 도입 (2026-08-13, [091](./devlog/20260813_091_References_Queue_Hygiene.md))** — 오래 미해결이던 항목.
    `Paper.references_attempts`가 PARTIAL/실패마다 +1, **완전 파싱 성공 시 0으로 리셋**(리셋이 없으면 장애로 실패한 논문이 영영 은퇴 상태로 남는다). 3회면 일반 실행에서 빠지고
    우클릭 **"Retry Failed References…"** / CLI `--only-failed`로만 돌아온다. 기존 DB는 0으로 마이그레이션(추측 backfill 금지 — 관측한 실패만 센다)
  - **desktop도 논문 단위 병렬** (`refs_workers` pref, 기본 4, qwen에서만) — [089](./devlog/20260813_089_Desktop_Parallel_References.md).
    워커는 **LLM 호출만**, 저장·resolve·인덱스 빌드는 메인 스레드(CLI `--workers`와 같은 분할). 진행창은 **동시 논문마다 진행바 한 줄**

### 대기 중
- **needs_review 일괄 검토** — 실측 **5,229편**. Library "Needs Review" 필터 → Metadata 탭의 Biblio 대조 UI로 처리
- **Phase D 후처리**: 위 검토 후 non-dry `reflect_biblio.py` 확인 패스 한 번(desktop 경로 밖에서 생성된 biblio의 status stamp 누락 확인용)

---

## 다음 할 일

> **현재 우선순위 (2026-08-28)**: references는 완주로 종료했다. 본체로 남은 건
> **4월 배치 재OCR 하나**이고, ocrserver를 독점해서 쓸 수 있는 상태다.

### 진행 중 (본체)

- [x] ✅ **references 추출 완주 (2026-08-28)** — **9,765/9,895편(98.7%)**, `Reference` 511,338행.
  남은 130편은 give-up·PARTIAL·PDF 없음이라 배치를 더 돌려서 줄지 않는다.
  **완주 후 작업으로 재-resolve + `normalize_works` 재실행이 남아 있다**(둘 다 멱등).
  실패 경로 복원력은 075~079·083, 큐 위생은 091 참조
- [x] ✅ **`refs_workers=4` 실측 완료 (2026-08-13 12:11~, 큐 정리 후 80분 누적)** — **45.5 refs/min = 직렬 대비 2.91배**,
  논문 **43편/시간**(직렬 ~9), 130초 초과 2.3%, **WARNING 0건**. 남은 1,789편 ETA **약 1.7일**(직렬이면 9일)
  - ⚠️ 첫 19분 표본은 **67편/시간**으로 나왔는데 짧은 창 + 짧은 논문이 겹친 낙관치였다. **80분 누적 43편/시간이 실제값**
  - **오전의 timeout 2건은 재현되지 않았다** — 동시성이 아니라 **Treatise 합본의 거대 입력**(16k~36k자)이 원인이었다
  - **6으로 올리는 건 보류**: 호출 평균이 38s→54s로 이미 경합이 보인다. 더 올리면 130초 선을 넘기 시작해
    백오프가 붙을 수 있고, 어차피 1.5일이면 끝나므로 이득보다 위험이 크다
  - ⚠️ **089의 마이크로벤치마크(4배·6배)는 여전히 근거로 쓰지 말 것** — 입력 684토큰짜리 장난감이었다.
    실제 값은 **2.88배**이고, 이 수치가 실측 근거다
- [ ] **은퇴시킨 47편 처리 방침 결정** — Treatise 합본·化石 합본·단행본이다(079 §e가 보류한 부류).
  본류가 끝난 뒤 "Retry Failed References…"로 한 번 볼지, 영구 제외할지

### 🔴 사용자 액션 대기

- [ ] **v0.1.7 Windows 설치본 수동 확인** — CI 스모크는 "기동한다"까지만 보증한다. 설치 자체와 실기능은 미검증.
  AppId가 v0.1.4부터 고정됐으므로 **제자리 업그레이드로 깔려야 한다** — 그게 곧 이 항목의 검증이다.
  0.1.7은 PDF 엔진이 바뀌었으므로 **프로즌 빌드에서 PDF 탭이 실제로 그려지는지**를 특히 볼 것
  (소스에서는 확인했으나 PyInstaller 번들에 `pdfium.dll`이 제대로 실리는지는 별개 문제다)
- [ ] **백업 신선도 감시를 서버에 건다** — 백업은 **이 PC가 깨어 있을 때만** 돈다.
  `-StartWhenAvailable`/`-WakeToRun`으로 놓친 실행과 절전은 덮지만 **꺼져 있으면 방법이 없다**.
  실패 모드가 "조용히 안 돎"이라 (086에서 2주 몰랐다) **항상 켜져 있는 서버 쪽에서** 봐야 한다:
  `find /mnt/disk1/backups/papermeister -name 'papermeister-*.db.gz' -mtime -2 | grep -q . || echo stale`
- [ ] **서버의 옛 `~/backups` 정리** — 백업 대상을 `/mnt/disk1/backups/papermeister`로 옮겼는데,
  **retention은 새 디렉터리만 청소한다.** 홈에 남은 최대 24개(≈26GB)는 아무도 안 지운다.
  한 번 지워야 한다: `ssh jikhanserver "ls -t ~/backups/papermeister-*.db.gz"` 로 확인 후 삭제
- [ ] **백업 스크립트 Windows 실행** — 7/28 이후 첫 성공 백업이 되는지
- [x] ~~앱 재시작 후 `%LOCALAPPDATA%\PaleoBytes\PaperMeister\preferences.json` 생성 확인~~
  ✅ (2026-08-13 확인) 7/29에 생성됐고 8/5에 갱신됨 — `migrate_legacy_config()`가 라이브에서 실제로 돌았다

### 환경·운영 상수 (매 세션 전제)

- **라이브 DB의 WSL 경로**: `/mnt/c/Users/Jikhan Jung/PaleoBytes/PaperMeister/papermeister.db`.
  앱이 쓰는 중이면 WAL/NTFS 충돌로 `disk I/O error`가 난다 → `?mode=ro&immutable=1`로 열거나
  (마지막 체크포인트 시점 값) Windows에서 `scripts/refs_progress.py`를 쓴다
- **데이터를 바꾸는 스크립트는 Windows(Anaconda)에서 실행한다.** WSL은 read-only 조회 전용
- **ocrserver는 이 PC 혼자 쓰는 게 아니다** — 다른 PC도 같은 서버에 OCR을 돌린다.
  **wrapper 0.2.4가 클라이언트별로 용량을 나눠준다**(2026-08-28). 핵심은 **`?client_id=`를
  붙여서 물어야 한다**는 것 — 서버는 "페이지가 처리 중이거나 대기 중인 client_id"만 활성으로
  세므로, **제출 전 클라이언트는 목록에 없다.** 그냥 물으면 12(서버 전체), 내 id를 주면
  6(내 몫)이 온다. 라이브 확인: `no id → 12 / with id → 6`.
  그래서 `wrapper_get_stats()`가 **기본으로 자기 client_id를 붙인다**(앱 Process 창도 같이 고쳐짐).
  서버 전체 값이 필요하면 `wrapper_get_stats(for_this_client=False)`
  - 배치 도구는 서버 답을 쓰되 `concurrency // (others+1)`과 비교해 **작은 쪽**을 택한다 —
    `client_id` 파라미터를 모르는 옛 wrapper는 조용히 서버 전체를 답하기 때문. `others`는
    `GET /ocr`의 job별 `client_id`에서 **내 것을 빼고** 센다(직전 실행 job이 남아 있으면
    `active_clients`에 내가 포함돼 몫이 절반으로 깎인다)
  - 누가 붙어 있는지 자세히는 `/api/services`의 `scheduler.per_client`
- **wrapper의 작업 단위는 PDF 한 편이지만, concurrency의 단위는 페이지다.**
  그래서 "동시 논문 수"로 조절하면 안 된다 — 중앙값 13페이지 × 12편 = **150페이지**를
  12페이지짜리 서버에 밀어넣게 된다(실제로 그래서 다른 PC를 굶겼다)
- **그 페이지 수는 "넘지 말 상한"이 아니라 "채워 둘 하한"이다.** 앱의 `min_queued_pages`가
  원래 그 뜻이고(`_queued_pages() < min_queued_pages`면 계속 제출), 배치 도구도 같게 맞췄다.
  **`inflight + waiting > share`를 유지**해야 페이지 하나가 끝난 순간 대기 중인 다음 페이지가
  즉시 들어간다. 정확히 share에서 멈추면 논문 경계마다 슬롯이 빈다(실측: inflight가 6→5→3).
  여유분을 share의 1.5배로 잡는 이유는 **논문 한 편의 시간 중 일부만 서버에 있기 때문**이다 —
  앞의 Zotero 다운로드와 뒤의 JSON 업로드 동안 그 페이지들은 클라이언트가 붙잡고 있지만
  서버에서는 논다(실측: share 12에 서버측 outstanding이 11까지 내려감).
  **스레드 풀도 share보다 넉넉해야 한다** — 1페이지 논문이면 스레드가 전부 페이지를 물고 있어서
  뒤에 대기시킬 논문을 제출할 스레드가 안 남는다.
  **더 제출해도 다른 클라이언트를 뺏지 않는다** — admission이 클라이언트별로 잘리므로
  초과분은 내 대기열만 길어진다
- **CI는 push/PR에서만 돈다 — 커밋을 안 하는 동안은 아무도 안 본다.** 7/29~8/12에 Tests가
  Windows 레그에서 red였는데 2주 동안 몰랐다: Linux 레그는 green이라 반만 건강해 보였고,
  main에 push가 없어 마지막 green(7/29)이 계속 표시됐으며, 스케줄로 도는 Security·CodeQL은
  green이었다. 086의 "릴리스를 안 컷하는 동안 아무도 안 본다"가 조건만 바꿔 재발한 것.
  **오래 쉰 뒤 첫 push는 CI 결과를 반드시 확인한다** ([090](./devlog/20260813_090_Dependency_Sweep_And_CI_Red_Fortnight.md))
- **lock을 설치할 땐 `python -m pip`** — `pip-audit`→`pip-api`가 pip 자신을 `requirements-dev.lock`에
  핀하므로 이 설치는 pip를 덮어쓴다. Windows에서 `pip.exe`는 자기가 실행 중인 파일을 못 바꾼다
- **새 런타임 의존성을 넣으면 `papermeister/about.py`의 표에도 넣어야 한다** — 안 넣으면 테스트가 막는다.
  라이선스를 분류하라는 뜻이고, copyleft 하나가 배포본 라이선스를 통째로 바꾸기 때문이다
- **새 런타임 의존성은 Windows Anaconda env(`envs/PaperMeister`)에도 설치해야 한다** — 거기가
  라이브 실행 환경이다. `requirements.txt`만 고치고 넘어가면 다음 실행이 `ModuleNotFoundError`로
  죽는다(0.1.7의 `pypdfium2`에서 실제로 그랬다)
- **기관 네트워크가 TLS를 가로챈다** — `api.zotero.org` 인증서의 발급자가 `CN=KOPRI SSL`이다.
  그 CA는 Windows 루트 저장소에 있으므로 **파이썬이 OS 신뢰 저장소를 보게** 해서 해결했다
  (`papermeister/nettls.py`, 진입점에서 `install_system_trust()` 1회).
  **`verify=False`로 되돌리지 말 것** — 모든 호스트의 검증을 끄는 데다, 옛 패치는 requests에
  매여 있어서 pyzotero가 httpx로 옮겨간 0.1.6 이후 Zotero를 보호하지도 못했다.
  테스트가 재유입을 막는다 ([093](./devlog/20260828_093_TLS_Interception_OS_Trust_Store.md))
- **PDF는 `papermeister/pdfdoc.py`를 통해서만 만진다** — pypdfium2를 직접 import하지 말 것.
  메타데이터 인코딩 보정이 거기 한 곳에만 있고, 라이선스 교체가 가능했던 이유도 진입점이 하나였기 때문이다
- **Chandra2 OCR 출력은 마크다운이 아니라 레이아웃 HTML이다** — 블록마다 `data-label`·`data-bbox`.
  bbox는 **각 축 독립 0..1000 정규화**(라이브에서 crop해 확인). `pages[].page`는 **0-based**.
  Text 탭이 이걸로 헤딩·캡션·표를 살리고 그림을 PDF에서 잘라 온다 ([094](./devlog/20260828_094_Text_Tab_Reads_The_OCR_Layout.md))
- **설치본 `AppId` GUID는 절대 바꾸지 않는다** — 바꾸면 업그레이드가 별개 프로그램으로 설치된다.
  런타임 데이터는 설치/제거가 건드리지 않는다(`[UninstallDelete]` 추가 금지)
- **설정은 데이터와 분리돼 있다** — OS 설정 위치의 `PaleoBytes/PaperMeister/preferences.json`.
  규약·근거는 [R02](./devlog/20260728_R02_Config_File_Location_Convention.md)
- **공통 규약은 `.guides/`(심볼릭 링크)에 있고 이 저장소에 커밋하지 않는다** — 비공개 가이드
  체크아웃을 참조만 한다. 링크가 없으면 체크아웃이 안 걸린 머신이고, **끊어진 링크는 빈
  디렉터리처럼 보이므로** 가이드에 내용이 없다고 판단하기 전에 링크부터 확인할 것.
  거는 법은 [devlog 087](./devlog/20260729_087_Shared_Guides_Checkout.md)
- **ocrserver 간헐적 5xx**: 502/503/504는 컨테이너가 죽었다 다시 뜨는 것이라 분 단위가 걸린다. 그래서 in-place
  재시도가 아니라 **healthz 폴링으로 복구를 기다렸다 같은 배치를 이어서** 한다(`refs_recovery_wait` pref, 상한 900초).
  그 대기는 이제 **References 창과 status bar에 보인다**(멈춘 것과 구분되도록, [devlog 088](./devlog/20260729_088_Refs_Server_Outage_Visible_In_UI.md)).
  **근본 원인은 서버 측(OOM 유력)** — 확정하려면 서버 vLLM 로그의 스택 트레이스가 필요하다.
  [devlog 083](./devlog/20260728_083_Container_Restart_Recovery_Wait.md)

### 4월 배치 재OCR (신규, 2026-08-28)

- [ ] **`scripts/reocr_legacy_ocr.py --execute`** — **2,049편 / 58,402페이지**.
  2026-04-09 이전 OCR은 옛 평문 마크다운이라 Text 탭이 헤딩·캡션·그림을 살리지 못한다
  (형식 전환은 04-09 ↔ 05-13 사이. 이후 처리분은 전부 구조화). **텍스트에서 레이아웃을
  복원할 방법은 없고 재OCR뿐이다**
  - **대상은 캐시에서 도출한다** — 라벨 없는 JSON이면 대상, 생기면 자동 제외.
    그래서 **중단·재실행이 그대로 이어달리기**가 된다. 짧은 논문부터(중앙값 13p, 최장 832p)
  - 재OCR은 `force=True`라 로컬 캐시와 **Zotero sibling 양쪽을 모두 건너뛴다**.
    끝나면 스크립트가 sibling JSON을 in-place 교체한다 — 안 하면 캐시 미스 때 Zotero에서
    옛 JSON을 도로 받아와 조용히 되돌아간다
  - 전제 조건: **앱을 닫고**, Windows에서. references가 완주했으므로 ocrserver 경합은 없다
  - 🟡 **1차 완주 (2026-08-30, 42.6시간)** — **1,892편 변환 / 54편 실패**, 잔여 **52편**.
    실패는 전부 **끝부분 몇 초 사이에 몰렸다**: 08-30 12:51 이후 서버 앞단이 POST를 413으로
    막기 시작했고(그 직전 poll은 JSON 대신 HTML을 반환), **53편은 wrapper에 도달조차 못 했다**
    (서버 job 목록에 없음). 파일 크기 문제가 아니다 — 실패한 것 중 최소가 1.8MB이고
    직전에 240페이지짜리가 성공했다. 지금은 5MB 업로드가 정상이므로 **일시적 장애**였다
  - **실패분은 DB에 failed로 안 찍힌다**(status는 `processed` 유지) → 재실행이 그냥 집어간다
  - 🔴 **조각 유실 사고 (2026-09-08)** — 서버가 `done_with_errors`로 몇 쪽만 돌려준 걸
    클라이언트가 성공으로 받아, **논문 9편이 자기 자신의 2~8%로 덮어씌워졌다**
    (예: Walcott 1916이 694쪽 → 18쪽). 캐시·DB passage·Zotero sibling 세 곳 모두.
    유일한 가드가 "텍스트가 하나라도 있나"였는데 조각은 그걸 통과한다.
    구조화된 정상 출력이라 **재처리 대상으로도 안 보였다**
    - ✅ `text_extract.MIN_PAGE_COVERAGE`(0.5) + `_reject_incomplete_ocr()` —
      **아무것도 쓰기 전에** 거부하므로 기존 데이터가 그대로 남는다. 더 적은 페이지로
      기존 캐시를 덮는 것도 막는다
    - ✅ 배치 스크립트의 `is_fragment()` — 이미 조각으로 저장된 것을 다시 대상에 넣는다.
      **별도 리셋 불필요**: 재실행하면 자동으로 집어간다
    - 전수 스캔 결과 조각은 9,832개 중 **15개**뿐이고 그중 9개가 이 사고다(나머지 6개는 5~6월 것)
  - ✅ **2차 완주 후 전수 점검 (2026-09-09)** — 캐시 9,832건 중 미완결 5건, 본문 없음 3건.
    조각 10편은 전부 복구됨(`Walcott 1916` 694/694 등). 미완결 5건의 **서버측 페이지 오류**는
    `/ocr/{job_id}`의 page.error로 확인:
    - **4건은 인프라 일시 장애** — `404 Not Found`/`502`/`500` from `http://nginx/v1/chat/completions`.
      **재실행하면 복구된다** (모델 백엔드가 잠깐 안 떠 있던 것)
    - **1건은 문서 문제** — `Hansen`(5/6): `render failed: code=7: cmsOpenProfileFromMem failed`.
      색상 프로파일이 깨진 페이지라 다시 돌려도 같다. **영구 미완으로 두는 게 맞다**
    - `--incomplete` 플래그로 "부족한 것 전부"를 대상에 넣는다. **기본값이 아닌 이유**는
      Hansen처럼 100%에 영영 못 닿는 논문이 매 실행마다 다시 잡히기 때문(references의
      give-up 카운터와 같은 교훈)
  - **본문 없음 3건 중 2건은 고아 캐시** (`Kutscher2008`, `Pillet1972...PLT`) — PaperFile 행이
    아예 없다. 라이브러리에서 지운 논문의 잔해라 무해하다. 나머지 1건 `Geyer - The Cambrian of
    the Moroccan Atlas`(pf=3767, 0/41)는 **status가 `processed`라 앱의 Retry로도 못 잡는다** —
    그래서 스크립트가 **본문 없는 캐시도 대상에 넣도록** 고쳤다(기본 동작)
  - ✅ **재발 방지**: `ServerGate` 추가 — 연속 3회 실패면 서버 다운으로 보고 최대 15분
    복구 대기, 안 돌아오면 정상 종료. 없으면 프록시가 몇 분 삐끗할 때 남은 큐가 통째로
    "실패"로 소진된다(1차 실행에서 실제로 그랬다)
  - 시범 실행으로 파이프라인 확인됨(변환 결과가 `data-label` 있는 HTML로 바뀌는 것까지)
  - **재OCR이 끝나면 references를 다시 뽑을지 결정해야 한다** — 본문 텍스트가 새로 나오므로
    참고문헌 파싱 결과도 달라질 수 있다. 지금 511,338행을 버리고 다시 하는 건 큰 결정이라
    보류. 먼저 몇 편만 비교해 볼 것

### references 잔여 130편 (완주 후 정리)

- [ ] **give-up 48편** — Treatise·化石 합본·단행본. "Retry Failed References…"로 한 번 볼지,
  영구 제외할지 (079 §e가 보류한 부류)
- [ ] **직전 PARTIAL 53편** — `Reference` 행은 있는데 `references_checked`가 안 찍힌 것들
- [ ] **처리된 PDF 없음 67편** — 애초에 추출할 본문이 없다. references 문제가 아니라 OCR 문제

### P16 도판 패널 분할 (계획, 2026-09-14)

- [ ] **[P16](./devlog/20260914_P16_Figure_Panel_Split.md)** — 논문 도판·플레이트를 소패널 단위로:
  캡션 연결·분할(Claude Opus 5, 논문 1회) + 이미지 분할(GPT-6 Astra/Sol, 도판 1회)을 **ocrserver가 호출**,
  결과는 **PaperMeister DB**(`Figure`/`FigureEntry`/`FigurePanel`). 조립은 클라이언트 규칙.
  fsis2026이 두 달 치른 교훈(지어낸 묘사가 캡션 칸에, 사후 연결 추론, 원본 삭제로 95건 손실)을 구조로 막는다
  - **Phase 0 완료(2026-09-15, [095](./devlog/20260915_095_P16_Phase0_Figure_Assembly_Survey.md))** — 전 캐시 도판 156,502,
    플레이트 병합 4,463쪽, **조각난 도판 2,211**(계획에 없던 세 번째 조립 방식 `caption_group_union`), 분할 후보 추정 23,745.
    이중 번호 플레이트(Tafel 13 + Plate 2)도 한 장으로. 파일럿 30편 목록은 095 §4
  - **Phase 1 구현 완료(2026-09-15, [096](./devlog/20260915_096_P16_Phase1_Figure_Store_And_List.md))** — `Figure`·`FigureEntry`·`FigurePanel`
    테이블, 다시 돌려도 안전한 저장(`figure_store.py`: 안 나오면 접고 지우지 않음, 사람 결정 보존), Text 탭 도판 목록.
    라이브 DB 읽기 전용 dry run: 파일럿 30편·도판 295개
  - **fsis edge case 정리 반영(2026-09-15, [097](./devlog/20260915_097_P16_Assembly_Rules_From_fsis_Edge_Cases.md))** — 표지 줄·사진 한 장 플레이트·
    번호 추론(앞 쪽 설명 제목·다음 쪽 N-1·번호 없는 PLATE)·도판별 캡션 플레이트(`Plate N, Fig. M`)·조각 그림 틈 제한·옆 단 캡션·
    재 OCR로 좌표만 옮겨진 행 유지. 라이브 렌더 검토에서 둘을 더 고침(마주 보는 두 쪽 플레이트, 인용 캡션). Phase 2·3 요구는 P16 §1.3.
    **파일럿 목록이 새 규칙으로 다시 뽑혔다** — 아래 저장은 이 목록으로
  - **[P17](./devlog/20260916_P17_P16_Client_Readiness_For_ocrserver.md) (2026-09-16)** — fsis가 9/16에 edge case·설계 가이드를 다시 고쳤다(21건 PDF 직접 검수).
    새로 온 것은 조립이 아니라 **② 연결 · ③ 분할 · 저장 · 검수** 쪽 = ocrserver 착수 전에 **여기서 정해야 할 것**. 준비 목록 A~G(P17 §4):
    검수 도구(contact sheet · curate 스크립트 — 게이트에 필요한데 없다) → 파일럿 저장·검수 → 조립 후보 셋 측정 → 스키마 보강(`caption_pages`·`continuation_of`·
    `*_locked`·`printed_label`) + 보호 판정 한 곳 + `blocks_json`으로 조각 부활 방지 + `store_mode` 예외 격리(지금은 `try`가 없다) →
    `link_payload`(앞·뒤 쪽 포함, 설명 쪽 우선, 배치) + 검증·반영(skipped ≠ cleared, 이름 정규화 양쪽) → `panel_key`에서 entries 제외 · `split_targets` 제외 사유 출력 →
    프롬프트·스키마 파일 + **명세 v2** → 서버에 넘긴다
    - 🔴 **사용자 확인 2건**: 프롬프트·스키마를 PaperMeister가 갖고 요청에 실어 보내기(P17 §3.2, P16 §6.3·6.4 변경) / `panel_key`에서 entries digest 빼고 재연결 규칙(P17 §3.5, P16 §5 변경)
    - ✅ **결정(2026-09-16)** — 둘 다 채택. 같은 날 더 정한 것: ②도 Astra(Opus 안 씀, 확정) · 의심 도판은 ①′ 재판정(Astra 가
      작업 폴더에서 앞뒤 쪽·전체 텍스트를 스스로 본다) · 호출은 5분에 1건으로 시작. 정리: [`docs/figure_pipeline_client_plan.md`](./docs/figure_pipeline_client_plan.md)
      (서버 짝 문서 ocrserver `devlog/20260916_P02_…`)
    - 🔴 **P02 대조에서 나온 명세 구멍** — P02 §3.3은 작업 폴더 텍스트를 **서버 DB**에서 만든다. RunPod 시절 논문은 서버에 job이 없고, 9/8 조각 사고의
      job은 서버에 그대로 남아 있다 → **텍스트는 클라이언트 캐시가 원천**, `POST /figures/workspace` + `ocr_digest`로 올린다(클라이언트 계획 §10.1). 명세 v2·P02 §3.3에 반영할 것.
      D8(5분 1건)이면 파일럿 게이트만 ≈ 4일 — 게이트 표본은 ② 30편 · ③ 도판 100으로 자른다(§10.2)
  - ✅ **A 검수 도구 (2026-09-16, [098](./devlog/20260916_098_P16_Review_Sheets_And_Curation.md))** — `scripts/figure_contact_sheet.py`(그림 있는 쪽을 9층으로 나눠
    쪽 렌더 위에 상자를 그린 HTML, 저장 전에도 동작) + `scripts/figure_curate.py`(confirm/dismiss/restore/rename/set-bbox/merge, `--reason` 필수,
    `<DATA_DIR>/tmp/p16_curation/` 기록 + `replay`). 파일럿 시트는 이미 생성돼 있다: `$env:USERPROFILE\PaleoBytes\PaperMeister\tmp\p16_review\index.html`
    (그림 있는 쪽 2,857 — dropped 34 · plate_inferred 11 · dup_number 28 · many_marks 7 · plate_single 467 · plate_union 191 · cut_up 94 · body 2,025)
    - 🔴 **첫 발견**: `tiny` 필터가 번호 캡션 달린 작은 본문 그림을 버린다(Westergård p.27 `Fig. 10`). C 단계에서 "번호 캡션이 바로 아래면 크기 무관"을 전 캐시 dry-run으로 재고 넣을 것
  - ✅ **B-1 파일럿 저장 완료 (2026-09-16, Windows)** — `Figure` **3,750행**(dry run과 동일): body single 2,980 · cut-up 101 · plate union 202 · plate single 467 ·
    plate_inferred 11. 시트도 `#id`로 재생성됨(`$env:USERPROFILE\PaleoBytes\PaperMeister\tmp\p16_review\index.html`)
  - ✅ **B-2 Phase 1 게이트 통과 (2026-09-16, 사용자 검수, 098 §7)** — 8층 전부 봄. plate_inferred·plate_single·plate_union 전부 맞음(키릴·한글 추론 포함).
    틀린 것은 규칙 버그 둘(→ 고침: tiny 소형 그림 `c67cb71` · `Pl. 2 A/2.B` 접미사 `b34abff`, 덤으로 번호 캡션 겹침 허용 → 캡션 힌트 +302)과
    **규칙으로 못 만드는 것**(블록 없는 플레이트 1191 · PDF 안 중복 1080 · 펼침 스캔 562/8833 · 글자를 그림으로 8615 · 빈 영역 #889).
    **사용자 결정: 규칙은 여기까지, 안 걸리는 건 LLM에 텍스트를 다 주고 찾게 한다**(D4) → 위 다섯이 ①′ detect의 첫 사유 목록
    - [ ] Windows에서 `assemble_figures.py --pilot … --execute` **다시**(규칙 셋 반영, refresh/new만) · 구분선 #791(1334)·빈 영역 #889(7987)는 `figure_curate.py dismiss`
  - [ ] **C 조립 후보 측정** — 이번 검수로 사실상 끝(tiny·접미사 반영, 다음 쪽 설명·전폭 캡션은 detect로). 남은 건 없음
  - ✅ **D′ `figures.suspect()` (2026-09-16, [099](./devlog/20260916_099_P16_Uncertainty_Reasons.md))** — 도판마다 `reasons`(dup_number · many_marks · unmarked_plate_page · no_caption ·
    text_as_figure · fragmented), 쪽마다 `suspicions`(plate_without_pictures · caption_without_figure). 파일럿 24.6%(≈450 항목) · 전 캐시 **33.4%**(≈29,000 항목) —
    4분의 3이 `no_caption`인데 **그건 ② link가 어차피 푼다** → detect 사전 항목은 `no_caption`을 빼면 파일럿 ≈140 · 전 캐시 ≈7,000. 덤: `图 版`·`Tabl.`·키릴 로마숫자(`ХХV`) 파싱 구멍 셋 고침
    - G 단계 메모(099 §4): detect 항목은 **쪽 단위**(힌트 상자 여러 개) · 쪽 의심은 **자리표시 행** · 결과 verdict에 **`merge`** 추가
  - ✅ **D (2026-09-16, [100](./devlog/20260916_100_P16_Schema_Protection_Placeholders.md))** — 스키마(`uncertain_reasons_json`·`bbox_source`·detect_*·`caption_pages_json`·`continuation_of`·
    `panel_entries_digest`·`*_locked` / entry `printed_label`·`label_status`·`specimen_number` / panel `annotation`, `_migrate` 표 하나) · **`figure_store.protection()` 한 곳** ·
    사람의 행이 `blocks_json`으로 조각을 대변(absorbed/contested) · 쪽 의심 자리표시 행(`assembly='page'`) · `store_mode` 파일 단위 격리. 라이브 사본 dry run: new 66(자리표시 37 + 키릴/Tabl. 플레이트 10) · refreshed 909 · failed 0
    - ✅ **Windows 재저장 완료 (2026-09-17)** — 라이브 DB 마이그레이션(D 컬럼 + REINDEX) + 파일럿: 3,790 도판(의심 969) · new 66 · refreshed 909 · folded 30 · failed 0 — 사본 dry run과 동일.
      시트 재생성(dropped 32 · plate_inferred 8 · dup_number 24 · many_marks 15 …), `figure_review.py`: link 대기 3,732 · detect 대기 510 · 검수 사유별(no_caption 468 …) · 보존 2
  - ✅ **E (2026-09-16, [101](./devlog/20260916_101_P16_Link_Stage_Client_Side.md))** — `papermeister/figure_link.py`: `link_targets`(due/context/excluded 사유) · `link_payload`(도판+힌트, 텍스트 없음) ·
    `workspace_payload`(캐시 그대로 + `ocr_digest`) · `validate_link_result`(밖의 id/쪽 거절, 지어낸 캡션·설명/공유 캡션/빈 플레이트는 검수 사유, 항목 감소는 덮지 않음, skipped는 기존 값 유지) ·
    `apply_link`(보호 판정·내용 해시 unchanged). `scripts/link_figures.py --dump`: 파일럿 due 3,752 · 요청 중앙값 6 KB · 작업 폴더 텍스트 중앙값 147 KB, 합 36 MB. 이름 정규화는 불필요(결과가 figure_id로 온다)
  - ✅ **F (2026-09-16, [102](./devlog/20260916_102_P16_Panel_Stage_And_Review.md))** — `figure_panels.py`(`panel_key`=이미지 정체만 · `split_targets` 사유 · 조각 상자→도판 좌표 · fsis 검증기 이식+무라벨 채움 · `apply_panels` · **`rematch`** 라벨 재연결) ·
    `figure_review.py`(5범주, 레인과 같은 판정) · `scripts/split_panels.py`·`figure_review.py`. 🔴 **D 마이그레이션 버그 잡음**: `continuation_of` 인덱스가 컬럼보다 먼저 생겨 UPDATE가 malformed → `REINDEX`(102 §4). 사본 재검증 failed 0
  - ✅ **G (2026-09-16, [103](./devlog/20260916_103_P16_Prompts_And_Server_Spec_v2.md))** — `papermeister/figure_prompts/`(detect·link·panels `.md` + `.schema.json`, `load()`가 해시 버전) ·
    **[`docs/figure_server_spec_v2.md`](./docs/figure_server_spec_v2.md)** = 서버 명세 원본(workspace·detect 쪽 단위·`from`/`dismiss`·워커 요구·규모). **→ ocrserver P02 0단계 해제, 서버 착수 가능**
  - ✅ **H 코드 (2026-09-17, [104](./devlog/20260917_104_P16_Lanes_And_Detect.md))** — `figure_client.py`(HTTP, paused 워커는 기다림) · `figure_detect.py`(쪽 단위 항목, `from`/`dismiss`→kept/adjusted/merge/split/new/dismiss, 사람 행 불가침) ·
    `figure_lane.py` · `link_figures.py --execute/--collect` · `detect_figures.py` · `split_panels.py --execute`. 라이브 dry run 통과. 서버(0.3.3 + 워커 systemd)는 대기 중
  - ✅ **첫 실제 호출 (2026-09-17)** — `link_figures.py --paper-ids 664 --execute`: Westergård 1936, **24/24 반영, 거절 0, 지어낸 설명 0**, 46쪽 훑음, **969 s**.
    범위 펼침(`Fig. 2 a/b` → 2a·2b)·분류군 병합·펼침 스캔 facing-page 설명 모두 프롬프트대로. 검수 1건은 모델이 OCR 오독(`'Glandicus'` → `Œlandicus`)을 고친 것 → 검사기 완화(`00cd4bb`)
  - 🟡 **Phase 2 게이트 진행 중** — 파일럿 `--limit 30 --execute --no-wait`로 **30잡(726 도판) 제출**(09-17). 워커 직렬 + 5분 간격이라 5~10시간.
    거두기: `python scripts/link_figures.py --collect --execute`(앱 닫고) → `figure_review.py --pilot …`. 볼 것: `budget_exhausted` 비율(969 s/46쪽이라 200쪽급은 1200 s 상한에 걸릴 수 있음 → 서버 상한↑ vs 클라이언트 플레이트 묶음 분할) · 검수 사유 분포 · `pages_consulted`
  - **결정(2026-09-17, 사용자)**: link·detect는 논문의 **OCR 텍스트 전체**가 ocrserver 작업 폴더에 올라가고, Astra가 여는 만큼(664는 46/46쪽) **OpenAI로 간다**.
    PDF를 보내 도판을 찾게 하는 것과 정보량이 같으므로 **받아들인다**. PDF 파일 자체는 OpenAI로 가지 않는다(detect 쪽 이미지·panels 크롭만).
    워커가 로그인한 ChatGPT 계정의 **"Improve the model for everyone" 토글을 껐다**(2026-09-17) — 학습 데이터 사용 제외. 그 전에 나간 것은 664 + 파일럿 앞 몇 편
  - ✅ **같은 PDF가 Zotero 부모 여럿에 걸린 경우** — ocrserver가 `e5def301…`(이창숙 2004 = 4386/9832/9841) link 잡 3개를 같은 초에 받은 것을 보고함. 해시는 같은데 `figure_id`가 달라 서버 dedup 밖.
    고침: 레인은 **해시당 한 번** 제출, 반영 뒤 `figure_link.propagate_link()`가 같은 (쪽·상자)의 형제 행에 복사(보호·기연결 행은 건너뜀). 이번 파일럿의 중복 3쌍은 이미 큐에 있어 그대로 돈다(`--collect`가 각각 반영 → 복사는 unchanged)
  - 🔴 **8833 Bala 1976(109쪽·도판 91) 3회 실패 → `budget_exhausted`** (ocrserver 보고, 10:49 UTC: 완료 31 · 대기 7 · 상한 초과 1). 세 번 다 설명을 다 읽고 **답(도판 91개)을 쓰는 단계에서 웹소켓이 끊김** —
    답 크기 문제. 고침: 레인이 due 도판을 **40개 이하 항목으로 분할**(`link_items`, 키 `…#i/n`, context는 모든 항목에), 답은 항목별 검증 후 병합(`LinkCheck.merge`).
    8833은 `--collect`가 옛 키(단일 항목)를 stale로 건너뛰므로 **`link_figures.py --paper-ids 8833 --execute`로 다시 제출**(3 항목). 대기 중인 291쪽(7450)·218쪽(8176)도 같은 위험 — 큐에 이미 단일 항목으로 들어가 있음
  - ✅ **Phase 2 게이트 1차 거둠 (2026-09-18)** — 서버: 27편·항목 36(단일 27 + 분할 9) 완료, 도판 707 요청 → 답 542, 항목 3,898, 실패 0, 세션 합 7.4 h, 입력 12.6M 토큰(대부분 캐시).
    분할 효과: 8833 39/40+39/40+11/11, 8176 38/40+25/25, 7450 40/40+40/40+1/1 + **1/4만 3600 s 초과**. `--collect`: **written 397 + 형제 복사 23**, rejected 0, `description_not_printed` 0.
    - 검수 사유 대조: `caption_not_printed` 32는 전부 키릴 논문에서 모델이 OCR 오독·격변화를 고친 것 → 검사기를 **어간(5자)+동형문자 접기** 비교로 → 4건(진짜 대조 대상). `caption_shared` 75는
      **파서가 사진별로 나눈 한 그림/플레이트**(8422 p9 `Text-figs. 8–11`, 1147 `Tafel IV`) — 모델은 사진마다 맞는 항목을 붙였고, 합치는 건 detect 몫 → `caption_shared`를 **detect 트리거에 추가**. 순서는 ①′→②가 맞다
    - 버그 셋 고침: `/figures/jobs` 응답 `items` 키 · collect가 형제 파일(같은 해시)의 잡을 첫 파일에 매핑해 헛시도 계산 → 답의 `figure_id`로 파일 식별 · skipped 사유를 행에 기록(`link_skipped:<reason>`)
    - ✅ Windows(2026-09-18): `--recheck --execute`(사유 재계산) · 7450 1/4을 `--per-item 20`으로 재제출(큐에서 처리 중, 나중에 `--collect --execute`)
  - ✅ 7450 2×20 재제출 → **39/40 반영**. 파일럿 27편 link 완주. `--collect`가 옛 잡을 다시 읽으며 skipped 행 시도를 또 세던 것 고침(같은 답 digest면 unchanged) · `link_skipped:not_a_figure`(26, Walcott 인장·표)를 detect 트리거에
  - ✅ **①′ detect 표본 통과 (2026-09-18)** — 7편 27쪽 전부 답, conflicts 0, failed 0, 쪽당 72–170 s. merged 107 · new 13 · adjusted 16 · dismissed 6.
    8803 사진 85장 → 图版 I–IV 넷 · 1191 p.221 자리표시 → `Pl. 50.` · 1147 Tafel IV 조각 6 → 1 · 8422 조각 → Text-fig. 8–15 · 1080 `Taf. IV` p.40/60/61 = 중복 스캔으로 판정(오독 아님) · 8615 `圖版` 글자 접힘.
    파일럿 전체 detect 대상은 55편·190쪽(아직 안 돌림)
    - 🟡 합쳐진·보정된 행 캡션 제출(7잡, 152 도판) · **③ panels 표본 제출**(664 15 · 7450 68 · 8833 29 = 112장) → 각각 `--collect --execute`
    - 🔴 **collect 회귀 잡음**: 40개 분할 뒤 옛 단일 항목 잡(1189·1190·3853, 48~79 도판)이 `stale key`로 안 거둬짐 → 후보 키에 비분할 모양 추가. `--collect --execute` 다시 → 되찾힘
    - 파일럿 link 진행: 108편 중 첫 30편만(461 linked / 3,633). 나머지 ~70편(3,143 도판)은 `--pilot --execute --no-wait`로 낼 수 있음(하루 이상)
    - 🔴 **끊김은 답 크기(항목 수)를 따른다**(ocrserver 실측 09-18: 5k 토큰 미만 0건 · 15k 초과 5/18; 1191 Barrande는 18도판 묶음도 실패 — 플레이트당 항목 수십 개).
      분할 기준을 **도판 수 → 예상 답 무게**(플레이트 8 · 본문 1, 항목당 80)로 바꿈: 1191 6항목 · 3853 2항목 · 664 1항목. `--per-item`도 무게. 서버는 HTTPS 전송 테스트 중(웹소켓 끊김 완화, 완치는 아님)
    - **서버 결정(09-18 09:35 UTC, ocrserver devlog 047)**: HTTPS(SSE) 실험도 40도판 항목에서 3회 끊김·60분 타임아웃 → **워커 전송 유지, 해법은 클라이언트 무게 분할**. 잡 상태에 `cancelled` 추가(클라이언트 `TERMINAL`에 반영).
      호출 간격 **`FIGURES_MIN_INTERVAL=120`**(사용자 결정 06:02; D8의 300에서 하향). panels 111장 진행 중(끊김 0, 70–90 s/장)
    - ✅ 09-18 저녁 `link_figures.py --collect --execute` ×3(멱등 확인): detect 뒤 7편 답 → **written 175 + 형제 복사 17**, rejected 0. 1191(6항목)·3853(2항목)은 panels 뒤 큐에서 대기 중 → 나중에 `--collect`. 80이 Barrande에서 걸리면 그 논문만 `--per-item 40`
    - ✅ 09-19 collect: **7450 panels 68/68**(패널 820, 검토 사유 0) · **8833 panels 29/29** · 3853 link 답은 앞선 잡에서 이미 반영(68 captioned, 11은 not_a_figure로 소진). **1191**: 6항목 중 5 done → **31 written(40/58 captioned)**, 1/6 실패(15 도판 미답, `--paper-ids 1191 --execute --no-wait`로 재제출하면 남은 것만 감), 3행 소진
    - 🔴→✅ **split 이동 회귀**: 제출 뒤 due 집합이 바뀌면(행 접힘·소진·형제 복사) 같은 무게로 잘라도 항목 수가 달라져 키가 하나도 안 맞음 → 1191 답 40도판이 표류. `figure_link.items_from_replies()`가 **답이 이름 붙인 figure_id로 항목을 재구성**(collect가 후보 키 실패 시 사용). 회귀 테스트 추가
    - ✅ **③ panels 첫 답(664)**: `split_panels.py --collect --execute` → 15장 중 **14 반영**, 1 실패(`duplicate_caption_index` #1360). 플레이트당 6–33패널, a/b 부패널까지 상자가 표본에 딱 맞음(Plate I 33/33). 눈으로 볼 시트: **`scripts/panel_sheet.py --paper-ids 664`** → `<data>\tmp\p16_panels\664\index.html`(도판 crop + 패널 상자 + 매칭 항목). 7450(68)·8833(29)은 서버 진행 중(70–90 s/장) → `--collect --execute` 뒤 같은 시트로
  - **Windows 명령은 WSL에서 직접 실행 가능**: `"/mnt/c/Users/Jikhan Jung/anaconda3/envs/PaperMeister/python.exe" scripts/…`(Windows 설정·client_id·DB writer 그대로). `--execute` 전엔 앱이 닫혀 있는지 확인
  - ✅ **Phase 4a — 도판 결과 ↔ 캐시 JSON ↔ Zotero sibling** (2026-09-18, [105](./devlog/20260918_105_P16_Figures_Ride_In_The_OCR_JSON.md)): `figure_share.py`(정체로 직렬화, `ocr_digest`·`file_hash` 가드, 새 결과만 갱신, 사람 행 불가침).
    DB→JSON은 레인·curate 반영 뒤 자동, JSON→DB는 sibling 다운로드·Text 탭 첫 로드·assemble 저장 때. 파일럿 108편 JSON 백필(`--no-push`). Zotero 푸시는 pref `zotero_upload_ocr_json`이 켜져 있을 때 다음 반영부터
  - ✅ **Phase 4b (앱)** (2026-09-18, [106](./devlog/20260918_106_P16_Process_Figures_In_The_App.md)): 우클릭 "Process Figures"(논문/폴더/전체) → `figure_pipeline.process_file`이 ①→①′→②→③을 **한 논문씩** 직렬 큐로(끝난 단계는 키로 건너뜀, 단계마다 JSON 갱신) + `FiguresWindow`(워커 paused = "Waiting", 취소는 다음 단계에서) + 서버 미설정이면 **비활성 + 이유 툴팁**. 537 passed.
    - 🟡 **앱에서 실전 미실행** — 먼저 다 끝난 논문(서버 호출 0, "nothing to do")으로, 다음 새 논문 하나로 확인. 파일럿의 미수거 잡(link 7편+1191/3853, panels 112장)은 레인 `--collect --execute`로 거둔 뒤
  - ✅ **Phase 5 step 1** (2026-09-21, [107](./devlog/20260921_107_P16_Figure_List_Shows_Entries_And_Panels.md)): Text 탭 도판 목록 줄에 `33 panels / 33 entries` · `1 unmatched` · `panels failed` · `single image` 표시(`FigureRow.entries/panels/unmatched/panel_state`, 논문당 쿼리 2개). 툴팁에 한 문장
  - ✅ **Phase 5 step 2·3** (2026-09-21, [108](./devlog/20260921_108_P16_Panel_Tiles_And_Reader_Overlay.md)): 도판 줄 선택 → 아래 **패널 타일**(`PanelTiles`, 워커가 페이지 1회 렌더 후 패널별 crop, 색 테두리, hover/클릭에 매칭 항목) + 리더 도판 이미지 위 **같은 색 상자 오버레이**(`OcrView.set_panels`/`draw_panel_boxes`, crop과 같은 픽셀 프레임), 목록 헤더 "Panel boxes" 토글. 664 Plate I 실물로 확인. 545 passed
    - 같은 날 추가: 패널이 없는(캡션만 연결된) 도판을 고르면 같은 자리에 **항목 목록**(라벨·설명·표본번호, `show_entries`/`load_entries`)
    - 같은 날 교체: 타일 격자 → **도판 전체 + 패널 상자**(`FigureCanvas`, 페인트 시 그림) 왼쪽, **항목 목록** 오른쪽(패널 색). 항목 클릭 → 상자 노랑 강조·나머지 흐림, 상자 클릭 → 항목 선택(겹치면 가장 작은 상자). 미매칭 항목·항목 없는 패널은 뒤에 회색
  - ✅ **Figures 탭** (2026-09-21, [109](./devlog/20260921_109_P16_Figures_Tab.md)): Text와 References 사이. 도판/플레이트 블록을 페이지 순으로 — 도판 전체(≤760px) + 서브피겨 상자, 아래 캡션 항목(패널 색). **상자 hover → 항목 노랑 채움, 항목 hover → 상자 노랑 강조·나머지 흐림**, 클릭은 고정. 렌더는 뷰포트 근처만(600px 선행, 2,400px 밖 해제, 최대 10장 보유). conftest에 `papermeister.*` 재import 복원 픽스처 추가(전체 실행에서만 나던 "uninitialized Proxy")
    - 같은 날: 상자 hover 툴팁(항목), 도판 아래 **Entries/Caption 탭**, Figures·PDF 탭 **폭 맞춤**(리사이즈 시 재맞춤, 스크롤바 상시 표시), 메인 스플리터 비례(1/2/2). ③ 추가: **1737 Bruton 10/10 · 1541 Naimark 3/4**(Fig. 2 `duplicate_caption_index`)
    - 같은 날 정리(사용자 요청): **Text 탭에서 도판 목록·분할 뷰·리더 상자 오버레이 제거** — Text는 본문+도판 인라인만, 상세는 Figures 탭. `panel_tiles.py`·`figure_list.py` 삭제, 캔버스·워커는 `figure_canvas.py`로. 패널 상자는 **한 가지 옅은 색**(`PANEL_COLOURS = ('#7b93ad',)`), hover/클릭만 노랑
    - ③ 검사기 완화: 한 항목이 여러 패널(사진+선화, 스테레오 쌍)이면 거부가 아니라 `entry_on_several_panels` 검토 — 1541 Fig. 2(6패널)·664 Fig. 11(9패널) 반영. `split_panels.py --figure-ids N --force`(서버 캐시 우회)
    - 🟡 **③ 파일럿 전체 제출**(09-21): link 끝난 나머지 논문 **253장 / 32잡** `--pilot --execute --no-wait`. 장당 70–150 s → **6–10시간**. 끝나면 앱 닫고 `split_panels.py --collect --execute`. ⚠️ panels 레인은 **같은 PDF 형제를 해시로 합치지 않는다**(Lee 2004 ×3, Müller 2010 ×2 → 11장 중복 제출) — link의 `propagate_link` 같은 처리가 필요
    - 남은 것: 앱에서 상자 수정/라벨 교정(`figure_curation` UI 미연결), 도판 목록에서 Figures 탭의 해당 블록으로 점프(`FiguresTab.show_figure`는 있음)
  - 1191 Barrande(09-21): `e7708b8a` 3항목 거둠(2/3·3/3 → Pl. 5–10 6장 written 369항목). **1/3은 done이지만 사실상 실패**(9장 중 243만, 그것도 항목 1개에 Fig. 3·5·6·10·12를 뭉침; 나머지 8장은 figures에도 skipped에도 없음 — 웹소켓 재연결 뒤 컨텍스트 유실, ocrserver 분석). 244–246은 이걸로 attempts 3 소진
    → **`--relink 243,244,245,246 --execute`**(새 옵션: 캡션 결과·항목·시도 삭제, 사람 캡션은 거부) 뒤 **`--per-item 8`로 플레이트 1장 = 1항목** 4개 제출(`4e377fbc`). 본문 그림 6장(240–242·247·248·256)은 not_a_figure로 소진 상태 그대로 둠.
    ✅ 거둠(09-21): **4/4 done, 1,038 s** — Pl. 1(p.4) 5항목 · Pl. 1(p.10, 옛 'Plate I') 16항목 · Pl. 2B 28 · Pl. 3 51. 1191은 58행 중 **50 captioned**, 8 소진(본문 그림). ⚠️ p.4와 p.10이 같은 설명(p.7–8)을 받음 — p.4가 Pl. 1의 부분 교정쇄인지 사람이 볼 것
  - [ ] 릴리스는 **pre-release beta**(`v0.2.0-beta.1`, `release.yml`이 `-beta`를 prerelease로) — CHANGELOG + ko 카탈로그 + `version.py`(지금 0.1.9) + 태그
    - **프롬프트 손볼 것(모아서 한 번에 — 버전이 바뀌면 linked 444행이 전부 다시 due)**: `name`은 인쇄된 단어 포함(`Text-fig. 15`, 맨 `15` 금지; 8803 p.29만 `Plate II`로 영어화) → 합쳐진 행은 link가 새 키로 다시 돈다(`link_figures.py --pilot … --execute --no-wait` 재실행) → panels 100장 (104 §5)
  - [ ] **Phase 1 게이트** — 파일럿 **100편**(연도·길이 섞음, 097 §5-1 — PDF 108개·도판 3,750) Text 탭 도판 목록을 사람이 보고 맞다 → 그다음 Phase 2(서버 `/pdfs`·`/figures/link`)
  - **결정 반영(2026-09-14)**: 구독 CLI(ocrserver 호스트 워커) · 패널 분할은 Astra만 · 요청 단위(일괄 처리 중이면 끝까지,
    아니면 논문·폴더·전체 우클릭 "Process Figures") · 서버 PDF는 먼저 존재 확인 후 없으면 업로드 · Batches API는 해당 없음
  - ocrserver에 넘길 명세는 P16 §6에 따로 정리돼 있다

### 즉시 착수 가능 (Phase 4 hookup)
- [ ] **`extracted` 잔존분 재시도** — 실측 **10편**(2026-07-29). LLM은 끝났는데 apply를 못 하고 멈춘 것들. 해당 폴더를 다시 Process 한 번 돌리면 정리된다
- [ ] **모드 라벨 status bar 영구 표시 여부 결정** — 지금은 Process 시작 시 한 번만 출력. 항상 표시 vs 공간 절약 트레이드오프
- [ ] **앱 Process 창의 `/api/stats` 주기적 재조회** — 이제 실제 사유가 생겼다.
  클라이언트가 붙고 떨어질 때마다 몫이 12↔6으로 움직이는데, `run()`이 **배치 시작 때 한 번만**
  읽고 `_run_wrapper_pipeline(min_queued_pages=…)`에 고정값으로 넘긴다. 강제는 서버가 하므로
  틀려도 깨지진 않고 **낭비만 된다** — 높으면 서버 대기열에 쌓이고, 낮으면 내 몫이 논다.
  `scripts/reocr_legacy_ocr.py::follow_the_share`가 60초마다 따라가는 형태로 먼저 구현돼 있다
- [ ] **Apply Biblio Zotero write-back 추가 검증** — auto_commit 한 건이라도 Zotero 서버 version 증가 + `papermeister_meta`가 JSON에 박혀 in-place replace 되는지 확인. 다른 머신에서 같은 폴더를 받았을 때 `BiblioAlreadyApplied`로 LLM이 스킵되는 cross-machine 시나리오까지
- [ ] desktop: source/folder 단위 batch Reflect 트리거 + 결과 다이얼로그
- [ ] desktop: PaperList 상태 셀에 StatusBadge delegate (현재는 축약 pill — done/wait/err/rev. 필요 시 풀 라벨로 복원 또는 아이콘화 검토)

### 저순위 백로그
- [ ] 병렬 OCR 실 테스트 (max worker 올린 상태에서 처리 속도 확인)
- [ ] 에러 핸들링 보강 (암호화된 PDF, 파손된 파일 등)
- [ ] DB 삭제 후 복구 경로 실증 테스트 (Phase 1 잔여)
- [ ] 커버리지 끌어올리기 — 현재 floor 18%(측정 19.6%). 실패 경로가 특히 얇다
- [x] ✅ **한국어 매뉴얼 백틱 렌더링 (2026-08-15, [092](./devlog/20260815_092_Korean_Manual_Backtick_Rendering.md))** — 번역문이 MyST가 아니라 **RST 인라인 규칙으로 재파싱**되는 게 원인이라는 진단은 맞았다. 다만 이탤릭은 세 증상 중 가장 가벼운 것이었다: **백슬래시가 먹혀 `%LOCALAPPDATA%\PaleoBytes\PaperMeister`가 `%LOCALAPPDATA%PaleoBytesPaperMeister`로**(경로가 틀리게 표시), `--execute`는 `–execute`로, `**굵게**` 안에 중첩된 건 **백틱이 그대로 노출**됐다(RST는 인라인 중첩 불가). ko changelog 실측 code 6 : cite 11 : 노출 백틱 8 → 지금은 en과 같은 **code 22 : cite 0 : 노출 0**
  - ⚠️ **여기 적혀 있던 "`\\`→`\`로 줄여야 한다"는 틀린 조언이었다** — PO의 이스케이프 계층과 RST 계층을 섞어 본 것이다. PO의 `\\`는 이미 백슬래시 하나이므로 이중 백틱으로 바꾸면 그대로 맞다. 백슬래시는 **하나도 건드리지 않았다**
  - `.mo`도 같이 커밋해야 한다 — `docs.yml`은 `sphinx-build`만 돌리고 `sphinx-intl build`를 하지 않는다
  - `tests/test_manual_translations.py`가 재발을 막는다(단일 백틱 스팬 금지 + 인라인 리터럴 종료 검사). **단, ko `.po`만 본다** — `.rst` 원본에 단일 백틱을 새로 쓰면 못 잡는다

### Zotero sync 양방향성 보강
- [ ] **PaperFolder remove (컬렉션 멤버십 양방향 sync)** — 현재 `sync_zotero_items`는 `PaperFolder.get_or_create`만 호출 → add-only. 사용자가 Zotero에서 컬렉션 멤버십을 빼거나 다른 컬렉션으로 옮겨도 옛 링크가 잔존. 정책 결정 필요: "Zotero source of truth로 mirror" vs "add-only 보존". 전자라면 item의 `collections` 배열 기준으로 set-difference로 제거
- [ ] **PaperList에서 Trash 복원 UX** — Zotero에서 복원 시 다음 sync에서 자동 clear되지만, desktop 내에서 우클릭 "Restore from trash"로 즉시 Zotero PATCH(`deleted: 0`) + local clear 가능하게 할지 결정
- [ ] **PaperFile MD5 추적** — Zotero가 attachment에 대해 자체 md5를 보관. 우리는 추적 안 해서 사용자가 Zotero에서 PDF를 새 파일로 교체해도 옛 hash 기반 OCR cache를 그대로 사용. Phase 2 sync-centric 데이터 모델 개정과 함께 다루는 게 자연스러움
- [ ] **PaperFile.content_type 컬럼 추가** — 현재 mime은 attachment dict에서 일회성 `is_derived` 판정에만 쓰임. 컬럼 추가 후 sync에서 동기화하면 mimetype 변경(corner case) 추적 가능
- [ ] **itemType 캐시** — write-back에서 `ITEM_TYPE_JOURNAL_FIELD` 분기는 매번 fresh fetch로 itemType을 알아냄. 로컬에 캐시할지는 use case 더 봐야
- [ ] **OCR JSON sibling attachment title 정규화** (세션 42 메모) — 마이그레이션 script가 `data.title`을 filename과 동일하게 박았는데 Zotero 7+ 정책은 attachment title을 generic label("PDF", "EPUB" 등)로 두는 것. items list에서 긴 hash-suffixed filename이 noise. 필요 시 `scripts/rename_ocr_json.py`에 `--retitle-generic "OCR JSON"` 같은 옵션 추가해서 한 번 더 일괄 PATCH. 또는 Zotero 8의 `Tools → Manage Attachments → Normalize Attachment Titles` 활용. 지금은 의도적으로 그대로 둠. 참고: https://www.zotero.org/support/kb/attachment_title_vs_filename

---

## 결정된 사항

| 항목 | 결정 | 비고 |
|------|------|------|
| GUI | PyQt6, 3-pane | 소스/폴더 트리 \| 논문 목록 \| 상세 뷰 |
| DB | SQLite + FTS5 | `~/PaleoBytes/PaperMeister/papermeister.db` |
| ORM | Peewee 4.x | `DatabaseProxy` + `SqliteDatabase` |
| 데이터 경로 | `papermeister/paths.py` 단일 소스 | PaleoBytes 규약. 폴백 없음, 현재는 `PAPERMEISTER_DATA_DIR`로만 override |
| 데이터 위치 기본값 | **옮기지 않는다** (Documents 아님) | Modan2와 공유한 판단 — 동기화 폴더의 라이브 SQLite가 조용히 갈라지는 위험이 관례 위반보다 나쁘다. Zotero도 같은 선택(`~/Zotero`). [Modan2 P03](../Modan2/devlog/20260728_P03_data_directory_relocation_plan.md) |
| 데이터 위치 설정 가능화 | 예정 (미착수) | 기본값은 그대로 두고 원하는 사용자가 지정. 착수 시 **import 시점 바인딩**(아래 미결)과 **경로 부재 처리**가 전제 |
| 설정 | OS 설정 위치의 `PaleoBytes/PaperMeister/preferences.json` | 데이터와 **분리** — 머신 로컬 상태 + 평문 키. [R02](./devlog/20260728_R02_Config_File_Location_Convention.md) |
| 텍스트 추출 | 항상 RunPod OCR | 텍스트 레이어 유무 불문 |
| OCR 병렬 | ThreadPoolExecutor | health check → idle worker 수만큼 동시 처리 |
| OCR 응답 | `markdown` 필드 사용 | `chunks`도 raw JSON에 보존 |
| Raw OCR 보존 | `~/PaleoBytes/PaperMeister/ocr_json/{hash}.json` | 캐시 재활용 가능 |
| 메타데이터 | pypdfium2 | PDF 내장 메타데이터만 (Zotero는 API 데이터 우선). 0.1.7에서 PyMuPDF(AGPL) 대체 |
| 라이선스 | **GPL-3.0-or-later** | 배포본이 PyQt6(GPL-3.0)를 번들하므로. 소스 클론+pip는 무관. [R03](./devlog/20260813_R03_License_Audit.md) |
| PDF 접근 | `papermeister/pdfdoc.py` 단일 진입점 | 페이지 수·암호화·메타데이터·렌더 4가지가 전부. 인코딩 보정이 여기 한 곳 |
| 검색 | FTS5 BM25 | title×10, authors×5, text×1 |
| Import 흐름 | Scan → Process 분리 | ScanWorker(빠름) → ProcessWindow(OCR) |
| 처리 UI | 독립 윈도우 (ProcessWindow) | 비모달, 로그 누적, 프로그레스 바 |
| 재처리 | 기존 데이터 삭제 후 재생성 | 멱등성 보장, 캐시 있으면 OCR 스킵 |
| Zotero API | pyzotero (read+write) | user_id + api_key, Preferences에 저장 |
| Zotero PDF | 로컬 저장 안 함 | 임시 다운로드 → OCR → 삭제. NAS backup 별도 |
| Zotero 메타데이터 | API 데이터 우선 | PDF 메타데이터보다 정확 |
| Zotero key 저장 | PaperFile.zotero_key | 첨부파일 key, Folder.zotero_key는 collection key |
| Zotero 컬렉션 | 시작 시 자동 동기화 | 캐시 → API 순서, 소스 트리에 표시 |
| Zotero 아이템 | 컬렉션 클릭 시 fetch | API 1회 호출로 parent+attachment 매칭 |
| Zotero attachment sync | 모든 타입 수집 (PDF+JSON) | ingestion.py에서 파생(JSON)은 status='processed' |
| OCR JSON → Zotero | opt-in (`zotero_upload_ocr_json` pref) | OCR 후 자동 sibling upload, 기본 OFF |
| OCR 엔진 | Chandra2 유지 | glm-ocr 평가 후 탈락 (한국어 정확도 부족) |
| CLI | `cli.py` (argparse) | PyQt6 의존 없음, GUI와 동일 DB 공유 |
| 서지 추출 모델 | Haiku 4.5 (텍스트) | 세 모델 동률, Haiku가 비용 최적 |
| Vision pass 모델 | Sonnet 4.6 | CJK는 Haiku vision 부정확, Sonnet 필수 |
| 서지 추출 DB | PaperBiblio 별도 테이블 | 비파괴 원칙, source 필드로 모델/버전 구분 |
| Standalone promote | LLM biblio → Zotero parent 생성 | confidence=high만 자동, 나머지 수동 |
| Journal issue | Vision pass → document 타입 | Zotero에 journalIssue 타입 없음 |

---

## 미결 사항

- **데이터 경로 설정 가능화의 전제 두 가지** (착수 전 반드시 처리 — Modan2 P03 조사 2·위험 7의 우리 판)
  - **import 시점 바인딩**: 프로덕션 코드 20여 곳이 전부 `from .paths import DB_PATH` 형태라 값을 자기 네임스페이스에 복사해 둔다. 지금은 `PAPERMEISTER_DATA_DIR`가 프로세스 시작 전에 정해지므로 무해하지만, **런타임에 바꿀 수 있게 되는 순간 전부 stale해진다**(다시 읽는 쪽은 새 위치, 복사본을 든 쪽은 옛 위치). 상수를 접근자 함수로 바꾸는 게 선결
  - 📌 **규약은 `.guides/desktop/file-locations.md`가 원본이다** — 착수 전에 그걸 먼저 읽는다.
    §5가 "설정 가능화를 기본값 변경보다 먼저" + "경로 부재 처리를 **같은 단계에서**"를 규정하고,
    §7 체크리스트가 **`<APP>_CONFIG_DIR`/`<APP>_DATA_DIR` 두 개의 독립 override**와
    **경로를 import가 아니라 호출마다 해석**을 요구한다(우리가 선결 조건으로 꼽은 바로 그 둘).
    구현 예시가 필요하면 `../CTHarvester/utils/paths.py`가 그 체크리스트를 가장 충실히 따른 사례다 —
    다만 **가이드가 상위이고 옆 리포는 참고**다(사본이 아니라 원본을 본다는 087의 논지 그대로)
  - ~~**설정된 경로가 사라졌을 때**~~ ✅ (2026-07-29) — `check_configured_data_dir()`가 `PAPERMEISTER_DATA_DIR`의 **부모**가 없으면 시작을 거부한다(CLI는 stderr+exit 1, desktop은 QMessageBox). 부모를 보는 이유는 새 위치를 처음 지정하는 것과 드라이브 미연결을 구분하기 위해서. 기본값 경로는 검사 대상이 아니다 — 그건 우리가 만들 자리고, 사용자가 지정한 자리는 사용자가 제공할 자리다. **UI를 붙일 때 같은 함수를 재사용하면 된다**
- **`ocr_json/` 1.8GB(9,832개)에 백업이 없다** — 오프사이트 백업은 DB만 대상이다. Zotero sibling 업로드(`zotero_upload_ocr_json`)가 켜져 있는 만큼만 부분적으로 사본이 있다. OCR 비용 전체가 여기 들어 있으므로 재생성이 가장 비싼 자산
- 컬렉션-수준 메타데이터 (issue 모음 마킹 등)
- **systematic** Zotero → DB pull sync (현재는 on-demand: `resync_zotero.py`는 destructive, 타겟 in-place refresh는 수동 one-off)

---

## 운영 규칙 (세션 8~10에서 발견된 것)

### biblio 추출 후 반드시 non-dry reflect 한 번
`extract_biblio.py`가 새 PaperBiblio row를 만들어도, `reflect_biblio.py --dry-run`은 `status` 필드를 persist하지 않는다. **Library 트리의 "Needs Review" 폴더가 비어 보이면** 이 스텝이 빠진 것. Phase D 워크플로우는 `extract → real reflect → UI 확인` 순서로 구성.

### Zotero-sourced Paper는 local 직접 쓰기 금지
P08 §3.5 원칙. `biblio_reflect.apply()`가 자동으로 분기하지만, 혹시 별도 스크립트에서 Zotero-sourced Paper를 로컬에서 직접 건드리면 드리프트가 생긴다. `resync_zotero.py`가 destructive라 PaperBiblio 손실 위험도 있음. 타겟 in-place refresh가 필요하면 `client._zot.item(key)` → `_parse_item_metadata` 조합 사용.

### `resync_zotero.py`는 위험
`Paper`를 drop하면 `PaperBiblio`가 cascade 삭제됨. 오늘 날까지 추출한 모든 PaperBiblio가 사라진다. 전면 재동기화가 필요하면 먼저 PaperBiblio 테이블 백업, 또는 Zotero에서만 일부 item을 refresh하는 타겟 스크립트 작성.

### preferences.json을 세션에 노출하지 않기
평문 API 키가 들어있다. `cat preferences.json` 직접 실행 금지. 존재 확인은 `get_pref('key', '')` 의 boolean만 활용.

### 세션 마무리 checklist
- HANDOFF.md "다음 할 일" / "현재 단계" 갱신
- P07 매트릭스에 오늘 바뀐 항목 반영 (세션 10에서 이걸 놓쳐서 stale했음)
- devlog NNN 작성 (결정 과정과 근거 위주, 단순 diff는 git이 기록)
- **push 후 CI 결과 확인** — red면 그 위에 다음 커밋을 쌓지 않는다. 7/28~29에 `test.yml`이 6런 연속 red였는데 릴리스 태그가 실패하고서야 발견했다(릴리스를 안 컷하는 동안은 아무도 안 본다)
- git commit + push (commit 분리는 논리 단위로)

---

## 최근 세션 요약

**2026-08-13 (세션 55, 이어서)** — 라이선스 감사 → **v0.1.6 · v0.1.7 릴리스** — [R03](./devlog/20260813_R03_License_Audit.md)
- **About 탭에 버전·라이선스를 넣으려다 LICENSE 파일이 아예 없다는 걸 발견.** 의존성이 스스로 선언한 값을 읽어보니
  copyleft는 **PyQt6(GPL-3.0)** 와 **PyMuPDF(AGPL-3.0)** 둘뿐이고, 배포 설치본이 둘 다 번들하므로 결합저작물은 **AGPL-3.0**이었다
  - **경계**: 저장소 clone + `pip install`은 copyleft 라이브러리를 배포하지 않으므로 무관. **PyInstaller 번들만** 해당
  - Modan2 대조: PyQt5만 있고 PyMuPDF가 없어 **GPL-3.0**. MIT LICENSE는 *소스 기준으론 정확*하고, 빠진 건 "배포 바이너리는 GPL-3.0" 한 줄 (별건으로 남김)
- ✅ **v0.1.6** — 라이선스 명시(AGPL-3.0) + About 탭(버전·라이선스·서드파티 7종) + 앞선 references 작업 일체
  - `LICENSE`는 gnu.org 정본. ⚠️ **옆에 있는 걸 복사하면 안 된다** — PyMuPDF의 `COPYING`은 빈 파일이고 PyQt6가 실은 674줄은 **GPL**이다.
    GPL과 AGPL은 §13에서만 갈려 눈으로는 구분이 안 되므로, 테스트가 양방향으로 검사한다
  - `papermeister/about.py` + `tests/test_about.py` — 표의 라이선스가 **설치된 배포판의 자기 선언과 맞는지** 검사하고,
    `requirements.txt`의 모든 런타임 의존성이 표에 있어야 통과한다 → **새 copyleft가 조용히 들어와 배포 라이선스를 바꾸는 일을 차단**
- ✅ **v0.1.7 — PyMuPDF → pypdfium2 교체로 AGPL 탈출** (배포본 **GPL-3.0**, Modan2와 같은 등급)
  - **교체 전에 실측**: 페이지 수·암호화 판정 전건 일치 / 두 엔진 렌더를 같은 OCR 모델에 넣어 **문자 유사도 0.9991** /
    대조군(같은 이미지 2회 OCR)이 **바이트 동일**이므로 잔차는 렌더러 기인
  - ⚠️ **raw 비교는 1/8 일치로 보였는데 대부분이 Chandra 출력의 bbox 좌표였다** — 래스터가 1픽셀 다르면 좌표가 달라진다. 본문만 보면 4/8 완전일치
  - 손이 더 간 곳 둘: **메타데이터 인코딩**(pypdfium2가 UTF-8을 바이트 단위로 디코드 → latin-1↔UTF-8 왕복으로 복원, 300편 중 1편) /
    **PDF 탭 QImage**(PDFium 기본이 BGRA → 명시적 RGB 요청 + 버퍼 소멸 전 copy). Science 로고가 빨갛게 나오는 것으로 확인
  - `papermeister/pdfdoc.py`가 **PDF 접근의 유일한 진입점**(4가지). 이렇게 모여 있어서 교체가 가능했다
  - **덤**: 번들이 20~32% 작아졌다 (설치본 51→40MB, AppImage 107→86MB)

**2026-08-13 (세션 55)** — 의존성·CI 복구 + references 큐 위생 + desktop 병렬화 — [089](./devlog/20260813_089_Desktop_Parallel_References.md) · [090](./devlog/20260813_090_Dependency_Sweep_And_CI_Red_Fortnight.md) · [091](./devlog/20260813_091_References_Queue_Hygiene.md)
- **Dependabot 5건 정리** (열린 PR 0건). 081 관례대로 각 버전을 설치해 우리 API 면을 훑는 probe로 검증 — 전부 baseline과 동일
  - 🔴 **peewee 4.3.0은 단독 머지가 불가능했다** — 자기참조 FK(`'self'`) 오버로드가 고쳐져 `models.py`의 `type: ignore`가 unused가 되고 mypy가 깨진다.
    Dependabot은 requirements만 건드리므로 그 PR을 머지했으면 main이 red. 4건을 코드 수정과 함께 직접 커밋 → Dependabot 자동 close
  - pyzotero는 PR의 1.13.4가 아니라 **lock이 잡은 1.13.5**로 검증·반영 / codeql-action 패치 핀은 **거절**(리포의 액션 12개가 전부 floating major) + `dependabot.yml`에 ignore
  - PyMuPDF 1.28.2가 `import fitz`에 deprecation 경고 → `import pymupdf`로 rename(9곳)
- 🔴 **CI가 7/29 이후 2주 동안 red였다** — `pip-audit`→`pip-api`가 pip를 lock에 핀해서 Windows `pip.exe`가 자기 자신을 못 바꾸는 문제.
  **Linux green + push 없음 + 스케줄 잡 green** 3중으로 가려졌다. `python -m pip`로 수정, 이제 전부 green
- **desktop references를 논문 단위 병렬로** (`refs_workers`, 기본 4) — CLI `--workers`는 2026-06-25(`05c79d6`)부터 있었고
  커밋에 "Desktop stays serial for now"라고 적혀 있었다. **느렸던 진짜 이유는 추출을 desktop에서 돌렸기 때문**
  - 핵심은 **DB를 워커 스레드 밖으로** 뺀 것(저장·resolve·인덱스 → 메인 스레드). 직렬일 땐 무해했지만 동시엔 peewee thread-local·SQLite 단일 writer·인덱스 race가 전부 걸린다
  - `_refs_batcher` 전역 싱글턴은 **안 건드렸다** — `05c79d6`이 4스레드로 이미 검증("benign int races")
- 🔴 **처리량이 직렬보다 나쁘게 나왔는데, 사용자 지적("문제 있는 문서들이라 그런 건 아닐까?")이 맞았다** — 표본 오염이었다.
  PARTIAL율이 **재시작 전 1.0%(2,873편) vs 후 40%(10편)**. `_refs_targets`가 `paper.desc()`로 훑고 PARTIAL은 checked를 안 찍으므로
  **7월부터 실패해온 논문이 매 배치 선두에 재등장**한다(076이 진단만 하고 남긴 구조). 동시성 판단은 철회 — **다음 세션에서 다시 측정**
  - 편향을 이기고 살아남은 신호: **timeout 직렬 0건 → 동시 2건.** 089 벤치마크가 장난감 프롬프트(684토큰)라 이걸 놓쳤다
- ✅ **give-up 카운터** (HANDOFF 장기 미해결 항목) — `references_attempts`, 3회면 일반 실행에서 제외, **성공 시 0으로 리셋**(없으면 라이브러리가 서서히 전부 은퇴)
  - `scripts/seed_refs_attempts.py`로 기존 문제 논문 소급 처리. 대상은 **unchecked인데 Reference 행이 있는 논문**으로 DB에서 도출(로그 파싱·추측 없음)
  - 라이브 실행 **47편 은퇴** → 정체는 **Treatise 합본·化石 합본·단행본**(079 §e가 보류한 부류). 남은 정상 대상 1,916편
- **진행바를 논문마다 한 줄로** — 병렬화 직후엔 `Parsing 4 papers…`만 나와 직렬 때보다 정보가 줄었다. 답은 바를 없애는 게 아니라 논문마다 두는 것
- ✅ **세션 말 실측(큐 정리 후 19분)**: **44.9 refs/min = 직렬 2.88배**, 67편/시간, 130초 초과 1.2%, **WARNING 0건**.
  오전의 timeout 2건은 재현되지 않음 → **동시성이 아니라 합본의 거대 입력이 원인이었다.** 남은 1,846편 ETA 약 1.5일

**2026-07-29 (세션 54)** — references 서버 장애를 화면에 노출 — [devlog 088](./devlog/20260729_088_Refs_Server_Outage_Visible_In_UI.md)
- **502가 나면 났다고 보여준다**(사용자 요청). 083의 "재시도 말고 복구를 기다린다"는 옳았지만 **그 대기가 화면에
  전혀 안 나왔다** — 논문이 안 끝났으니 `record()`도, 배치가 멈춘 게 아니니 `mark_paused()`도 안 불려서
  최대 900초 동안 `Parsing: <title>` 그대로였다. **멈춤과 대기가 구분 불가.**
  `extract_references_llm(on_notice=…)` → `BackgroundTask.notice` → References 창 + status bar로 배선.
  복구 후 라벨을 원래 `Parsing: …`로 되돌리고, 대기 중에는 진행바를 전진시키지 않는다(끝날 때 이중 계산 방지)
- **덤**: `on_progress`가 있는데 desktop이 안 넘겨서 **논문 내 진행바가 한 번도 뜬 적이 없었다** — 같이 물렸다
- biblio 경로는 이미 502가 `failed: …`로 보인다. 조용한 건 references의 인-페이퍼 대기뿐이었다

**2026-07-29 (세션 53)** — 상태 점검 + 백업 경로 드리프트 + 데이터 위치 가드 — [devlog 086](./devlog/20260729_086_Backup_Path_Drift_And_Data_Dir_Guard.md)
- 🔴 **오프사이트 DB 백업이 7/28 이후 죽어 있었다** (`a071ef0`) — `backup-papermeister.ps1`이 옛 `~/.papermeister`를 가리킨 채였다.
  084가 23개 파일의 하드코딩을 `paths.py`로 모을 때 **파이썬이 아닌 이 스크립트가 빠졌다.** Task Scheduler 실패는 보이지 않는다.
  서버 보존 정리가 scp 성공 뒤에만 도는 덕에 기존 백업은 무사. 이제 경로를 `paths.py`에 물어본다
- **데이터 위치 설정 가능화** — Modan2 P03 대조 후 **전체는 references 완주 후로 미루고**(리팩터 값이 오늘은 0, 무인 배치와의 결합이 나쁨),
  이미 열려 있던 위험 7만 막았다 (`9885011`, `check_configured_data_dir()`)
- **라이브 실측**(WSL read-only, `?mode=ro&immutable=1`): references `references_checked` **4,248/9,891편(43%)**,
  `Reference` 199,719행(held 36,218), `CitedWork` 108,075노드. OCR은 사실상 완료(processed 19,894 / pending 3 / **failed 0** / skipped 110).
  오늘 로그 10시간 기준 **161편 처리, PARTIAL 1건, `empty_result`/`no_array` 0건** — 075~079의 가드가 오탐 없이 조용하다.
  처리율 ~16편/시간이라 남은 5,643편은 **약 2주**
- **미검증으로 남아 있던 두 항목 해소**: peewee 4 → 라이브 DB(2.5GB)에서 앱이 정상 기동했으므로 `_migrate()` 통과 /
  pyzotero 1.13 → `logs/zotero_sync.log` 7/28 14:31 풀 sync가 컬렉션 548개, 에러 0으로 완료
- ⚠️ **설정 위치 분리(`516b5b5`) 코드는 라이브에서 아직 한 번도 안 돌았다** — `%LOCALAPPDATA%\PaleoBytes\PaperMeister\`가
  아직 없고 `preferences.json`은 데이터 디렉터리에 그대로다. 실행 중인 빌드가 그 커밋보다 앞선다.
  **다음 앱 재시작 때 `migrate_legacy_config()`가 복사해 간다**(원본은 남긴다) — 그때 새 경로가 생겼는지 확인할 것
- ✅ **v0.1.5 릴리스** — 자산 5종(설치본·portable zip·AppImage·dmg·SHA256), 3플랫폼 스모크 통과, `build262`.
  **배포된 ko 매뉴얼에서 0.1.5 섹션이 한국어로 나오는 것까지 확인**했다(085에서 놓쳤던 지점)
- 🔴 **CI가 `516b5b5` 이후 6런 연속 red였는데 하루 동안 몰랐다** — 릴리스 태그가 실패하고서야 발견.
  원인은 `test_config_location.py`의 격리 실패: **Windows에서 platformdirs는 ctypes(`SHGetFolderPath`)로 해석해
  어떤 환경변수로도 리다이렉트되지 않는다.** `XDG_CONFIG_HOME` 고정은 Linux만 격리했고, Windows CI는
  러너의 **실제 `%LOCALAPPDATA%`를 읽고 썼다** → 테스트가 순서 의존이 됨(한 테스트가 남긴 설정을 다음이 주워 읽음).
  Linux에선 완전히 안 보였다. 수정(`702774c`)은 환경변수가 아니라 **resolver 자체를 패치** + 격리 유지 검사 테스트 추가
  - **형제 리포는 둘 다 면역**이고 방식이 다르다 — Modan2는 해석된 상수(`DEFAULT_CONFIG_PATH`)를 통째로 monkeypatch하고
    위치 검증은 읽기 전용 단언이라 아무것도 안 쓴다 / CTHarvester는 **제품에 `CTHARVESTER_CONFIG_DIR` override**가 있어
    테스트가 문서화된 경로로 지정한다. **OS 해석과 싸우려 든 건 우리뿐이었다**
- **공통 가이드 대조** (`70be780`) — `.guides/desktop/file-locations.md`와 우리 상태를 맞춰봤다.
  **정면으로 어긋나는 건 없었다**(설정 분리·platformdirs·벤더 세그먼트·로그 위치·마이그레이션 비대칭·
  기본값 유지+백업·WAL 단서·인스톨러 신원 4종 전부 준수). 미준수분은 **TODOs.md의 전용 섹션**으로.
  HANDOFF의 참조 구현 포인터도 옆 리포가 아니라 **가이드 원본을 먼저** 가리키도록 고쳤다(087의 논지)
- ✅ **`PAPERMEISTER_CONFIG_DIR` 도입** (`2881c31`) — 위 대조에서 나온 것 중 하나만 먼저 처리했다.
  가이드 §7이 두 override를 요구한 근거가 *"테스트가 개발자의 실제 파일에서 벗어나는 방법"* 인데,
  **그게 오늘 CI를 하루 red로 만든 그 버그였다.** 아침 수정은 테스트 쪽 우회였고 이게 제품 쪽 정답.
  도입하자마자 **패치된 값을 측정하던 단언 2개**(분리 검증·벤더 세그먼트)가 드러나 함께 고쳤다.
  검증: Windows CI green + **전체 테스트 실행이 실제 `~/.config/…`를 더 이상 만들지 않는다**
- **HANDOFF 정리**: 749줄 → 약 300줄. 세션 1~49 요약(355줄)은 devlog 001~068이 연속으로 덮으므로 이정표 표로 대체,
  완료된 ✅/[x] 항목·shipped 기능의 구현 서사 제거, `~/.papermeister` 잔재 경로를 현재 경로로 수정.
  실측으로 갱신한 것: `extracted` 잔존 48편 → **10편**, `failed` → **0편**, **needs_review 5,229편**(가장 큰 실제 백로그)

**2026-07-28 (세션 52, 마무리 2)** — **v0.1.3 / v0.1.4 릴리스** — [devlog 083](./devlog/20260728_083_Container_Restart_Recovery_Wait.md) · [devlog 084](./devlog/20260728_084_PaleoBytes_Paths_And_Installer.md)
- **v0.1.3** — 컨테이너 재기동 대기(083). 502는 컨테이너가 죽었다 뜨는 것이라 분 단위인데 재시도는 20초 → **성공률 0%**(72/24 = 3:1로 전건 소진). 게이트웨이 계열은 in-place 재시도 빼고 **healthz 폴링 후 같은 배치 재개**로 전환 → **논문의 기파싱분 보존**. `ServerGuard` 로깅 추가(무인 실행 시 pause/복구 소요가 기록에 안 남던 문제)
- **v0.1.4** — PaleoBytes 정렬(084). 데이터 `~/PaleoBytes/PaperMeister`(`paths.py` 단일 소스, 이전엔 23개 파일 하드코딩) + 설치본 `AppId`·`AppPublisher`·`%LOCALAPPDATA%\Programs\PaleoBytes\PaperMeister`·시작메뉴 PaleoBytes 그룹. **레거시 폴백은 사용자 판단으로 제거**(쓰던 사람 없음) — 경로는 조건 없는 상수, 대신 레거시 잔존 시 **경고만** 출력
- 세 릴리스 모두 **3플랫폼 스모크 통과 + 자산 5종**(zip·설치본·AppImage·dmg·SHA256). 릴리스 노트는 CHANGELOG 자동 추출
- ⚠️ **v0.1.4는 설치본 신원(AppId)이 바뀐 첫 릴리스** — v0.1.2/0.1.3 설치본은 별개 프로그램으로 잡히므로 제어판에서 수동 제거 필요(일회성)

**2026-07-28 (세션 52, 마무리)** — **v0.1.2 릴리스 + 매뉴얼 배포** — [devlog 082](./devlog/20260728_082_Release_Smoke_Test_And_Installer_Fix.md)
- **v0.1.2 발행 완료** — 절차대로(CHANGELOG 섹션 → `version.py` 범프 → 태그 push). `test_version_consistency`가 "CHANGELOG에 해당 버전 섹션 없으면 실패"라 순서를 강제함. 자산 4개+SHA256, 릴리스 노트는 CHANGELOG에서 자동 추출. 빌드번호는 커밋수(`build238`)
- 🔴 **1차 발행에서 구멍 2개 발견 → 수정 후 재발행**:
  - **설치본이 빌드되고도 첨부 안 됨** — `installer/Output/*.exe`로 업로드해 그 경로가 아티팩트에 보존됨 → `release-files/**/*.exe`가 **4단계 깊이에 못 닿음**(zip·AppImage는 2단계라 걸림). **v0.1.1도 같은 상태였음**(설치본 도입 이래 계속 누락). 업로드 전 zip 옆으로 이동해 같은 깊이로
  - **릴리스 파일을 한 번도 실행해보지 않았음** — 형제 리포는 빌드 직후 프로즌 실행 파일을 `--self-test`로 띄우는데 우리에겐 없었음. **프로즌 실행 파일은 자기 번들의 Python·라이브러리를 쓰므로 소스 테스트가 구조적으로 못 보는 부류**(빠진 `--add-data`, 번들 안 된 네이티브 라이브러리, 누락된 Qt 플러그인/SQLite 드라이버)가 있음 — **devlog 061 conda DLL 사고가 정확히 그것**("빌드 성공, 실행 시 사망")
- ✅ **`--self-test` 도입** (`desktop/app.py`): 정상 기동 경로 전부 타고 3초 뒤 exit 0. **argparse 미사용**(유일한 플래그인데 `-h`를 가져가고 Qt가 넘기는 `-platform` 등에 에러). 종료 전 top-level 위젯 close(모달 중첩 루프가 `quit()`보다 오래 살아 러너를 매다는 것 방지). 3레그 스모크 단계 — Windows `Start-Process -Wait`(windowed 앱이라 필수) / Linux `timeout 120` / **macOS는 러너에 `timeout`이 없어 앱 내부 워치독이 상한**. 패키징 *전에* 실행(깨진 번들이 AppImage/DMG로 감싸지기 전에 실패). `tests/test_self_test_flag.py` 4케이스 — **self-test가 조용히 안 걸리면 CI가 아무것도 검사하지 않으면서 통과**하므로(081 mypy와 같은 실패 방식) 양쪽 고정
  - **라이브 검증**: 3플랫폼 스모크 전부 통과, 자산 4개(설치본 **처음 첨부됨**)
  - **남은 한계**: 스모크는 "기동한다"까지만 보증. 설치본 실제 설치·기능 동작은 **사용자 수동 확인 영역**
- **문서 일괄 갱신** (`35d1063`): README(상세패널 3탭→**4탭**, Rail 버튼 누락 3개, OCR 1→3 backend, Python 3.11→**3.12**, **릴리스 존재 자체가 누락돼 있었음**, 참고문헌·개발 워크플로 추가, 로드맵 현행화) / CLAUDE.md(같은 탭 오류, P14 스크립트 5개, 매뉴얼·릴리스·CI 섹션, **mypy 함정 명문화**) / TODOs(완료분 표시 + 인프라 섹션 신설) / CHANGELOG(`[Unreleased]` 신설)
- **매뉴얼 한국어 번역 + 언어 스위처** (`53bb902`, `6e8a056`): 259개 중 **227개 번역**(나머지 32개는 경로·파일명 등 리터럴이라 원문 유지). 스위처는 Modan2 이식하되 **JS `onclick` 대신 실제 `<a href>`** — Sphinx가 `pagename`을 알고 두 언어가 형제 디렉터리라 빌드 시점에 경로가 정해짐 → 새 탭/가운데 클릭/키보드/JS-off 모두 동작. 전제: **두 언어 트리가 평평해야 함**(하위 디렉터리 생기면 `pathto()` 필요, README에 기록). 배포본에서 링크 20개 전부 실재 파일 확인
  - ⚠️ **한국어 RST 함정**: 닫는 `**` 뒤에 조사가 바로 붙으면 마크업이 통째로 사라짐 → `**강조**\ 조사` 이스케이프 공백 필요. CLAUDE.md·매뉴얼 README에 기록

**2026-07-28 (세션 52, 계속)** — **의존성 일괄 업그레이드** — [devlog 081](./devlog/20260728_081_Dependency_Upgrade_Sweep.md)
- 080에서 Dependabot을 켜자 한 시간 만에 **PR 8건**. 각 버전을 **실제로 설치해 우리가 쓰는 API 면을 훑어** 검증 후 전부 머지 (CI 그린만으론 부족 — 커버리지 19.6%이고 실패 경로는 테스트가 안 닿음)
- 🔴 **pyzotero 1.5→1.13은 코드 수정 필요** (`c630fb3`): (1) 에러 클래스 전면 개명(`UserNotAuthorised`→`UserNotAuthorisedError`) → 옛 이름 `except`가 **진짜 에러 전파 도중 AttributeError**를 냄 (2) **requests→httpx 전환** → 연결 blip이 httpx 타입으로 와서 재시도 판정에 안 걸림. 둘 다 **실패하는 순간에만** 드러나 CI로는 안 잡힘. 수정: 이름 여러 개로 조회 + **빈 튜플 폴백**(미래 개명 시 degrade), 재시도에 `httpx.TransportError` 추가(status 에러는 제외). **1.5.28/1.13.2 번갈아 설치해 전체 통과 확인** + `tests/test_zotero_compat.py` 6케이스
- 🟢 **peewee 3.17→4.2 안전**: 우리 API 면 전체(FTS5 원시 SQL·트리거·snippet·bm25 포함)를 두 버전에서 나란히 돌려 **출력 동일** 확인. ⚠️ **CLAUDE.md의 "Peewee 4.x"가 그동안 사실과 달랐음**(실제 3.17.9) — 이 머지로 비로소 맞음
- 🟢 **PyMuPDF 1.24→1.28 안전**(쓰는 API 6종 전부 동작, `fitz` 별칭 생존 확인) / requests·PyQt6는 **하한만 상향**(설치물 변화 0) / actions 3건은 표준 업그레이드 — 그중 `upload-artifact 4→7`과 pages 액션 2건은 **어제 내가 만든 불일치를 Dependabot이 잡아준 것**
- **운영 지식 2건**: 워크플로 파일 PR은 토큰 `workflow` 스코프 없이 **API 머지 불가**(SSH push는 제약 없음 → #2·#9·#10은 main에 직접 적용, Dependabot이 자동 close) / **lock은 머지마다 충돌**하므로 `@dependabot rebase`→승인→머지를 한 건씩 반복. `dependabot-lock-refresh`는 **첫 실전에서 정상 작동**(#4·#5 `refresh-locks` 통과)
- ⚠️ **드러난 것 — mypy 게이트가 보이는 것보다 약함**: lint 잡이 `ruff mypy`만 설치하고 **프로젝트 의존성을 안 깔아서** peewee를 `Any`로 처리 중. peewee 4는 타입 주석이 있는데 **암묵적 `id`/`<fk>_id`를 모델링 안 해** 로컬에선 오탐 28건(테스트 117개는 통과 = 실제 버그 아님). **같은 세션에서 해결** (081 갱신): 28건 전수 분류 → 26건은 peewee가 *생성하는* `id`/`<fk>_id` 미선언(→ `TYPE_CHECKING` 선언), 1건은 자기참조 FK 오버로드(→ 좁은 ignore), **2건은 우리 코드의 이종 dict 느슨함**(→ `TypedDict`). **`id`는 `int`가 아니라 `peewee.AutoField`로 선언해야 함** — 필드가 디스크립터라 클래스=쿼리표현식/인스턴스=값. **`x_id` 대신 `x`를 쓰는 건 금지**(mypy는 통과하지만 행마다 관계 fetch = N+1). CI는 lint에 **의존성 설치 + mypy 버전 핀**(Modan2 관례) 추가 → 게이트가 표방하는 일을 실제로 함. 검증: 수정 전 코드는 28건 검출, 수정 후 0건
- **배포 후 확인 필요**(테스트 미도달 영역): peewee 4 → 라이브 DB `_migrate()` 경로 / pyzotero 1.13 → 실제 Zotero API 왕복(`logs/zotero_sync.log`)
- 소소한 UX 변경 (devlog 없음, 커밋 메시지에 근거 기록): **SourceNav 탭 유지**(`a7020cd` — `refresh()`가 `tabs.clear()`로 선택을 잃어 동기화·Apply 후 첫 탭으로 튀던 것. **인덱스가 아니라 소스 신원으로 복원** — refresh 이유 자체가 소스 목록 변화라 인덱스 복원은 다른 소스로 착지 가능) / **진행창 로그에 날짜**(`465e0bc`) / **`biblio_YYYYMMDD.log` 자정 롤오버**(`971109d` — 핸들러가 import 때 한 번 생성되는데 배치가 며칠씩 도므로 파일명 고정 시 전부 시작일에 쌓임 → 레코드마다 날짜 확인)

**2026-07-27 (세션 52, 이어서)** — **Modan2/CTHarvester 프로세스 정렬** — [devlog 080](./devlog/20260727_080_CI_Docs_Parity_With_Sibling_Repos.md)
- 사용자 요청: 두 형제 리포의 테스트·CI·릴리스 프로세스를 충실히 따를 것 + 매뉴얼도 만들 것. 073에서 한 번 맞춘 뒤 벌어진 **격차 차분** 작업
- **CI 추가** (`bdcd3d2`): `dependabot.yml`(pip+actions 주간) / `dependabot-lock-refresh.yml`(requirements 변경 PR에서 lock 자동 재생성 → lock-check 통과) / `manual-release.yml`(workflow_dispatch 릴리스, 프리릴리스·재컷용, 커밋수 build number 일관) / **커버리지 최초 측정 19.6% + floor 18% ratchet**(Linux leg, `papermeister`+`desktop` 스코프, coverage.xml 아티팩트) / C901 복잡도 리포트(비게이팅)
  - **P15 판단 뒤집음**: Dependabot을 "1인 도구 과잉"으로 뺐었는데, 오늘 그 부재로 pytz lock 드리프트가 CI를 red로 만듦(074) → 채택. Modan2와 달리 우리는 `--universal` lock 2개라 워크플로 조정
  - **미채택(근거 기록)**: `test-full.yml`(전체 111개가 2초라 분리할 느린 테스트 없음, 주간 스케줄은 security/codeql이 이미 담당) / `ruff format --check`(대량 format 커밋 선행 필요, P15부터 보류 중)
- **Sphinx 매뉴얼 + Pages 배포** (`6a0989e`): `docs/manual/`(index/installation/quick_start/user_guide/faq/troubleshooting/developer_guide/changelog) + `docs.yml`(en/ko 빌드 → Pages). **내용은 새로 작성** — troubleshooting은 이 프로젝트가 실제 겪은 장애(502/500 크래시 루프, PARTIAL 사유 읽기, Zotero 403/400, conda DLL, WSL 라이브 DB 인덱스 손상)로 구성. `conf.py`가 `version.py`에서 버전 읽음 + `changelog.rst`가 루트 CHANGELOG.md include → **둘 다 single-source**. 한국어는 sphinx-intl 스캐폴딩(미번역 시 영어 폴백이라 ko 빌드도 완전), en/ko 로컬 빌드 확인
  - **후속**: ko `.po` 번역 / **GitHub 저장소 설정에서 Pages source를 "GitHub Actions"로 지정 필요**(안 하면 첫 배포 실패) / `LOCK_REFRESH_TOKEN` 시크릿(선택)

**2026-07-27 (세션 52)** — 상태 점검 + CI 그린 복구 — [devlog 074](./devlog/20260727_074_Lock_Check_Pin_Preference_Fix.md)
- 상태 점검: main clean, `pytest` 81 passed, v0.1.1 릴리스 완료. **본체로 남은 건 references 추출 완주** (마지막 실측 1,733/9,889편, 17.5%). 라이브 DB는 오늘도 쓰이는 중 — WSL에서 read-only 조회는 WAL/NTFS로 `disk I/O error`라 현재 수치 미확인, Windows에서 `scripts/refs_progress.py`로 볼 것
- **`make lock-check`가 upstream 릴리스마다 red 되던 문제 수정**: `lock`은 기존 lock 파일을 핀 선호로 읽는데 `lock-check`는 빈 temp에 컴파일해 전부 fresh 해석 → pytz가 7/25에 2026.3.post1을 내자 소스 변경 0인데 실패. temp를 커밋된 lock으로 seed해 양쪽 해석 조건을 일치시킴 + 의도적 업그레이드용 `make lock-upgrade` 분리. **lock 파일 자체는 stale하지 않아 손대지 않음**. 검증: lock-check 통과 + `tabulate` 임시 추가 시 정상 실패(게이트 살아있음)
- **Qwen 5xx(엔진 재시작)에 짧은 재시도 추가** — [devlog 075](./devlog/20260727_075_Qwen_5xx_Transient_Retry.md). 추출 중 `500 EngineCore encountered an issue` → `502 upstream: All connection attempts failed` 반복 보고. **502는 증상, 진범은 vLLM 엔진 워커 크래시**(OOM 유력, 확정은 서버 로그). `_call_qwen`이 5xx를 `HTTPError`로 그냥 올려보내 논문 하나가 통째로 실패하던 것을 **5xx 전용 예산**(`server_retries=2`, backoff 5s→15s)으로 흡수. 타임아웃 예산과 분리 — 타임아웃은 "배치를 줄여라", 5xx는 "같은 배치를 기다렸다 다시"라 대응이 정반대. **지속 장애는 그대로 raise**(ServerGuard가 pause해야 하므로 — `complete=False`+record_ok로 바꾸면 스트릭이 리셋돼 죽은 서버로 남은 편수를 헛돌게 됨). `tests/test_qwen_retry.py` 6케이스, 87 passed
- ~~실행 중인 앱이 7/24 이전 코드~~ (로그의 `read timeout=240`이 증거) → **세션 말미에 재시작 완료** — 360초 타임아웃 + 5xx 재시도 반영됨. 서버 쪽에도 사용자가 crash 대비 조치를 넣음
- **다음에 엔진이 또 죽으면 확인할 것**: 서버 vLLM 로그의 스택 트레이스(`CUDA out of memory` / `EngineDeadError` / `illegal memory access` / Xid 중 무엇인지) + 그 시각 GPU 메모리 + OCR 동시 실행 여부. 이게 있어야 대응(배치 상한 축소 / `--gpu-memory-utilization` 조정 / refs 도는 동안 OCR 모드 분리)을 고를 수 있음. 우리 쪽 5xx 재시도는 크래시가 논문 실패로 번지는 것만 막을 뿐 크래시 자체는 못 막음
- references 진행률 실측(7/27 12:17 사용자 로그): 배치 **2,188/8,036**, 편당 평균 250초(레퍼런스 1건당 ~4.3초), 표본상 PARTIAL 약 18%
- **PARTIAL 원인 진단** — [devlog 076](./devlog/20260727_076_References_Partial_Cause_Diagnosis.md). 재시작 후 새 배치(6,027편) 첫 5편 중 4편 PARTIAL. ⚠️ **"급증"이 아님(사용자 지적)** — `_refs_targets`가 `references_checked==False`를 **`paper.desc()`** 로 훑으므로, 지난 런에서 checked를 못 받은 PARTIAL/실패분이 **다음 배치 맨 앞에 그대로 재등장**한다. 즉 앞부분은 무작위 표본이 아니라 **재시도 큐**. 배치 크기 역산(8,036−2,188=5,848 vs 새 6,027)으로 **모집단 PARTIAL+실패 ≈ 8~9%**가 11편 표본의 18%보다 신뢰할 만한 추정. 구조적 문제: **재시도 give-up 조건이 없어** 파싱 불가 논문은 매 배치 선두에서 영원히 재시도됨. PARTIAL 발생 지점은 **A) floor에서 타임아웃(서버 무응답)** / **B) HTTP 200인데 JSON 파싱 실패(잘린 출력)** 둘뿐이고, **5xx는 원인이 아님**(075 이후 5xx는 논문 전체 failed로 감). 타임아웃은 WARNING이라 콘솔에 반드시 찍히는데 해당 시간대 `Read timed out`이 없었음(사용자 확인) → **B로 판정**
  - ⚠️ **desktop 앱은 `biblio` 로거에 핸들러/레벨을 안 붙임** — `basicConfig`는 CLI 스크립트에만 있음. 그래서 배치별 사유(`bad JSON for batch N (…)`)가 INFO라 **전부 폐기**되고 WARNING/ERROR만 lastResort로 stderr에 나옴. 파일 로그가 있는 건 `ocr` 로거뿐(`logs/ocr.log`)
  - 가설(미확정, **근거 약화됨**): 생성 도중 vLLM 엔진이 죽으면 프록시가 **부분 응답을 200으로** 반환 → 잘린 JSON = B. 단 위 정정으로 "급증"이라는 설명할 현상 자체가 사라져, 서버 동작 변화보다 **그 논문들 고유 성질**(레퍼런스 블록 구조/언어/OCR 품질 — 목록에 독일어 대문자 제목, 합자 섞인 제목 등)이 더 유력. `max_tokens` 산식상 단순 토큰 초과로도 설명이 약함
  - ✅ **후속 구현 완료** — [devlog 077](./devlog/20260727_077_Biblio_Log_And_Partial_Attribution.md): (a) `biblio` 로거에 `ocr.py`와 같은 파일 핸들러(`~/.papermeister/logs/biblio.log`, DEBUG, 즉시 flush) (b) `extract_references_llm` 반환 4-tuple → **5-tuple**(`skipped={'timeout','bad_json','refs_lost'}`), 호출자 2곳(desktop 워커·`scripts/extract_references.py`) 갱신, `describe_skips()` 헬퍼 → 진행창이 `34 refs PARTIAL (bad JSON x2, 17 refs lost)`로 표시 (c) 파싱 실패 시 **응답 본문 head/tail 400자 + max_tokens를 DEBUG로 기록** — 잘린 응답인지 딴소리인지 구분용 (d) 두 스킵 로그 INFO→WARNING. `tests/test_refs_partial_reporting.py` 5케이스, **92 passed**
  - **재현 절차 불필요**: PARTIAL 논문이 다음 배치 선두에 다시 오므로, 로그 켠 채 다음 배치를 돌리면 바로 원인 확정됨. 데이터 유실은 없으나(unchecked로 남아 재파싱) 버려진 배치만큼 재작업이 쌓이는 중
  - ✅ **레퍼런스 없는 문서의 영구 PARTIAL 루프 수정**(077 §4): `0 refs PARTIAL` 관측(`SVP-Letter-to-Editors` 등, **88초/243초로 끝나 타임아웃일 수 없음**) → 원인은 **레퍼런스가 애초에 없는 문서**. 헤딩 미검출 → 마지막 2p fallback(산문) → 프롬프트에 "없으면 `[]`" 지시가 없어 모델이 산문 응답 → 파싱 실패 → PARTIAL → checked 안 찍혀 **매 배치 선두에 영구 재등장**(서버가 건강해도 영원히 수렴 안 함). 수정: (1) 프롬프트에 "참고문헌 없으면 빈 배열, 산문 금지" (2) `no_array`(배열 부재) vs `bad_json`(배열 절단) **분리 집계** — `JSONDecodeError`가 `ValueError` 서브클래스라 `isinstance`로 명시 판별 (3) **fallback(low) + 배열부재 + 파싱 0 + 타임아웃/절단 없음** 네 조건 모두 만족 시 `complete=True`(checked-empty). high-confidence 블록·부분 파싱·타임아웃은 전부 PARTIAL 유지(보수적)
  - ✅ **토큰 예산 보정 + 절단 에스컬레이션** — [devlog 078](./devlog/20260727_078_Refs_Token_Budget_And_Truncation_Escalation.md). 077 반영 후 첫 PARTIAL(`bad JSON x1, 3 refs lost`)의 `biblio.log`가 **절단을 확정**(파싱 사망 위치=본문 맨 끝 char 6544, tail이 값 중간에서 끊김, `max_tokens=2322`). 실측: 2.8자/토큰, 레퍼런스당 ~107토큰 → **필요 출력 ≈ 입력문자 × 0.87**인데 산식은 `in_chars//2`(0.5배)라 **1.7배 과소**. 수정: (1) `in_chars//2` → `in_chars` (2) 절단 시 **같은 배치를 `_MT_CEILING`(8192)로 1회 재시도** (3) 그래도 안 되고 배치>1이면 **축소 후 재시도**, 엔트리 1개가 상한으로도 안 될 때만 skip. `boost_at`으로 루프 방지, 축소는 `size>MIN`일 때만이라 종료 보장. **상한 8192는 의도적으로 안 올림** — `max_tokens`가 vLLM KV 캐시 헤드룸에 들어가는데 엔진 OOM 정황(075/076)이 있어 압력을 키우지 않으려고, 추정만 정확하게 하고 상한은 실패 시 드문 재시도 경로로만. **왜 중요한가**: 배치 분할·예산이 입력에 대해 결정적이라 skip하면 재시도해도 매번 똑같이 잘려 **영구 PARTIAL**(077 §4 편지 케이스와 같은 비수렴 구조). 테스트 10케이스, **97 passed**
  - ✅ **라이브 검증**: 재기동 후 같은 DETR 논문이 `34 refs PARTIAL (3 refs lost)` → **`53 references, 6 in library`** 로 통과. **+19개** — "3 refs lost"가 실제로는 레퍼런스 19개였음(엔트리 3개 × blob당 6~7개, 절단 응답 6,544자 ≈ 22개 분량과 일치). **blob 가설 실측 확정**
  - 따라서 지표명 `refs_lost` → **`entries_lost`** 로 정정(표시도 `3 entries lost`). 엔트리 수를 세면서 "refs"라 부르면 **심각도를 6배 축소 보고**하게 됨. 실제 손실 레퍼런스 수는 파싱을 못 했으니 알 수 없으므로 아는 척하지 않는 쪽이 정직
  - 배처 거동은 건강함 확인(`1건 42.7s → 8건 62.4s` 정상 워밍업) — 이 논문의 PARTIAL은 서버 문제가 아니었음
  - 🔴 **`[]` 탈출구 회귀 발견 + 수정** — [devlog 079](./devlog/20260727_079_Empty_Array_Escape_Hatch_Regression.md). 077 §4에서 넣은 프롬프트 줄("참고문헌 없으면 `[]`")을 모델이 **CJK 서지에서 남용** → `complete=True` → `references_checked=True` → **레퍼런스 0건으로 영구 확정**(PARTIAL 무한재시도라는 *복구 가능한* 상태를 **조용한 영구 유실**로 바꿔버린 최악의 교환). 라이브 증거: 한국어 논문(엔트리 **47개**, 실제 서지 목록)이 배치당 **0.05초/엔트리**로 응답 — 같은 런 정상 속도 4.4초/엔트리 대비 물리적으로 불가능 → `[]` 확정. 영향 논문 2편(로그상 9/115 배치)
    - 수정: (1) 프롬프트에서 `[]` 조건 축소 + **OCR 잡음·낯선 언어·축약 저널명은 포기 사유 아님** 명시 (2) **코드 가드**: `high` confidence 블록(진짜 섹션을 찾음)인데 파싱 결과 0건 = 모순 → `complete=False`로 UNCHECKED 유지(`empty_result` 집계). 비대칭 근거 — 잘못 checked는 영구 유실, 잘못 unchecked는 재시도 1회. **fallback(`low`)의 `[]`는 checked-empty 유지**(편지 케이스 보존) (3) `refs: block confidence=…, N entries` 로깅 추가 (4) **복구**: `scripts/reset_references.py --scope empty-checked` — `references_checked=1`인데 Reference 0건인 논문의 플래그 해제(지울 데이터 0이라 안전, 진짜 무참고문헌은 같은 판정 재확인). 테스트 12케이스, **105 passed**
  - 🔵 **범위 결정 (2026-07-27, 사용자)**: **참고문헌 헤딩 탐지 정확도 개선은 하지 않는다** — "일반적인 학술지 논문만 잘 처리해도 오케이". 오작동 대상(코스 가이드북·도판·목차·부고·편지)이 애초에 인용 네트워크에 기여하지 않는 문서들이고, 휴리스틱을 더 쌓으면 본류 경로에 회귀 위험만 는다. 보류 항목: 목차 줄 배제(점선 리더+페이지번호), 매치 블록 최소 크기 요구, `low` 블록 추가 가드. **단 077~079의 가드는 유지** — 그건 이상 문서를 *잘 처리*하려는 게 아니라 **조용한 유실·무한 루프를 봉쇄**하는 것이고, 무한 루프는 이상 문서 하나가 매 배치 선두를 점유해 일반 논문 처리량을 갉아먹으므로 **본류를 지키는 비용**임
  - 🔵 **Treatise류(단행본·합본) — 검토 후 보류** (079 §e): fallback이 색인 페이지를 참고문헌으로 변환(`Titanocarcinus`를 저자로). **피해는 갇힘** — `canonicalize_reference`가 제목·DOI 없는 항목을 거부해 `CitedWork` 미생성, 인용 네트워크에 가짜 엣지·노드 없음, 한 번 완료되면 배치 선두도 점유 안 함. 제안했던 규칙 = **`low` + 페이지 수 >~60이면 LLM 없이 checked-empty**(fallback은 짧은 문서에서만 정당; 단 **페이지 수 단독 컷은 금지** — 100~200쪽 계통 개정판은 `high`로 잘 처리됨). 사용자 결정 "일단 그냥 두자, 어떻게 처리해도 애매" → 미구현, 필요해지면 재개. **명시적 기각**: 장별 추출(합본을 컨테이너→챕터로 쪼개는 건 "PDF 하나=Paper 하나" 전제를 갈아엎음). 방향 정리: Treatise류는 **나가는 인용보다 들어오는 인용**이 가치 있고, 그건 biblio 메타데이터 정확도의 문제
  - **미해결**: 일반적 재시도 give-up 카운터는 여전히 없음. 위 수정들이 확인된 두 원인(레퍼런스 없는 문서 / 절단)을 제거하므로 새 로그로 잔류분 규모를 본 뒤 필요성 판단
- 라이브러리 정리: `papermeister.db.corrupt-20260625` / `.pre-p13-backup` 삭제(사용자, ~9GB 회수)
- 미반영이던 **devlog 073**(lockfile + CodeQL + 버전 일치 테스트, Modan2 CI 패리티)을 HANDOFF에 편입

**2026-07-24 (세션 51)** — CI 패리티 — [devlog 073](./devlog/20260724_073_CI_Parity_Lockfiles_CodeQL_Version_Test.md)
- `requirements.lock` / `requirements-dev.lock`(uv `--universal --generate-hashes`) 도입, CI·release는 `pip install --require-hashes`로 설치 → 배포본이 CI가 테스트한 그 wheel임이 증명됨. `Makefile`의 `lock`/`lock-check` + `security.yml`의 lock-check job
- `codeql.yml`(자체 코드 data-flow SAST, push+주간+PR) 추가. ruff `S`(bandit)는 P15부터 이미 보유
- `tests/test_version_consistency.py` — `version.py` 단일 소스 일치 검증

**2026-07-23 (세션 50)** — 상태 점검 + **P14 계획/착수** (references 진행 모니터 + 인용 네트워크) — [devlog P14](./devlog/20260723_P14_Citation_Matching_And_Network.md)
- HANDOFF 상단이 세션 49(P11 "라이브 대기")에 멈춰 있어 git log(P12/P13/065~068)와 어긋남을 발견 → **Windows 라이브 DB(2.3GB)를 WSL 로컬로 복사 후 스키마·카운트 실측**으로 실제 진행 확정
- **P13 FTS 마이그레이션 적용 완료 확인**: `passage_fts` external-content + standalone `paper_fts` + 트리거 9종, `passage_fts_content` 부재, `pre-p13-backup`(4.3GB) 존재, `quick_check=ok`. DB 4.3→2.3GB
- **P11 references 부분 실행 + P12 CitedWork 정규화 라이브 확인**: `references_checked` 1,737/9,828편(17.7%), `Reference` 104,889행(held 13,123 / external 58,473), `CitedWork` 49,728노드
- **P14 계획서 커밋** (`2a0dc35`): 참조 매칭 품질(A1 증분 재-resolve / A2 감사) + 인용 네트워크(L0 통계 / L1 export / L2 ego-view / L3 공동인용). 착수 순서 L0→A2→L1→A1→(L2/L3 추출 후)
- **구현·검증·커밋 (read-only, Windows 실행 전제)**:
  - `scripts/refs_progress.py` — 추출 진행률/처리율/ETA 모니터(`--watch`)
  - `scripts/citation_stats.py` (L0, `1d01402`) — held→held 그래프 통계(3,831노드/12,038엣지 @17.6%)
  - `scripts/export_citation_graph.py` (L1, `1d01402`) — nodes/edges CSV + GEXF(Gephi), `--with-external`
  - `scripts/audit_matches.py` (A2, `8ed8591`) — 매칭 감사. **실측 발견**: title 매칭 12,925 중 4,279 의심(FP, 예: "On Growth and Form" 오연결), 제목이 보유논문과 일치하는데 미연결 4,403(FN, 예: 완전일치인데 unresolved)
- **A2 후속: `resolve_one` 스코어러 보강 완료** (`4f27773`): containment(inter/min) 단독 → **containment+Jaccard 블렌드**(짧은 제목이 긴 제목에 박혀 1.0 나던 FP 차단) + **near-exact 토큰셋 강신호**(year mismatch veto 면제, exact-title FN 회수). 오프라인 A/B(라이브 스냅샷, fresh 재-resolve 동반): held 9,339 유지 · **FP 3,225 제거** · 597 재연결 · **FN 7,697 회수**(일부는 재-resolve 효과). ⚠️ **라이브 추출은 OLD 코드 메모리 상주** — 새 스코어러는 **추출 재시작 후** 신규 논문에 적용, 기존 refs 반영엔 **재-resolve 패스(A1) 필요**
- **references 진행창 Cancel 버튼 추가** (`7734da1`, 사용자 요청): 대기 큐 비우고 진행 중 1편만 마무리(LLM 호출 중단 불가). `ReferencesWindow.cancel_requested` 시그널 + `mark_cancelling`, main_window `_ensure_refs_window`/`_cancel_refs`. `_active` 플래그로 begin() extend 오판 수정. offscreen 스모크 통과
- **서버 다운 견고성 2건** (사용자 지적):
  - **부분 파싱을 checked로 안 찍기** (`8c15cdc`): 데스크톱 워커가 `extract_references_llm`의 `complete` 플래그를 무시하고 `references_checked=True`를 무조건 찍던 버그 → 서버 죽으면 부분/빈 결과인데 done 처리돼 재파싱 영영 안 됨(조용한 데이터 유실). CLI(`extract_references.py`)처럼 `complete=True`일 때만 stamp, 부분결과는 unchecked로 남겨 재파싱(save_references delete-and-replace라 중복 없음). **적용하려면 소스(`python -m desktop`) 재시작 필요 — 옛 .exe 아님**
  - **서버 다운 시 자동 정지→일시정지+자동복구로 진화** (`f12b03c`→`bb1d7b1`→`31c6e35`→`0859040`): 연속 실패 3회 → LLM 엔드포인트 직접 핑(`biblio.references_server_alive`, max_tokens=1로 slow≠down 구분) → 죽었으면 **큐 유지한 채 Pause**, 60초마다 백그라운드 폴링 → 서버 복구 시 **자동 Resume**(무인 실행 대응). 일시적 blip이면 스트릭 리셋 후 계속. Cancel은 pause 중에도 동작. `complete=True`(파싱 or no-ref)가 스트릭 리셋해 오탐 방지
  - **공유 `ServerGuard` 추출** (`31c6e35`, `desktop/workers/server_guard.py`): streak+확인핑+복구폴링+pause/resume 콜백 상태머신. 큐는 호출자 소유, guard는 "언제 멈출지/복구됐는지"만. references 이관(behavior-preserving) + 유닛 스모크 통과
  - **biblio에도 적용** (`0859040`): BiblioWindow에 Cancel + pause/resume, `_biblio_guard`. `biblio_server_alive()`는 **qwen 백엔드만 폴링**(claude는 폴링할 서버 없어 True 반환→pause 안 함). 유효 pred=record_ok(다운스트림 apply 실패해도), 추출 err/task.failed=record_fail
  - **OCR에도 적용 완료** (`fe4e691`, `papermeister/ui/process_window.py`): ProcessWorker에 연속실패 streak + `_pause_if_server_down()` — 3연속 실패 시 `ocr.is_ready()` 확인 → 죽었으면 **워커 루프 안에서 30초 폴링하며 대기**, 복구 시 resume, Cancel 시 탈출. `_run_parallel`(pool)·`_run_wrapper_pipeline`(제출) 두 루프 모두. **`ServerGuard` 미사용** — OCR은 자체 QThread 루프라 인라인 `sleep+is_ready()`가 더 단순(메인스레드 QTimer 불필요). `is_ready()`가 백엔드별(pod/wrapper/serverless) 분기라 새 헬스프로브 불필요. 진행 메시지는 기존 progress 시그널로 ProcessWindow 로그에 표시. **"동결" ProcessWindow지만 OCR 워커는 실질 활성 유지 엔진이라 일관** (사용자 승인). 유닛 스모크 통과(no-op/blip리셋/down→resume/cancel)
- **코드 품질 인프라 도입 (P15, ../Modan2 가이드 기반)** — [R01 검토](./devlog/20260723_R01_Code_Quality_Guide_Adoption.md) · [P15 계획](./devlog/20260723_P15_Code_Quality_Adoption_Plan.md)
  - **CLAUDE.md에 `R##`(리뷰/감사) devlog 타입 추가**. R01(판단)→P15(실행계획)→999(기록) 3단 구조
  - **Phase 1 (ruff)** `7e110ca`: `pyproject.toml` curated 룰셋(base+DTZ+RUF012+S; 스타일 SIM/RET/PIE/A는 후속 패스), Qt camelCase·의도적패턴 ignore(사유 명시), 61파일 자동+수동 수정. **`ruff check` clean**, 전 모듈 import OK, **requires-python ≥3.12**
  - **Phase 2 (pytest)** `1afde45`: pytest 설정(markers unit/ui/integration) + `requirements-dev.txt` + `tests/`(conftest headless Qt) — test_references(P14 스코어러 회귀)·test_paper_service(CJK 저자)·test_server_guard·test_smoke(전 모듈 import). **72 passed**. "픽스마다 회귀 테스트" 관례 시작
  - **Phase 3 (CI + 서버 패키징·릴리스)** `c3f3f3f` — **Modan2 미러**. `.github/workflows/`: `test.yml`(ruff lint 게이트 + {ubuntu,windows}×3.12 매트릭스, import 스모크+pytest, `workflow_call` 노출), `reusable_build.yml`(Windows 전용 clean-pip PyInstaller onedir→portable zip), `build.yml`(수동 `workflow_dispatch`만—커밋 잦아서), `release.yml`(태그 `v*.*.*`→test→build→gh-release+SHA256). `version.py`(0.1.0) + build_number=commit count. **라이브 미검증**: windows-latest `pyinstaller PaperMeister.spec` 실빌드는 첫 CI가 확인(spec conda 가드로 pip-CI 표준빌드 기대). 후속: Inno Setup 설치본/아이콘/mac·Linux 레그/CHANGELOG
  - **Phase 3 라이브 검증 완료**: CI(test.yml) Linux·Windows 그린, Windows PyInstaller 빌드 그린(portable zip), 액션 버전 Node24로 최신화(`a468131`). `pythonpath=["."]` 픽스(`885adf4`)로 plain `pytest`의 import 해결 — CI가 잡은 실버그
  - **첫 릴리스 태그 `v0.1.0`** push → release.yml(test→build→공개 Release+SHA256) 트리거
  - **Phase 4 (excepthook + pre-commit)** `cc94e4a`: `desktop/app.py`에 전역 `sys.excepthook`(미처리 슬롯 예외 로깅+비치명 다이얼로그, KeyboardInterrupt는 위임) + `.pre-commit-config.yaml`(ruff --fix + 파일위생; ruff-format은 format 패스까지 보류) + excepthook 회귀 테스트. **73 passed**
  - **Phase 5 (deps 보안 + mypy 코어, vulture 제외)** `592996b`: pip-audit로 Pillow 10(CVE 다수)·requests 2.31·python-dotenv 발견 → **python-dotenv 제거**(미사용—main.py가 .env를 plain open()으로 읽음), Pillow≥12.3.0·requests≥2.33.0 버전업(pip-audit clean). `security.yml`(pip-audit push/PR/주간, Modan2 미러). mypy 설정 + **references/search/biblio 3모듈 mypy-clean → CI lint 게이트**(점진 확장). ⚠️ **사용자: Windows env에서 `pip install -r requirements.txt --upgrade` 후 OCR 이미지(Pillow) 동작 확인 필요**
  - **Phase 6 (인코딩 + 패키징 체크리스트)** `c9e5441`: 텍스트 `open()` 잔여 3곳(main.py .env, refs_progress state json)에 `encoding='utf-8'` — 이제 미명시 text open() 0건. `docs/RELEASE.md`(릴리스 런북 + 프로즌 아티팩트 스모크 체크리스트)
  - **✅ P15 전 6단계 완료**. **미실행(의도적)**: `ruff format` 대량-diff 커밋, vulture(데드코드, 사용자 제외), 엄격 coverage gate/Dependabot/코드사이닝(1인 도구 과잉)
  - **P15 후속 추가**: `scripts/verify_image.py`(OCR Pillow 경로 1-커맨드 검증 — Windows Pillow 12.3.0 PASS 확인) + **크로스플랫폼 패키징 3레그 완성** (`8cc7fd7` Inno Setup, `47b584b` Linux AppImage, `b6c563f` macOS DMG):
    - **Windows**: portable zip + Inno Setup 설치본(`installer/*.iss.template`, per-user)
    - **Linux**: AppImage(`packaging/linux/create_appimage.sh`, appimagetool `EXTRACT_AND_RUN`)
    - **macOS**: DMG(`packaging/macos/create_dmg.sh`, onedir→.app→hdiutil, **미공증**)
    - reusable_build 3 job, release가 4종(zip/exe/AppImage/dmg)+SHA256 첨부. **수동 Build로 3플랫폼 전부 빌드 검증 완료**
  - **인용 네트워크 그래프 시각화** (P14 L2, [devlog 072](./devlog/20260724_072_Citation_Network_Ego_Graph.md), `828bb4e` 등): 논문 우클릭 "Show in citation network" → ego-network(선택 논문 1~2홉) `QGraphicsView` force-directed. **전체 네트워크**(held `resolved_paper` + 외부 `CitedWork` `resolved_work`). 2채널: **채움색=방향**(피인용 초록/인용 앰버/상호 시안/2홉 회색), **테두리=보유**(굵은실선 PDF보유/얇은실선 held/점선 external). 클릭=재중심(held만), Open in list=리스트 reveal. `paper_service.load_ego_network`. 라이브 확인 대기
  - **v0.1.1 릴리스** (`e49fa39` + 태그 `v0.1.1`): `CHANGELOG.md`(Keep a Changelog) 신설 + release.yml이 **CHANGELOG 섹션을 awk 추출해 릴리스 노트로** (Modan2 방식). 3-OS 아티팩트 + 노트로 **release 파이프라인 end-to-end 검증 완료**. 다음 릴리스: CHANGELOG 섹션 추가 → version.py 범프 → 태그 push
  - **구현 기록**: [069](./devlog/20260723_069_Citation_Matching_And_Network_Implementation.md)(P14) · [070](./devlog/20260723_070_Server_Down_Resilience.md)(서버 복원력) · [071](./devlog/20260724_071_Code_Quality_And_Cross_Platform_Release.md)(P15+릴리스) · [072](./devlog/20260724_072_Citation_Network_Ego_Graph.md)(그래프)
  - 릴리스 후속 잔여(저순위): 앱 아이콘, macOS 코드사이닝/공증. 다음 실질 작업: **references 추출 완주**(진행 중) → 완료 후 재-resolve/normalize 재실행
- **A1 재-resolve + 정규화 라이브 실행 완료** (Windows, 앱 닫은 상태): `resolve_references.py --reresolve --execute` → `normalize_works.py --pass 1 --execute` → `--pass 2 --execute`(~61분, LLM 병합). **효과(라이브 DB 실측)**: unresolved **31.7%→4.3%** 급감, held 13,123→**17,671**, external 58,473→**83,388**, held→held 엣지 12,038→**17,089**, active CitedWork 49,728→**59,963**(pass1이 미분류 인용을 canonicalize → 순증, pass2가 near-dup 5,989 제거). `quick_check=ok`
  - **병합 품질 spot-check 통과**: `match_method='work-llm'` 7,955 refs 샘플 검사 — 전부 같은 문헌의 OCR/철자/음차 변형(키릴 혼입까지 정상 병합), Hupé 1953/1955 Part1/2를 연도로 구분 유지(과대병합 없음). borderline 1건(work#20427 Whittington), out-degree 이상치 1건(Education 2005, 367)만 관찰 대상
  - **다음**: PaperMeister 재시작(새 스코어러 + Cancel 버튼 반영) → 추출 재개. 추출이 더 진행되면 재-resolve 한 번 더(멱등). 증분 재-resolve 훅(sync 콜백)·L2/L3(인앱 ego-view / 공동인용)은 이후
- 참고: `.papermeister/papermeister.db.pre-p13-backup`(4.3GB, 6/26)는 검증 종료 후 삭제 가능 → **세션 52에서 `corrupt-20260625`와 함께 삭제됨**

### 세션 1~49 (2026-03-30 ~ 06-25) — devlog로 이관

상세 내역은 `devlog/`에 있다(001~068 + P01~P13이 이 구간을 연속으로 덮는다). 여기엔 이정표만 남긴다.

| 시기 | 이정표 | devlog |
|------|--------|--------|
| 03-30 ~ 04-01 | MVP(0→1), Zotero 연동, 병렬 OCR, CLI | 001~007 · P01~P03 |
| 04-02 ~ 04-09 | LLM 서지 추출 파이프라인 + 모델 비교(Haiku 채택), `PaperBiblio`, standalone promote, vision pass | 008~018 · P04~P06 |
| 04-10 ~ 04-16 | 새 desktop 앱 스캐폴드, P08 반영 정책·러너, Zotero write-back, `PaperFolder` M2M, 탭형 DetailPanel, 검색 wiring | 019~029 · P07~P10 |
| 05-13 ~ 05-28 | OCR Wrapper/Qwen3 3-backend, 폴더 일괄 파이프라인, write-back 토글 + `papermeister_meta` 크로스머신 sync, 자동 큐 깊이, lazy PDF 렌더 | 030~040 |
| 06-05 ~ 06-10 | Zotero trash·영구삭제 미러, incremental collections sync, OCR JSON 파일명 통일, 첨부 확장자 게이트(`skipped`), biblio 배치 워크플로, 라이브러리 전체 Process All | 041~060 |
| 06-15 ~ 06-26 | PyInstaller 패키징, 로컬 폴더 가져오기, 검색 제목 부스트·하이라이트, references 설계·구현, CitedWork 정규화, FTS external-content | 061~068 · P02·P11~P13 |
