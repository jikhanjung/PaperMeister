# 061 — PyInstaller 패키징 구현 + conda DLL 트러블슈팅 (완료)

> 세션 46 (2026-06-15). [P02 계획](./20260615_P02_PyInstaller_Desktop_Packaging.md)대로 onedir
> `.exe`를 만들었더니 conda 환경 특유의 DLL 문제가 연쇄로 터졌다. 그 진단 과정과 최종
> 동작 레시피를 기록한다. **결과: 빌드 성공, Qt/SQLite/SSL(Zotero sync)/PyMuPDF/FTS5 검증.**

## 증상 1 — 프로즌 앱이 QtWidgets에서 죽음

```
ImportError: DLL load failed while importing QtWidgets: 지정된 프로시저를 찾을 수 없습니다.
```

(`지정된 프로시저를 찾을 수 없습니다` = Windows error 127 = DLL은 로드됐는데 기대한
export 함수가 없음 = **버전 불일치**.) `python -m desktop`은 멀쩡히 돌아가는데 `.exe`만 실패.

### 헛다리 1 — VC++ 런타임 루트 셰도잉

번들에 VC 런타임이 **두 벌**이었다:
- `_internal\PyQt6\Qt6\bin\VCRUNTIME140_1.dll` = 14.44 (PyQt6 동봉, 정상)
- `_internal\VCRUNTIME140_1.dll` (루트) = 14.29 (conda에서 끌려옴, 구버전)

"루트가 먼저 로드되니 구버전이 범인"이라 보고 spec에 *루트의 PyQt6-중복 DLL을 신버전 src로
교체*하는 로직을 넣었다. **그런데 수동 복사로 루트를 14.44로 바꿔도 실패.** →
로드 순서상 `Qt6Core.dll`은 자기 옆(`Qt6\bin`)의 14.44를 쓰므로 루트 복사는 무의미했다.
VC 런타임은 범인이 아니었다. (단, 이 spec 교체 로직은 무해하고 일반적으로 옳아서 유지.)

### onefile도 동일

`PM_ONEFILE=1`로 단일 파일 빌드 → **완전히 같은 에러**. 즉 onedir/onefile 모드와 무관한
**번들링 자체의 문제**. (console 빌드 `PM_CONSOLE=1`로 full traceback 확보해서 확정.)

### 결정적 단서 — ctypes 프로브

conda 셸에서 번들된 Qt DLL을 직접 로드:
```python
ctypes.WinDLL(r'...\_internal\PyQt6\Qt6\bin\Qt6Core.dll')   # → OK
# Qt6Gui.dll, Qt6Widgets.dll 도 OK
```
**conda PATH가 있는 상태에선 셋 다 정상 로드.** 즉 번들된 Qt DLL 자체는 멀쩡하고,
의존 DLL을 conda `Library\bin`(PATH)에서 *올바른 버전으로* 빌려 로드한 것. 프로즌 앱은
실행 시 conda PATH가 없으니, **PyInstaller가 빌드 때 conda에서 끌어와 번들한 엉뚱한 버전의
Qt-의존 DLL**을 쓰다 "프로시저 없음"이 난 것.

### 진짜 원인 + 수정

빌드를 **conda 셸에서** 했기 때문에 conda의 Qt-의존 DLL이 번들에 섞였다. onedir·onefile
둘 다 같은 오염을 물려받음. **해결: conda를 PATH에서 뺀 채로 빌드.**

```cmd
REM 플레인 cmd (conda 비활성). conda env python은 venv의 base 인터프리터로만 사용.
"C:\Users\...\anaconda3\envs\PaperMeister\python.exe" -m venv .build-venv
.build-venv\Scripts\activate.bat
where Qt6Core.dll      REM → 빈 결과 (conda Library\bin이 PATH에 없음) ✓
where python           REM → .build-venv\Scripts\python.exe ✓
pip install -r requirements.txt pyinstaller pyinstaller-hooks-contrib
python -m PyInstaller PaperMeister.spec --noconfirm --clean
```
→ **Qt 에러 사라짐.** 앱이 `init_db()`까지 진행.

## 증상 2 — SQLite driver not installed

```
peewee.ImproperlyConfigured: SQLite driver not installed!
```

conda를 PATH에서 빼니 이번엔 `import sqlite3`가 실패. **conda는 `sqlite3.dll`을 `DLLs\`가
아니라 `<env>\Library\bin`에 둔다.** 빌드 때 Library\bin이 PATH에 없으니 PyInstaller가
`_sqlite3.pyd`는 넣고 그 의존 `sqlite3.dll`은 못 찾아 누락. (같은 이유로 `_ssl`/`_hashlib`도
다음 차례 — Zotero HTTPS에 필요했음.)

### 수정 — Library\bin에서 stdlib 지원 DLL만 콕 집어 번들

spec에서 `sys.base_prefix\Library\bin`(= conda env)으로부터 **Qt와 무관한** stdlib 지원
DLL만 골라 `a.binaries`에 추가:
`sqlite3.dll`, `libssl-3-x64.dll`, `libcrypto-3-x64.dll`, `libffi*.dll`, `liblzma.dll`,
`libbz2.dll`/`bzip2.dll`. (전부 Qt 의존성과 무관 → Qt 문제 재발 없음.)

→ 재빌드 후 **정상 실행.** Rail 아이콘/chevron(SVG), Zotero Sync(SSL), PDF 탭(PyMuPDF),
검색(FTS5/SQLite) 전부 동작 확인.

## 최종 상태 / 레시피

- 빌드: `build_desktop_clean.bat "<conda env python.exe 경로>"` (플레인 cmd, conda 비활성)
- 산출물: `dist\PaperMeister\PaperMeister.exe` (onedir, windowed)
- spec(`PaperMeister.spec`)이 자동 처리: SVG 아이콘 datas / lazy-import hiddenimports /
  Anaconda 비대화 excludes / 루트 VC런타임 중복 교체 / **Library\bin stdlib DLL 보강** /
  `PM_ONEFILE`·`PM_CONSOLE` 토글

## 교훈 (다음에 또 conda+PyInstaller 만나면)

1. **"procedure not found"는 거의 항상 DLL 버전 불일치.** conda 환경에서 빌드하면 conda의
   의존 DLL이 섞이기 쉽다. → **conda OFF PATH인 venv에서 빌드**가 정석.
2. 그러면 conda가 `Library\bin`에 숨겨둔 **stdlib 지원 DLL(sqlite3/openssl/...)**이 빠진다.
   → spec에서 `sys.base_prefix\Library\bin`으로부터 필요한 것만 명시 추가.
3. ctypes로 번들 DLL을 직접 로드해보면 "DLL 자체 문제 vs PATH/로드컨텍스트 문제"를 가른다
   (conda PATH 유무로 결과가 갈리면 = 빌드 환경 오염).
4. onefile/onedir은 이런 DLL 문제엔 차이 없음 — 모드 바꿔봐야 시간 낭비, 원인은 동일.
5. 진짜 정공법은 **conda 말고 python.org Python으로 빌드**하는 것(=stdlib DLL이 `DLLs\`에
   있어 1·2가 통째로 사라짐). 지금은 conda env만 있어 위 우회로 해결.

## 후속 (미완, 저순위)

- 앱 아이콘(`.ico`), 버전 정보, 코드사이닝
- 배포 자동화(zip/installer)
- 여유되면 python.org Python 빌드로 전환해 Library\bin 보강 로직 제거
