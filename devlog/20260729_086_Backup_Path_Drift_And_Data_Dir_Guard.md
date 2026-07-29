# 086 — 경로 이동이 끊어놓은 백업, 그리고 데이터 위치 설정 가능화의 선결 조건

> 구현 기록 (2026-07-29). 상태 점검으로 시작해서 백업 장애 하나를 찾았고, 형제 프로젝트의
> [Modan2 P03](../../Modan2/devlog/20260728_P03_data_directory_relocation_plan.md)을 우리
> 조건에 대조해 **무엇을 지금 하고 무엇을 미룰지**를 갈랐다.

## 1. 상태 점검 — 문서가 실제보다 뒤처져 있었다

HANDOFF의 마지막 실측은 7/23 것이었다. 라이브 DB를 다시 재니 진행이 두 배 이상 나가 있었다.

| | HANDOFF (7/23) | 실측 (7/29) |
|---|---|---|
| `references_checked` | 1,733 / 9,889 (17.5%) | **4,248 / 9,891 (43%)** |
| `Reference` | 104,755 | **199,719** |
| held 매칭 | 13,102 | **36,218** |
| `CitedWork` | 49,728 | **108,075** |

OCR은 사실상 끝났다 — processed 19,894 / pending 3 / **failed 0** / skipped 110.

**WSL에서 라이브 DB를 읽는 방법**이 그동안 막혀 있었는데(074에서 `disk I/O error`로 포기),
`?mode=ro&immutable=1`로 열면 된다. WAL을 무시하고 마지막 체크포인트 시점을 보는 것이라
값이 약간 과거지만, 진행률 확인에는 충분하다. 앱이 쓰는 중에도 안전하다.

추출 건강도도 로그로 확인했다 — 오늘 10시간에 161편, PARTIAL **1건**, `empty_result`·`no_array`
**0건**. 079의 가드들이 오탐 없이 조용하다는 뜻이다.

**문서에 없던 수치 둘을 찾았다.** `extracted` 잔존은 48편이 아니라 **10편**이고(그동안의
라이브러리 전체 Process All이 대부분 정리했다), 대신 **needs_review가 5,229편**이다. 후자는
지금 이 프로젝트의 가장 큰 실제 백로그인데 HANDOFF에 숫자가 아예 없었다.

## 2. 백업이 7/28 이후 조용히 죽어 있었다 (`a071ef0`)

### 발견

Modan2 P03이 "배경이 지적한 피해는 위치 문제로 위장한 백업 문제였다"고 한 대목을 우리에
대조해 보다가 `scripts/backup-papermeister.ps1`을 열었다. 27행:

```powershell
$Db = Join-Path $env:USERPROFILE '.papermeister\papermeister.db'
```

**v0.1.4에서 데이터를 옮길 때 이 스크립트만 따라오지 않았다.** `~/.papermeister`는
`shutil.move`로 통째로 사라졌으므로, 3시간마다 도는 Task Scheduler 작업은 7/28 14:21 이후
`unable to open database file`로 계속 실패하고 있었다.

**Task Scheduler 실패는 아무에게도 보이지 않는다.** 084가 데이터 이동을 "라이브 이동 확인됨"
으로 닫을 때, 확인한 것은 앱이 새 경로에서 뜬다는 것이었다. 앱 밖에서 그 경로를 아는 것이
하나 더 있다는 사실은 점검 목록에 없었다.

### 불행 중 다행

서버 보존 정리(`ls -t | tail -n +25 | xargs rm`)는 **scp 성공 뒤에만** 실행된다. 실패한 런은
거기까지 못 가므로 **7/28 이전 백업들은 서버에 그대로 남아 있다.** 새로 안 쌓였을 뿐이고,
있던 것이 지워지지는 않았다.

순서가 반대였다면 — 정리를 먼저 하는 구조였다면 — 실패한 런들이 3일치 보존분을 갉아먹고
있었을 것이다. 의도한 설계는 아니었지만 결과적으로 옳은 순서였다.

### 고친 방향: 경로를 두 번 적지 않는다

```powershell
$Db = (& $Python -c "import sys; sys.path.insert(0, r'$repoRoot'); from papermeister.paths import DB_PATH; print(DB_PATH)")
```

084가 23개 파일의 하드코딩을 `paths.py` 하나로 모은 작업이었는데, **이 스크립트는 파이썬이
아니라서 그 정리에서 빠졌다.** 값을 복사하는 대신 앱에게 물어보게 하면 다음 이동에도 안
깨지고, 덤으로 `PAPERMEISTER_DATA_DIR`도 자동으로 따른다.

해석에 실패하면 조용히 넘어가지 않고 throw한다. **이 스크립트가 조용히 실패해서 생긴 문제를
고치면서 새로운 조용한 실패를 만들면 안 된다.**

### 더 깊은 함정: `sqlite3.connect`는 없는 DB를 만든다

경로가 틀렸을 때 지금은 부모 디렉터리가 없어서 에러가 났다. 하지만 **부모가 우연히 존재하는
경로로 틀렸다면** `sqlite3.connect(src)`가 빈 DB를 만들고, `_db_snapshot.py`는 그것을 성실히
스냅샷해서 gzip하고 scp하고 `Backup OK`를 찍었을 것이다. 그리고 24번 반복하면 보존 정리가
진짜 백업을 전부 밀어낸다.

**출력을 아무도 읽지 않는 작업에서 가장 위험한 실패 방식**이라 명시적으로 막았다:

```python
if not os.path.exists(src):
    print(f'source database does not exist: {src}', file=sys.stderr)
    sys.exit(1)
```

## 3. 데이터 위치 설정 가능화 — Modan2와 같은 결론, 다른 조건

사용자가 Modan2 P03을 공유했다. 초안의 "기본값을 Documents로 옮긴다"를 **철회**하고
현행 위치를 유지하되 **설정 가능하게** 만드는 쪽으로 개정된 문서다.

### 우리에게 그대로 적용되는 부분

기본값 유지는 우리도 같다. 그리고 P03의 3단계(설정을 OS 설정 위치로)는 **우리가 같은 날
이미 했다**(085/R02). 즉 부트스트랩 순환은 양쪽 다 이미 끊겨 있다.

### 갈리는 지점 하나 — 우리는 WAL이다

P03 조사 8은 Modan2가 rollback journal이라 동기화 폴더 위험이 덜하다고 적고,
**"향후 WAL을 켜게 되면 이 계획의 판단을 다시 봐야 한다"**고 단서를 달았다.

우리는 이미 WAL이다(`database.py:234`). DB 2.5GB에 `-wal`/`-shm` 정합성까지 얹히므로,
경로가 설정 가능해질 때 **"동기화 폴더를 지정하지 말라"는 경고는 선택이 아니라 필수**다.
같은 결론에 도달한 두 프로젝트가 같은 이유로 도달한 것은 아니다.

### 미룬 이유 — 리팩터의 값이 오늘은 0이다

P03 조사 2(기본 인자가 import 시점에 고정된다)의 우리 판은 더 넓다. 프로덕션 코드
**20여 곳이 전부 `from .paths import DB_PATH` 형태**로 값을 자기 네임스페이스에 복사한다
(`database.py`·`biblio.py`·`text_extract.py`는 그것을 다시 재export한다).

**그런데 오늘은 아무 문제도 없다.** `PAPERMEISTER_DATA_DIR`는 프로세스 시작 전에 정해지므로
모든 복사본이 같은 값을 든다. 이 리팩터는 **런타임에 바꿀 수 있게 되는 순간에만** 값이 생긴다.

그래서 미뤘다. 근거 셋:

1. **역량은 이미 있다.** 환경변수로 어디든 지정할 수 있다. UI가 더하는 것은 편의성이다.
2. **결합이 나쁘다.** 지금 2주짜리 무인 배치가 2.5GB 라이브러리에 붙어 돈다. 사용자가 refs
   개선분을 받으려 재시작할 때 **덜 검증된 경로 리팩터가 같이 딸려 들어간다.**
3. **Modan2의 동기가 우리에겐 없다.** 그쪽 출발점은 OneDrive 백업 누락이었는데, 우리는
   오프사이트 scp로 다르게 풀었다(그리고 그게 2절에서 고친 그 스크립트다).

### 다만 위험 7은 지금 열려 있었다 (`9885011`)

P03 위험 7("설정된 경로가 사라졌을 때")은 **UI 없이도 이미 도달 가능한 구멍**이었다.
`PAPERMEISTER_DATA_DIR`가 연결 안 된 드라이브를 가리키면 `ensure_directories()`가 그 자리에
빈 라이브러리를 만들고 앱이 조용히 떴다. 사용자 눈에는 데이터 소실이다.

```python
def check_configured_data_dir() -> None:
    if not os.environ.get('PAPERMEISTER_DATA_DIR'):
        return
    parent = os.path.dirname(DATA_DIR.rstrip(os.sep))
    if parent and not os.path.isdir(parent):
        raise DataDirUnavailable(...)
```

판단 두 가지:

- **디렉터리 자신이 아니라 부모를 본다.** 새 위치를 처음 지정하는 것(`E:\Library`가 있고
  `E:\Library\PaperMeister`를 만드는 것 — 정상)과 드라이브 미연결(`E:\` 자체가 없음 — 거부)을
  구분해야 한다. 자기 자신을 검사하면 첫 지정이 항상 에러가 된다.
- **기본값 경로는 검사 대상이 아니다.** 그건 우리가 만들 자리고, 사용자가 지정한 자리는
  사용자가 제공할 자리다. 새 머신에 `~/PaleoBytes`가 없는 것은 정상이다.

**기본값으로 조용히 되돌아가는 것도 금지**다 — 빈 라이브러리가 열리고 사용자는 데이터를
잃었다고 생각한다. 알리고 멈춘다.

desktop은 `QApplication`을 만들기 전 단계라 stderr가 갈 곳이 없다(Windows 빌드는 콘솔이
없다). 메시지를 전달할 최소한의 `QApplication`만 만들어 `QMessageBox`를 띄우고 종료한다.

**검증**: 테스트 3개(미연결 거부 / 첫 지정 허용 / 기본값 면제) + 실제 CLI 실행으로
exit 1 + **아무것도 생성되지 않음** 확인. 145 passed, ruff·mypy clean.

## 4. HANDOFF 정리 (`bd22b9c`)

749줄 → 313줄. **append-only 로그가 되어 있었다** — 355줄이 첫 커밋까지 거슬러가는 세션
요약이었고, "안정적으로 돌아가는 것"은 현재 앱의 설명이 아니라 세션별 제작 후기였다.

세션 1~49는 이정표 표로 대체하고 `devlog/`를 가리키게 했다. **devlog 001~068 + P01~P13이
그 구간을 연속으로 덮는 것을 확인한 뒤에** 지웠다 — 두 번 적혀 있지 않은 것은 지우지 않았다.

수치는 이어받지 않고 다시 쟀다(1절). 그리고 `~/.papermeister` 잔재 경로가 결정 표에 세 곳
남아 있던 것을 고쳤다.

## 5. v0.1.5 릴리스, 그리고 하루 동안 몰랐던 red CI

절차대로 갔다 — CHANGELOG `[0.1.5]` → **ko 카탈로그 갱신**(085에서 빠뜨렸던 단계) → `version.py`
범프 → 태그. 배포된 ko 매뉴얼에서 0.1.5 섹션이 실제로 한국어로 나오는 것까지 확인했다.

**그런데 첫 태그가 Windows 테스트에서 막혔다.** 확인해 보니 `test.yml`이 **`516b5b5` 이후
6런 연속 red**였다. 마지막 green은 `7882f16`. 어제 설정 분리가 깨뜨렸고, **그 뒤로 릴리스를
안 컷했으니 아무도 안 봤다.** 나도 오늘 커밋 4개를 확인 없이 그 위에 올렸다.

### 원인 — 환경변수로는 Windows의 config 위치를 못 옮긴다

`tests/test_config_location.py`의 헬퍼가 `XDG_CONFIG_HOME`을 고정해 격리한다고 적어 뒀는데,
주석 자체가 `# pin on Linux`였다. Windows에는 대응물이 없었다.

`platformdirs`는 Windows에서 **ctypes(`SHGetFolderPath`)로 해석**한다(`_pick_get_win_folder`가
ctypes → 레지스트리 → 환경변수 순으로 고른다). 즉 `%LOCALAPPDATA%`를 세팅해도 소용이 없다.

결과가 두 겹이었다:

1. Windows CI가 **러너의 실제 프로필을 읽고 썼다**
2. 그래서 테스트가 **순서 의존**이 됐다 — "마이그레이션이 기존 설정을 덮지 않는다"를 증명하려고
   `{'ocr_pod_url': 'current'}`를 써 둔 테스트가 그걸 실제 위치에 남겼고, 다음 테스트가
   마이그레이션 대신 그 값을 주워 읽었다(`assert 'current' == 'http://server'`)

**Linux에선 `HOME` 패치로 우연히 격리돼 완전히 안 보였다.**

### 수정 (`702774c`)

환경변수가 아니라 **resolver 자체를 패치**한다 — `monkeypatch.setattr(platformdirs,
'user_config_dir', ...)`. 세 플랫폼 모두 `tmp_path` 안으로 떨어지고, OS 해석 방식에 의존하지
않는다. `test_paths.py`에도 같은 처리를 했다(`ensure_directories()`가 실제 CONFIG_DIR을
만들고 있었다).

그리고 **격리가 유지되는지 검사하는 테스트를 따로 뒀다.** 이 실패는 Linux에서 안 보이므로
가정이 아니라 명시적 가드여야 한다.

### 형제 리포는 둘 다 면역이었다 — 그리고 둘 다 우리보다 낫다

| | 방식 | 왜 면역인가 |
|---|---|---|
| **Modan2** | 테스트가 `mu.DEFAULT_CONFIG_PATH`·`LEGACY_CONFIG_PATHS`를 **해석된 상수째로** monkeypatch | OS 해석을 리다이렉트하려 들지 않는다. 위치 검증은 `startswith(user_config_dir())` **읽기 전용 단언**이라 쓰지 않는다 |
| **CTHarvester** | 제품에 **`CTHARVESTER_CONFIG_DIR`** override가 있고 테스트는 그 문서화된 override를 쓴다 | 테스트 훅이 아니라 실제 기능. 제품이 env를 먼저 보고 platformdirs로 폴백 |
| **PaperMeister** | `XDG_CONFIG_HOME` 고정 | Linux에서만 통했다 |

**OS 해석과 싸우려 든 건 우리뿐이었다.** 그리고 CTHarvester는 3절에서 우리가 선결 조건으로
꼽은 두 가지 — **접근자 함수**(`get_data_dir()`/`get_config_path()`)와 **데이터·설정 양쪽
env override** — 를 이미 갖고 있다. 설정 가능화에 착수할 때 새로 설계할 게 아니라
`../CTHarvester/utils/paths.py`를 따라가면 된다.

### 태그 처리

v0.1.5는 아무것도 발행하지 못했으므로(`create-release` skip, 릴리스·draft 없음) 태그를 지우고
고친 커밋에 다시 걸었다. 0.1.6으로 올리는 것보다 낫다고 봤다 — **소비된 적이 없는 태그**다.
재실행은 8개 잡 전부 success, 자산 5종.

## 6. 남은 것

- **백업 복구는 Windows에서 한 번 돌려봐야 한다.** WSL에서는 경로 해석과 가드까지만
  검증했고, 서버 scp까지 타는 경로는 여기서 확인이 안 된다
- **설정 위치 분리(`516b5b5`) 코드가 라이브에서 아직 한 번도 안 돌았다.**
  `%LOCALAPPDATA%\PaleoBytes\PaperMeister\`가 없고 `preferences.json`이 데이터 디렉터리에
  그대로다 — 실행 중인 빌드가 그 커밋보다 앞선다. 다음 재시작 때 `migrate_legacy_config()`가
  복사해 간다
- **`ocr_json/` 1.8GB(9,832개)에 백업이 없다.** 오프사이트 백업은 DB만 대상이다. Zotero
  sibling 업로드가 켜져 있는 만큼만 부분적으로 사본이 있다. **OCR 비용 전체가 여기 들어 있어
  재생성이 가장 비싼 자산**인데 가장 대비가 없다 — P03 조사 7("미디어에는 백업이 아예 없다")의
  우리 판이다. 다음에 다룰 값어치가 있다
