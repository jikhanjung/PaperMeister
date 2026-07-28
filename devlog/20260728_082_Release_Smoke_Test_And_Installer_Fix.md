# 082 — v0.1.2 릴리스: 프로즌 빌드 스모크 테스트 + 설치본 누락 수정

> 구현 기록 (2026-07-28). 계기: "release 잘 만들어지는지 버전 올려서 태그 push 해보자"
> → 파이프라인은 잘 돌았고, **돌리는 과정에서 구멍 두 개가 드러났다.**

## 1차 발행에서 드러난 것

`v0.1.2` 태그 push → test → 3플랫폼 빌드 → 발행까지 전부 그린. CHANGELOG 섹션이
릴리스 노트로 정확히 들어갔다. **릴리스 프로세스 자체는 정상 동작.**

그런데 자산이 **3개**였다. 노트는 "Windows (portable zip + installer)"라고 말하는데
설치본이 없었다.

### 구멍 (a) — 설치본이 빌드되고도 첨부되지 않음

빌드 로그엔 `PaperMeister_v0.1.2_build236_Installer.exe`가 있고, `SHA256SUMS.txt`에도
있다. **다운로드까지 됐는데 첨부만 안 됐다.** 경로 깊이 때문이었다:

```
release-files/papermeister-windows/…Portable….zip                     ← 2단계, 첨부 ✓
release-files/papermeister-linux/…AppImage                            ← 2단계, 첨부 ✓
release-files/papermeister-windows/installer/Output/…Installer.exe    ← 4단계, 누락 ✗
```

`installer/Output/*.exe`로 업로드하니 그 경로가 아티팩트 안에 **보존**됐고, 릴리스 단계의
`release-files/**/*.exe` 글롭이 거기까지 닿지 않았다. 2단계인 zip·AppImage는 잘 걸렸다.

**v0.1.1도 같은 상태였다** — 설치본 도입 이래 계속 누락. 노트만 있고 파일은 없었던 것.

수정: 업로드 전에 설치본을 zip 옆(레포 루트)으로 옮겨 **다른 아티팩트와 같은 깊이**로 만든다.

### 구멍 (b) — 릴리스 파일을 한 번도 실행해보지 않았음

사용자 질문에서 시작됐다: *"`--self-test`는 실제 파일을 실행시켜 보는 거야?"*

Modan2·CTHarvester는 빌드 직후 **프로즌 실행 파일을 띄운다.** 우리에겐 그 단계가 없었다.
3플랫폼을 빌드·체크섬·발행하면서 **단 한 번도 실행하지 않았다.**

이게 왜 중요한가 — 프로즌 실행 파일은 **자기 번들의 Python·라이브러리**를 쓴다. 소스 트리
테스트는 그 번들을 건드리지 않으므로, 다음 부류를 **구조적으로 못 본다**:
- 빠진 `--add-data` 항목
- 번들 안 된 네이티브 라이브러리
- 누락된 Qt 플랫폼 플러그인 / SQLite 드라이버

**이 프로젝트의 최악의 패키징 사고가 정확히 그 부류였다** — devlog 061의 conda DLL 건은
"빌드 성공, 실행 시 procedure not found로 사망"이었다. 지금 방식이면 그게 또 나도 릴리스에
그대로 실린다.

## 수정: `--self-test`

`desktop/app.py`에 플래그 추가. 정상 기동 경로를 **전부 타고**(무거운 import → Qt 플랫폼
플러그인 → `init_db()` → 테마/SVG → MainWindow) 3초 뒤 self-exit 0.

### argparse를 쓰지 않은 이유

앱의 유일한 플래그인데 argparse를 붙이면 `-h`/`--help`를 가져가고, **Qt가 넘기는 인자**
(`-platform`, `-style` 등)에 에러를 낸다. `'--self-test' in sys.argv[1:]` 한 줄이 맞다.

### 타이머로 종료하는 이유

이벤트 루프를 잠깐 돌려 지연 초기화 작업이 실행되게 한 뒤 종료한다. 종료 전에 top-level
위젯을 닫는데, 떠 있는 모달의 중첩 루프가 `quit()`보다 오래 살아 **러너를 매달아 두는**
것을 막기 위해서다.

### 3레그 스모크 단계

| 플랫폼 | 상한 방식 |
|---|---|
| Windows | `Start-Process -Wait` (windowed 앱이라 `-Wait` 필수) |
| Linux | `timeout 120` (외부 상한) |
| macOS | 러너에 `timeout`이 없음 → **앱 내부 워치독**이 상한 |

패키징 **전에** 실행한다 — 깨진 번들이 AppImage/DMG로 감싸지기 전에 실패하도록.

### 테스트를 붙인 이유

`tests/test_self_test_flag.py` 4케이스. self-test가 **조용히 안 걸리게 되면 CI 단계가
아무것도 검사하지 않으면서 통과**한다 — 오늘 mypy 게이트에서 본 것과 **정확히 같은 실패
방식**(devlog 081). 그래서 "플래그가 인식된다"와 "타이머가 실제로 종료를 예약한다" 양쪽을
고정했다.

## 재발행

사용자 요청으로 릴리스·태그를 지우고 최신 커밋에 다시 붙였다. `[Unreleased]`에 적어둔 두
항목을 **0.1.2 섹션으로 합쳤다** — 재발행되는 빌드에 실제로 들어간 내용이므로 노트에 있어야
맞다. (같은 버전 재발행은 원칙적으로 피할 일이지만, 발행 1시간 미만·소비자 없음.)

## 결과 (라이브 검증)

```
Smoke-test frozen build (Windows)   success
Smoke-test frozen build (Linux)     success
Smoke-test frozen build (macOS)     success
```

자산 **4개 + 체크섬**:
`Windows-Portable.zip` / **`Installer.exe`(처음 첨부)** / `Linux.AppImage` / `macOS.dmg`

이제 릴리스에 붙는 파일은 **최소한 기동은 된다는 것이 보장된다.**

## 남은 한계

스모크 테스트는 **"기동한다"까지만** 보증한다. Windows 설치본이 정상 설치되는지, 실제
기능이 동작하는지는 검증하지 않는다. 사용자 수동 확인 영역.
