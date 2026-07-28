# 084 — PaleoBytes 규약 정렬: 데이터 경로 단일화 + 설치 프로그램 신원

> 구현 기록 (2026-07-28). 요청: "DB 및 로그파일들 저장하는 위치부터. Modan2 케이스를 보고
> 그쪽 방식으로 맞춰줘. `~/PaleoBytes/[AppName]/` 디렉토리에 넣게 되어 있을 거야."

## 왜 chore였나 — 경로가 23개 파일에 흩어져 있었다

`os.path.join(os.path.expanduser('~'), '.papermeister', ...)` 이 표현이 **23개 파일에
그대로 적혀 있었다.** 중앙 경로 모듈이 없었다. 그래서 "디렉터리 하나 옮기기"가 코드 전역
수정 작업이 됐다.

Modan2는 `MdUtils`에 `COMPANY_NAME`/`PROGRAM_NAME` 상수와 `DEFAULT_DB_DIRECTORY` 등을 두고
있다. 같은 구조로 `papermeister/paths.py`를 만들고 전부 거기로 모았다.

```
~/PaleoBytes/PaperMeister/
├── papermeister.db · preferences.json · zotero_collections.json
└── ocr_json/ · pdf_cache/ · logs/ · tmp/
```

## 핵심 판단: 기존 데이터를 자동으로 옮기지 않는다

> **후속 정정 (같은 날)**: 아래 레거시 **폴백은 이후 제거됐다.** 사용자 확인 —
> "사용하는 사람이 없었기 때문에 레거시 디렉토리는 신경쓰지 않아도 돼". 유일한 설치본이
> 이미 이전됐으므로, 경로 해석을 **조건 없는 상수**로 되돌려 `paths.py`·매뉴얼·이 문서에서
> 분기를 설명하던 문단들을 함께 없앴다. 단 **경고는 남겼다**(`warn_if_legacy_dir`) — 폴백을
> 빼면 레거시가 있는 환경에서 앱이 **조용히 빈 라이브러리를 새로 만드는데**, 그게 바로 아래에서
> "Modan2가 겪은 사고"라고 적어둔 모양이기 때문이다. 호환이 아니라 진단으로 남긴 3줄이다.
> 마이그레이션 스크립트는 경고가 안내하는 대상이므로 유지.

라이브러리가 **2.5GB**이고, 그 순간에도 references 배치가 DB에 쓰고 있었고, 그게 **유일한
사본**이다. **남의 데이터를 옮길지를 앱 시작 경로가 결정할 일이 아니다.**

그래서 해석 순서를 이렇게 뒀다:

1. `PAPERMEISTER_DATA_DIR` 환경변수 (테스트·다중 머신용 override)
2. `~/PaleoBytes/PaperMeister` 가 **있으면** 그것
3. 없고 `~/.papermeister` 가 있으면 **레거시 그대로** (이동 없음)
4. 둘 다 없으면 새 경로 (신규 설치)

**2번이 3번보다 앞서는 게 중요하다.** 마이그레이션 후에는 두 디렉터리가 공존할 수 있는데,
그때 남은 옛 디렉터리가 앱을 **도로 stale한 쪽으로 끌고 가면** 안 된다. Modan2가 정확히 그
사고를 겪었다 — `--db` 처리가 무조건 override로 동작해 매번 빈 DB로 뜨고, 진짜 데이터는
`PaleoBytes/Modan2/` 에 손도 안 댄 채 남아 있었다(그쪽 `MdAppSetup._prepare_database` 주석).

이동은 `scripts/migrate_data_dir.py` — dry-run 기본, `--execute`, `--copy`(원본 유지).
`shutil.move`로 통째 이동하므로 **paths.py가 모르는 파일까지 따라온다**(`-wal`/`-shm`,
`.refs_progress_state.json`, 옛 백업 등).

### 검증

라이브와 같은 구성(WAL, 하위 디렉터리, 숨김 파일)을 임시 홈에 만들어 실제 실행 →
**12개 항목, 바이트 단위 완전 동일, 레거시 디렉터리 소멸**. 이후 사용자가 라이브에서 실행,
2.5GB DB 포함 전부 이동 확인.

## 곁들여 발견: `ensure_directories()`가 죽은 코드였다

만들어놓고 아무 데서도 안 불렀다. 각 writer가 자기 디렉터리를 lazy 생성하고 있어 **동작에는
문제가 없었지만**, 신규 설치 시 폴더가 `logs`/`db`/`preferences` 3개만 있는 반쪽 상태로
보였다 — 뭔가 잘못된 것처럼 읽힌다. 두 진입점(desktop `main()`, cli `_init()`)에서 호출하도록
연결. writer별 makedirs는 그대로 둬서 이 호출이 **필수가 아니게** 유지했다.

빈 HOME으로 실기동: 3개 → **6개** 전부 생성, exit 0.

## 설치 프로그램 (`installer/PaperMeister.iss.template`)

| 항목 | 이전 | 지금 |
|------|------|------|
| `AppId` | **없음**(AppName에서 유도) | `{AFA39013-CEDA-4056-9C78-9C66226B8B1F}` |
| `AppPublisher` | 없음 | `PaleoBytes` |
| 설치 위치 | `{localappdata}\Programs\PaperMeister` | `{localappdata}\PaleoBytes\PaperMeister` |
| 시작 메뉴 | `PaperMeister` | `PaleoBytes\PaperMeister` |

**AppId를 지금 넣은 게 타이밍상 중요하다.** 명시적 ID 없이 배포되면 Inno가 AppName에서
신원을 유도하는데, 나중에 표시 이름을 바꾸면 **업그레이드가 별개 프로그램으로 설치**되고
옛 항목이 제어판에 남는다. 그런데 설치본은 **v0.1.2부터야 실제로 배포됐다**(v0.1.1은
빌드됐지만 첨부 누락, devlog 082). 즉 지금은 설치본 보유자가 사실상 없어 신원 변경 비용이
0이다. 더 퍼진 뒤였으면 못 했다.

**Roaming이 아니라 Local인 이유**: onedir 페이로드가 ~180MB라 도메인 가입 PC에서 로그인마다
프로필과 동기화된다. Modan2도 같은 이유로 `{userappdata}` → `{localappdata}`로 옮겼다.
`{localappdata}\PaleoBytes\` 가 제품군 그룹핑과 올바른 루트를 동시에 만족한다.

**런타임 데이터는 설치/제거가 건드리지 않는다.** `[Files]`는 `{app}`에만 쓰고
`[UninstallDelete]`는 없다 — 그 디렉터리가 사용자의 라이브러리라 제거 후에도 남아야 한다.
나중에 누가 정리 목적으로 추가하지 않도록 템플릿 상단에 이유를 명시했다.

### 검증

`{{VERSION}}` 등 CI 치환을 로컬에서 재현해 최종 내용 확인 → 남은 이중 중괄호는 **AppId
이스케이프 한 줄뿐**(Inno의 리터럴 `{` 표기. 이 파일의 `{{PLACEHOLDER}}` 규칙과 헷갈리기
쉬워 주석으로 못박음). 이어서 **Build 워크플로 수동 실행**으로 실제 ISCC 통과 확인:

```
Compiler engine version: Inno Setup 6.7.3
Successful compile (22.125 sec)
→ PaperMeister_v0.1.3_build248_Installer.exe
```

3플랫폼 스모크도 전부 통과. 설치본이 아티팩트 루트에 있는 것도 재확인(082에서 고친 경로
평탄화가 유지되는지 — 깊어지면 릴리스에서 또 누락될 자리).

## 남은 것

실제 설치 동작(설치 위치·시작 메뉴 그룹·제어판 게시자, 그리고 설치 후 기존 라이브러리가
그대로 보이는지)은 **사용자 수동 확인 영역**. 스모크 테스트는 "기동한다"까지만 보증한다.
