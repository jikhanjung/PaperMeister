# R02 — 설정 파일 위치 규약 (PaleoBytes 공통)

> 검토·결정 기록 (2026-07-28). PaperMeister에 적용 완료. **다른 프로젝트에도 그대로
> 쓰라고 쓴 문서**라 프로젝트 고유 사정은 빼고 결론과 근거만 남긴다.

## 결론 한 줄

**설정은 사용자 데이터와 같이 두지 않는다.** OS 설정 위치 아래 `PaleoBytes/<AppName>/`에
`preferences.json` 하나. 해석은 `platformdirs`, 벤더 세그먼트는 직접 붙인다.

```
Windows   %LOCALAPPDATA%\PaleoBytes\<AppName>\preferences.json
macOS     ~/Library/Application Support/PaleoBytes/<AppName>/preferences.json
Linux     ~/.config/PaleoBytes/<AppName>/preferences.json
```

```python
CONFIG_DIR  = os.path.join(platformdirs.user_config_dir(), 'PaleoBytes', APP_NAME)
PREFS_PATH  = os.path.join(CONFIG_DIR, 'preferences.json')
```

## 왜 데이터와 분리하나

1. **성격이 다르다.** 설정은 머신 로컬 상태(창 위치, 엔드포인트, 자격증명)이고, 잃어도
   재설정하면 그만이다. 데이터는 유일하거나 재생성 비용이 큰 자산이다. 백업·동기화·이전의
   대상 여부가 정반대다.
2. **부트스트랩 순환을 미리 끊는다.** 데이터 위치를 설정 가능하게 만드는 순간,
   *설정 파일이 데이터 디렉터리 안에 있으면* 데이터 위치를 알려고 설정을 읽어야 하고
   설정을 읽으려고 데이터 위치를 알아야 한다. **분리는 그 기능의 선행 조건이다.**
3. **자격증명이 데이터와 함께 이동하지 않는다.** 데이터 디렉터리는 언젠가 공유 드라이브·
   동기화 폴더·외장 디스크로 갈 수 있다. API 키가 평문이면 그때 같이 간다.

## 왜 `platformdirs`인가 (`QStandardPaths` 아님)

| | |
|---|---|
| 직접 조립 | `XDG_CONFIG_HOME` 폴백, 현지화된 Windows 폴더명에서 깨진다. 스펙 재구현 |
| `QStandardPaths` | 정확하지만 **Qt를 끌어온다** |
| **`platformdirs`** | 순수 파이썬(컴파일 확장 0, 3 OS 동일 wheel), 사실상 표준 |

**Qt를 피하는 이유**: 경로 모듈은 CLI·배치 스크립트가 import한다. 거기에 Qt가 붙으면
헤드리스 환경에서 스크립트 하나 돌리는 데 GUI 툴킷이 필요해진다. GUI 전용 프로젝트라면
`QStandardPaths`도 무방하지만, **한 제품군에서는 한쪽으로 통일하는 편이** macOS 경로가
갈리지 않는다(아래).

## 벤더 세그먼트는 직접 붙인다

`platformdirs`에 `appauthor`를 넘겨도 **Windows에서만** 반영된다. macOS·Linux 관례에는
벤더 디렉터리가 없어서 의도적으로 무시한다.

제품군을 묶으려면 루트만 받아 직접 조립한다:
```python
platformdirs.user_config_dir()                    # 루트만
os.path.join(root, 'PaleoBytes', APP_NAME)        # 벤더+앱
```
세 경로 모두 각 플랫폼에서 정당한 위치다 — 벤더 디렉터리가 금지된 게 아니라 관례가 아닐 뿐.

### macOS 주의

- `platformdirs` → `~/Library/Application Support`
- `QStandardPaths(AppConfigLocation)` → `~/Library/Preferences`

Apple 기준으로는 **전자가 맞다**. `Preferences`는 defaults 시스템(plist) 자리이고, 앱이
직접 관리하는 JSON은 `Application Support`다. 두 도구를 섞어 쓰면 **여기서 갈린다.**

## 로그는 옮기지 않는다

두 가지 이유:
1. **부트스트랩** — 로깅은 설정을 읽기 전에 세팅된다. 로그 위치를 설정에 따르게 하려면
   초기 로그를 버리거나 이중 초기화를 해야 한다.
2. **조사 편의** — 장애를 볼 때 로그와 데이터가 한 폴더에 있으면 그곳만 보면 된다.

## 이전(migration)

**설정은 자동 복사해도 된다.** 1KB 미만이라 실패 비용이 없다 — 데이터 디렉터리 이전을
자동화하면 안 되는 것과 정확히 반대편이다.

구현에서 정한 것 셋:

- **첫 읽기에 건다**, 진입점이 아니라. 스크립트·CLI는 앱 초기화를 거치지 않으므로, 진입점
  하나만 놓쳐도 **설정 없이 조용히 도는 실행**이 생긴다.
- **새 위치에 이미 있으면 덮지 않는다.** 오래된 레거시 파일이 현재 설정을 되돌리면
  조용한 회귀가 된다.
- **원본은 지우지 않는다.** 비용이 0이고, 옛 빌드로 되돌려도 설정을 찾는다.

## 체크리스트 (다른 프로젝트 적용 시)

- [ ] `platformdirs` 의존성 추가 (lock 갱신)
- [ ] 경로 모듈에 `CONFIG_DIR` / `PREFS_PATH` / `LEGACY_PREFS_PATH`
- [ ] 벤더 세그먼트를 직접 붙였는지 (`appauthor` 인자로는 mac/Linux에서 안 붙는다)
- [ ] 이전 함수를 **설정 첫 읽기**에 연결
- [ ] 테스트: 데이터 디렉터리 밖에 있는가 / 벤더 세그먼트 / 복사됨 / **덮어쓰지 않음** /
      스크립트 경로에서도 이전이 일어나는가
- [ ] 로그는 그대로 두었는지 확인
