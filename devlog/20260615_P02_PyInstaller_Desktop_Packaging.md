# P02 — PyInstaller로 desktop 앱 .exe 패키징 (계획 + 1차 구현)

> 세션 46 (2026-06-15). 라이브러리 전체 biblio 작업 완료 후 다음 과제:
> `python -m desktop` 대신 더블클릭 가능한 Windows `.exe`로 배포.

## 목표

개발 환경(Anaconda + `python -m desktop`) 없이도 desktop 앱을 실행할 수 있는
Windows 실행 파일 생성. 사용자가 Python/패키지 설치 없이 쓰는 것이 목적.

## 결정

| 항목 | 결정 | 근거 |
|------|------|------|
| 패키징 모드 | **onedir** (`dist/PaperMeister/` 폴더 + `.exe`) | onefile은 매 실행 시 200MB+ 임시폴더 압축해제로 콜드 스타트 ~10초 + PyMuPDF 임시추출 이슈 + 백신 오탐. 개인 도구라 폴더 배포(zip) 비용 < 실행 속도/안정성 이득 |
| 빌드 정의 | `PaperMeister.spec` (CLI 플래그 X) | 재현성. datas/hiddenimports/excludes가 길어서 spec이 관리 용이 |
| entry point | `run_desktop.py` (루트) | `desktop/__main__.py`는 `from desktop.app import main`이라 스크립트 직접 실행 시 sys.path 모호. 루트 스크립트 + `pathex=['.']`로 명확화. `python run_desktop.py`로도 실행 가능 |
| 빌드 위치 | **Windows native (Anaconda)** | `.exe`는 Windows에서만 생성. 라이브 환경과 동일(메모리: migration도 Windows에서) |
| 앱 아이콘 | 없음 (TODO) | SVG만 있고 `.ico` 없음. spec의 `icon=None`에 나중에 `.ico` 경로 추가 |

## 코드/리소스 분석 (무엇을 번들해야 하나)

PyInstaller가 자동으로 못 잡는 것만 추림:

1. **SVG 아이콘 7개** (`desktop/theme/icons/*.svg`) — 유일한 소스-상대 리소스.
   `desktop/theme/icons.py`와 `desktop/theme/qss.py`가 둘 다
   `Path(__file__).parent / 'icons'`로 읽음. spec의
   `datas=[('desktop/theme/icons', 'desktop/theme/icons')]`로 같은 상대 레이아웃
   유지 → 프로즌에서 `__file__`이 `{_MEIPASS}/desktop/theme/icons.py`가 되므로
   `.parent / 'icons'`가 정확히 매칭. **코드 수정 불필요.**
2. **lazy import 2개** — `desktop`이 `papermeister.ui.process_window` /
   `preferences_dialog`를 함수 내부에서 import (재사용하는 동결 다이얼로그).
   PyInstaller AST 분석이 대개 잡지만 hiddenimports에 명시해 보험.
3. 그 외 `open()`/`fitz.open()`/`json.load()`는 전부 **사용자 데이터 경로**
   (PDF, `~/.papermeister`의 OCR 캐시/prefs/Zotero 캐시) 또는 런타임 인자 경로 —
   번들 대상 아님. biblio 프롬프트는 인라인 문자열.

## 번들에 **안 들어가는** 외부 의존성 (런타임 요구)

- **`claude -p` CLI** — biblio 추출(Sonnet/Haiku)이 `subprocess`로 호출
  (`papermeister/biblio.py::_call_claude`). `.exe`에 못 넣음 → 실행 PC의 PATH에
  `claude`가 있어야 biblio 추출 동작. **지금 `python -m desktop`과 동일 조건**
  (OCR/검색/sync/뷰어는 `claude` 없어도 전부 동작, biblio 추출만 영향).
- **`~/.papermeister/`** (DB/cache/prefs) — 런타임 생성, 번들 안 함. 첫 실행 시
  `init_db()`가 생성. 기존 사용자는 홈의 데이터 그대로 재사용.

## excludes (번들 다이어트)

Anaconda **base 환경**에서 빌드하면 numpy/scipy/mkl 등이 transitive로 휩쓸려
번들이 수백 MB 비대해짐. 실제 의존성이 아니므로 spec `excludes`로 차단:
numpy/scipy/pandas/matplotlib/sympy/numba, IPython/jupyter/pytest/sphinx,
tkinter/PySide6/PyQt5, 안 쓰는 무거운 Qt 모듈(WebEngine/Multimedia/Qml/Qt3D).
사용하는 Qt는 QtWidgets/QtGui/QtCore/**QtSvg**뿐(WebEngine 등 무거운 모듈 없음).

## 산출물

- `run_desktop.py` — entry point
- `PaperMeister.spec` — onedir 빌드 정의
- `build_desktop.bat` — Windows 빌드 헬퍼 (pyinstaller 설치 → clean → build)
- `.gitignore`에 `/build/` `/dist/` 추가 (spec은 추적, 산출물은 제외)

## 빌드 절차 (Windows, 라이브 환경)

```cmd
REM repo 루트에서, python -m desktop 쓰던 그 env
build_desktop.bat
REM → dist\PaperMeister\PaperMeister.exe
```

## 사용자 검증 체크리스트 (1차 빌드 후 Windows에서)

WSL에선 `.exe` 생성 불가라 빌드/실행 검증은 사용자가 수행. 확인할 것:

- [ ] 빌드 성공 + `dist\PaperMeister\PaperMeister.exe` 생성
- [ ] 더블클릭 실행 → 창 뜸, **다크 테마/Rail 아이콘이 보임** (= SVG 번들 OK)
- [ ] SourceNav 트리 chevron(▶/▼)이 보임 (= QSS `url(*.svg)` 경로 OK)
- [ ] Zotero sync, 논문 목록, PDF 탭 렌더, 검색 동작
- [ ] Preferences/Process 다이얼로그 열림 (= 동결 ui 모듈 번들 OK)
- [ ] (claude CLI 있으면) Extract Biblio 동작 / 없으면 명확한 에러
- [ ] 번들 용량 확인 — excludes 효과 (numpy/scipy 안 들어갔는지)

## 알려진 후속/리스크

- 첫 빌드에서 **아이콘이 안 보이면**: 프로즌 `__file__` 처리 이슈 가능성 →
  `icons.py`/`qss.py`에 `sys._MEIPASS` 인지 리졸버를 넣는 게 fallback 픽스.
  (현 onedir + datas 레이아웃에선 불필요할 것으로 판단)
- PyMuPDF/PyQt6 hidden import 누락 시 런타임 ImportError → 메시지 보고 spec
  hiddenimports 추가.
- 앱 아이콘(`.ico`), 버전 정보, 코드사이닝은 후속 과제.
- 배포 편의(installer, 단일 zip 자동화)는 필요 시 추가.
