# R03 — 라이선스 감사: 배포본은 무슨 라이선스인가

2026-08-13

> ⚠️ 법률 자문이 아니다. 아래는 **확인 가능한 사실**(각 패키지가 스스로 선언한
> 라이선스)과 그로부터 나오는 통상적 해석이다. 최종 판단은 저작권자 몫이다.

## 발단

Preferences의 About 탭에 버전과 라이선스를 표시하려다, "우리 라이선스가 뭐지?"에
답할 수 없다는 걸 알았다. **PaperMeister에는 LICENSE 파일이 아예 없었다.**

## 실측: 런타임 의존성의 라이선스

추측하지 않고 설치된 패키지 메타데이터(`License-Expression`)와 동봉된 라이선스
파일 첫 줄에서 읽었다.

| 패키지 | 버전 | 라이선스 | 성격 |
|---|---|---|---|
| **PyQt6** | 6.11.0 | **GPL-3.0-only** | 강한 copyleft |
| **PyMuPDF** | 1.28.2 | **AGPL-3.0** 또는 Artifex 상용 | 가장 강한 copyleft |
| Pillow | 12.3.0 | MIT-CMU | permissive |
| requests | 2.34.2 | Apache-2.0 | permissive |
| peewee | 4.3.0 | MIT | permissive |
| pyzotero | 1.13.5 | Blue Oak Model License 1.0.0 | permissive |
| platformdirs | 4.11.2 | MIT | permissive |

copyleft는 **둘뿐**이고, 둘 다 GUI/PDF라는 핵심 경로에 있다.

## 핵심 구분: 내 소스 ≠ 배포하는 바이너리

혼동의 원인이 여기다.

| | 누가 정하나 | PaperMeister의 경우 |
|---|---|---|
| **내 소스코드**의 라이선스 | 저작권자(우리)가 자유롭게 | 무엇이든 가능 |
| **배포하는 결합저작물** | 링크된 copyleft 조건이 지배 | **AGPL-3.0** |

GPL/AGPL은 "감염"이 아니라 **배포 조건**이다. 링크한 결과물을 남에게 주는 순간
발동한다. 사내/개인용으로만 쓰면 아무 의무도 없다. 우리는 GitHub Releases로
설치본·AppImage·DMG를 배포하므로 해당된다.

**경계는 "copyleft 라이브러리를 함께 배포하는가"다.**

| 배포 형태 | PyQt6/PyMuPDF를 배포하나 | 결과 |
|---|---|---|
| **소스만** (저장소) | ❌ 사용자가 각자 `pip install` | 우리 라이선스만 적용. GPL 의무 없음 |
| **PyInstaller 번들** (설치본·zip·AppImage·DMG) | ✅ Qt DLL과 함께 통째로 들어감 | **결합저작물 → AGPL-3.0** |

즉 저장소를 클론해서 쓰는 사람에게는 우리 라이선스만 걸리고, **릴리스 아티팩트를
받는 사람**에게 AGPL이 걸린다.

덧붙여 이건 해석이 갈리는 문제가 아니다 — **Riverbank(PyQt 저작권자)가 명시적으로**
"GPL 아니면 상용 라이선스"라는 입장이고 무료 배포판을 GPL v3로만 제공한다.
저작권자 본인의 입장이라 실무상 다툴 여지가 적다.

둘 중 강한 쪽이 이긴다 → **PyMuPDF의 AGPL-3.0이 배포본의 실효 라이선스.**

소스 제공 의무는 저장소가 공개라 사실상 이미 충족돼 있다.

## 형제 프로젝트 대조 (Modan2)

같은 질문을 Modan2에도 던졌다. `requirements.txt` 실측:

- copyleft는 **`pyqt5` 하나뿐**(PyQt6와 같은 Riverbank의 GPL-3.0/상용 이중 라이선스)
- 나머지는 전부 permissive — numpy·scipy·pandas·scikit-learn·statsmodels·
  matplotlib·trimesh·pyopengl(BSD 계열), opencv-headless(Apache-2.0),
  peewee·platformdirs(MIT), pillow(MIT-CMU)
- **PyMuPDF가 없어 AGPL은 안 걸린다** → 배포본은 GPL-3.0

Modan2의 `LICENSE`(MIT)는 **소스에 대해서는 정확하다.** MIT는 GPL과 호환되므로
결합도 합법이고, 누군가 Modan2 소스를 MIT 조건으로 가져다 쓰는 것도 유효하다.
빠진 것은 "배포되는 설치본 전체는 GPL-3.0"이라는 한 줄뿐이다. 파이썬 Qt 앱에서
매우 흔한 누락이다.

| | copyleft 요인 | 배포본 실효 라이선스 | 표기 상태 |
|---|---|---|---|
| Modan2 | PyQt5 | GPL-3.0 | MIT (소스 기준 정확, 배포물 언급 없음) |
| PaperMeister | PyQt6 + **PyMuPDF** | **AGPL-3.0** | 없었음 |

## 선택지 (작업량 실측 포함)

우리가 PyMuPDF로 하는 일은 딱 두 가지다 — 오늘 `fitz`→`pymupdf` rename하면서
전수 확인했다:

1. `open` + `metadata` + `page_count` → PDF 메타데이터
2. `get_pixmap` + `Matrix` → 페이지를 이미지로 렌더(OCR 전송, PDF 탭)

호출 지점 **13곳**(제품 코드 8곳, 나머지는 스크립트).

| | 내용 | 작업량 | 배포본 라이선스 |
|---|---|---|---|
| **A** | 그대로 둔다 | 0 | AGPL-3.0 |
| **B** | PyMuPDF → **pypdfium2**(Apache-2.0/BSD-3) | 반나절, 13곳 | GPL-3.0 |
| **C** | B + PyQt6 → **PySide6**(LGPL-3.0) | 1~2일, 회귀 위험 | MIT 등 자유 |

- **pypdfium2**는 Chromium의 PDFium 바인딩이고 렌더링·메타데이터를 모두 커버한다.
  3플랫폼 휠이 있다. 대안 검토: pdfminer.six(MIT)는 텍스트만, pikepdf(MPL-2.0)는
  렌더 불가, Poppler는 GPL이라 무의미.
- **PySide6**는 Qt 공식 바인딩(LGPL-3.0). 동적 링크 + 교체 가능성 + 고지 조건만
  지키면 permissive 배포가 가능하다. 우리 PyQt6 규모는 **28파일 / import 59줄 /
  `pyqtSignal`·`pyqtSlot` 57곳**. 기계적이지만 작지 않다.
  ⚠️ Modan2가 같은 길을 갈 때는 **더 비싸다** — PyQt5→PySide6는 바인딩 교체에
  **Qt5→Qt6 API 이전**이 겹친다.

## 결정 (2026-08-13, 사용자)

**A — 지금은 AGPL-3.0으로 간다.** 코드 변경이 0이고 배포되는 실물과 일치한다.

**이 선택은 되돌릴 수 있다.** 저작권자가 본인이므로 나중에 B/C로 의존성을 바꾸면
**그 이후 릴리스**를 더 자유로운 라이선스로 낼 수 있다. 이미 배포된 버전만 그대로
남는다. 즉 AGPL 선택이 프로젝트를 영구히 묶지 않는다.

## 반영 (0.1.6)

- [x] **`LICENSE`에 AGPL-3.0 정본** — gnu.org의 `agpl-3.0.txt`를 그대로 받았다
      (661줄 / 34,523바이트). ⚠️ **손으로 쓰거나 옆에 있는 걸 복사하면 안 된다**:
      PyMuPDF의 `COPYING`은 **빈 파일**이고, PyQt6가 동봉한 674줄은 **GPL**-3.0이라
      AGPL이 아니다. 둘은 대부분 같고 §13(Remote Network Interaction)에서 갈리므로
      **틀린 걸 복사해도 눈으로는 잘 안 보인다.** 그래서 설치 후
      "AFFERO"와 "13. Remote Network Interaction"의 존재를 확인했고,
      `tests/test_about.py`가 그 두 가지를 계속 검사한다
- [x] **About 탭** — 버전·설명·링크·저작권 + 라이선스 한 문단 + 서드파티 목록
- [x] **`papermeister/about.py`** — Qt 없이 신원·라이선스 사실만. CLI와 테스트가
      같은 값을 읽는다
- [x] **`tests/test_about.py`** — 표에 적힌 라이선스가 **설치된 배포판이 스스로
      선언하는 것과 맞는지** 검사한다. 메타데이터가 비어 있는 패키지(peewee)는
      동봉 라이선스 파일까지 본다. 또 `requirements.txt`의 모든 런타임 의존성이
      표에 있어야 통과하므로, **새 의존성은 라이선스를 분류해야만 들어온다** —
      copyleft 하나가 조용히 들어오면 배포본 라이선스가 바뀌기 때문
      - 검증: peewee를 GPL이라고 거짓 주장하도록 바꿔보니 정상적으로 실패했다
- [x] README 라이선스 절, `pyproject.toml`의 `license`/`license-files`

## 남은 것

- [ ] Modan2에도 "배포 바이너리는 GPL-3.0" 한 줄 추가 (별건, 소스 MIT는 그대로 두면 됨)
- [ ] B안(pypdfium2) 검토 — AGPL을 벗고 Modan2와 같은 등급이 된다
