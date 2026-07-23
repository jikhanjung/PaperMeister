# R01 — Code Quality Guide 적용 검토

> Review 문서 (2026-07-23). 원본: `../Modan2/docs/CODE_QUALITY_GUIDE.md` v1.0 —
> 크로스플랫폼 데스크톱(Python+Qt) 코드품질 체크리스트 14개 섹션. 이 문서는 그 가이드를
> **PaperMeister에 실제로 어떻게 적용할지** 현재 상태 실측과 함께 판단하고, 우선순위를 정한다.
> (Modan2의 R-series 관례를 도입 — devlog에 `R##` = 리뷰/감사 문서.)

## 0. 적용 가능성 — 높음 (+ PaperMeister 고유 리스크)

가이드는 Modan2(Python+PyQt6, 크로스플랫폼 데스크톱)용으로 쓰였고 PaperMeister도 **동일 스택**이라
대부분 그대로 적용된다. 게다가 이 프로젝트엔 가이드가 강조하는 리스크가 **더 크다**:

- **개발↔실행 환경 분리**: 편집·커밋은 WSL, 실제 실행은 Windows 네이티브(Anaconda). "WSL에선
  멀쩡한데 Windows에서 깨짐"이 구조적 위험 — 이미 겪음(PyInstaller conda DLL 지옥, devlog 061).
  → 가이드 §5(크로스플랫폼 CI)·§7(패키지 아티팩트 스모크)의 가치가 특히 큼.
- **한국어 Windows(cp949) + CJK 논문**: 인코딩/폰트 리스크(§10)가 실사용 데이터에 상존.
- **장시간 무인 배치 + 외부 LLM/OCR 서버 의존**: 견고성(§8)·리소스(§9)가 하루~몇 주 단위로 누적.
- **drvfs 동시접근 DB 손상**(devlog 068) — 가이드엔 없는 이 프로젝트 고유 함정.

단, **1인·단일 머신 개인 도구**라는 점도 사실이다. 배포 대상이 다수 사용자가 아니므로 가이드의
일부 항목(코드사이닝, Dependabot, branch protection, 엄격한 coverage gate)은 **과잉**이다.
이 리뷰의 핵심은 가이드 재진술이 아니라 **무엇이 여기서 가치 있고 무엇이 오버킬인지 판별**하는 것.

## 1. 현재 상태 실측 (2026-07-23)

| 영역 | 상태 |
|---|---|
| 코드 규모 | `papermeister/`+`desktop/` ~14,340줄 / 53파일 (Modan2 32k보다 작음) |
| 린트/포맷 | **없음** (ruff/black/flake8, pyproject.toml/setup.cfg 전무) |
| 타입체커 | **없음** (mypy/pyright 미설정; 부분적 타입힌트만 — "hint rot" 상태) |
| 테스트 | **사실상 0** (`scripts/test_ollama_ocr.py` 수동 스크립트 1개뿐, pytest 스위트 없음) |
| pre-commit | **없음** |
| CI | **없음** (`.github/workflows` 부재) |
| 의존성 | loose `requirements.txt` 7줄, 락파일 없음 |
| 패키징 | PyInstaller onedir 존재(P02), 빌드 스모크는 수동 |
| 전역 excepthook | **없음** — Qt 슬롯 미처리 예외 시 창이 조용히 죽을 수 있음 |
| 인코딩 | `open()` without `encoding=` **3곳뿐**(대부분 지정/바이너리) — CJK 대응 흔적, 양호 |
| 보안 | eval/exec/pickle/unsafe-yaml **없음**, bare `except:` **0** — 양호 |
| datetime | naive `datetime.now()` 15곳 (DTZ 대상) |
| 예외 | `except Exception:` 43곳(상당수 network/best-effort 의도적) |
| 경로 | `os.path` 203 vs `pathlib` 5 (PTH 대상, 기능상 문제는 아님) |

**요약**: 상위 계층(CI/테스트/린트/타입)은 **전무**하지만, 하위 위생(인코딩·보안·bare except)은
**이미 상당히 양호**하다. 견고성은 최근 세션에서 오히려 가이드 §8 원칙을 실천 중 —
아래 참조.

## 2. 이미 잘하고 있는 것 (가이드와 정합)

- **§8 "부분 실패를 성공으로 보고하지 말 것"**: 이번 세션에 정확히 이 버그를 잡음 —
  references 부분 파싱(`complete=False`)을 `references_checked`로 찍던 것을 unchecked 유지로 수정
  (`8c15cdc`). biblio/OCR도 동일 원칙.
- **§8 견고성 패턴**: `BackgroundTask.failed` 시그널, Zotero transient-retry, 그리고 방금 추가한
  서버-다운 pause/resume(`ServerGuard` + OCR 인라인 폴링). 슬롯별 guard의 "부분 커버리지=거짓
  안심"만 아직.
- **§10 인코딩**: OCR JSON/파일 I/O에 인코딩 명시가 습관화(HTML-flavored OCR 처리 등). 3곳만 잔여.
- **§12 보안**: 파일 인제스트 앱인데 eval/exec/pickle 미사용, path 처리도 `os.path.basename`+hash 기반.
- **devlog 관례**: 버그·결정의 서면 기록이 이미 촘촘 — 가이드 §14의 "devlog + R-series"의 절반은 이미 있음.

## 3. 섹션별 판단 (PaperMeister 맥락)

| # | 가이드 섹션 | 여기서의 가치 | 판단 |
|---|---|---|---|
| 1 | 린트/포맷 (ruff) | **높음** — 저비용, DTZ/RUF012/S로 실버그. 14k줄이라 도입 부담 적음 | **채택 1순위** |
| 2 | 타입체크 (mypy) | 중 — 코어 모듈(`references`,`biblio`,`search`)부터 점진 | 채택(범위 한정) |
| 3 | 테스트 전략 | **높음** — 현재 0. 순수로직(스코어러/파서/휴리스틱)부터 | **채택 1순위** |
| 4 | 커버리지 게이트 | 낮음(1인) — 측정은 좋되 엄격 gate는 과잉 | 측정만, gate 보류 |
| 5 | 크로스플랫폼 CI | **높음** — WSL↔Windows 분리 때문. 단 **Windows 러너 필수** | 채택(아래 주의) |
| 6 | 의존성 락 | 중~높음 — conda DLL 지옥(061) 재발 방지. 단 conda+venv 혼용이 특수 | 채택(현실 반영) |
| 7 | 패키지 아티팩트 스모크 | 중 — .exe가 소스와 갈림(061 전례). 수동이라도 체크리스트화 | 채택(경량) |
| 8 | 런타임 견고성 | **높음** — 이미 절반. **전역 excepthook**만 추가하면 큰 이득 | 채택(excepthook) |
| 9 | 리소스/메모리 | 중 — lazy 렌더 등 이미 신경. 장시간 세션 프로파일 1회 | 낮은 우선 |
| 10 | i18n/인코딩/렌더 | 중 — 대체로 양호. 잔여 3곳 + tolerant decode 확인 | 소규모 패스 |
| 11 | 성능 | 낮음 — OCR/LLM(네트워크)이 병목이라 로컬 프로파일 실익 적음 | 보류 |
| 12 | 보안 | **낮음(이미 양호)** — S 룰만 린트에 포함 | 린트로 흡수 |
| 13 | 데드코드/복잡도 | 중 — `papermeister/ui/`(동결) vs `desktop/` 병행, 멀티패스 OCR. vulture 1회 | 중간 |
| 14 | 워크플로 게이팅 | 중 — pre-commit(로컬)은 저비용 고효율. 원격 gate는 1인이라 완화 | pre-commit 채택 |

## 4. 우선순위 적용 계획 (가이드 Appendix A를 이 프로젝트에 맞게 재정렬)

**가장 저비용·고효율부터. 1인 개인도구 현실을 반영해 배포/게이팅 항목은 완화.**

1. **[린트] ruff 도입** (`pyproject.toml`) — 기본(`E,F,I,N,UP,B,C4`) + `DTZ,RUF012,S`.
   `--fix`로 안전한 것 자동수정 후 눈으로 검토. Qt camelCase는 `N802/803/806` ignore.
   *효과: 15개 naive datetime, mutable default, 보안 룰 즉시 스캔.*
2. **[테스트 씨앗] pytest 스위트 시작** — 순수 로직부터: `references.resolve_one`/`_score_title`
   (이번 세션 스코어러), `biblio` 섹션 휴리스틱/엔트리 분할, `search` 토크나이저, `ServerGuard`
   상태머신(이미 스모크 있음 → 정식 테스트로). **버그 픽스마다 회귀 테스트** 관례 시작.
3. **[스모크+CI] headless import/smoke 테스트 + GitHub Actions** —
   모든 모듈 import + `python -m desktop`를 offscreen으로 띄웠다 종료. **Windows 러너 포함**(핵심 —
   WSL만 테스트는 사용자 환경 미검증). Qt/SQLite/PyMuPDF import가 red build로 드러남.
4. **[견고성] 전역 `sys.excepthook`** — 데스크톱 진입(`desktop/app.py`)에 로깅+비치명 다이얼로그
   backstop. 미guard 슬롯 예외가 창을 조용히 죽이는 것 방지.
5. **[pre-commit]** — ruff format/check + 파일 위생(EOF/trailing/large-file/merge-conflict).
   로컬 저비용.
6. **[의존성]** — `requirements.txt`를 runtime/dev 분리 + 버전 핀. 락파일은 conda+venv 혼용
   특수성(061) 고려해 "검증된 클린 리빌드 1커맨드 문서화"를 우선(무거운 pip-tools보다 실효).
7. **[타입체크]** — mypy를 코어 모듈(`references`,`biblio`,`search`,`references.py`)에 한정 도입,
   override 화이트리스트로 확장.
8. **[데드코드]** — `vulture` 1회 실행. `papermeister/ui/`(동결) vs `desktop/` 중복 표면 확인.

**보류/과잉(1인 개인도구 기준)**: 엄격 coverage gate, Dependabot, 코드사이닝/공증,
branch protection 필수화, 성능 벤치 스위트. — 배포 규모가 커지면 재검토.

## 5. 즉시 착수 후보 (다음 세션)

가장 작은 첫걸음으로 **1번(ruff) + 2번(pytest 씨앗 몇 개)**를 한 PR로:
- `pyproject.toml`에 ruff 설정 추가 → `ruff check --fix` → 잔여 수동 검토 → 커밋
- `tests/test_references.py`: `_score_title`/`resolve_one`에 이번 세션 A/B에서 검증한 케이스
  (짧은제목 FP 차단, near-exact FN 회수)를 회귀 테스트로 고정 — **가이드 §3 "픽스마다 회귀
  테스트"의 첫 적용**
- 이후 3번(CI 스모크, Windows 러너)로 확장

## 6. 비고

- 이 R01은 **계획/판단 문서**이며 구현은 별도. 실제 착수 시 devlog `999`(구현 기록)로 남긴다.
- 가이드 원본은 Modan2 `docs/CODE_QUALITY_GUIDE.md`(살아있는 문서, v1.0). 갱신 시 이 검토도 재방문.
- PaperMeister 고유 항목(drvfs DB 동시접근 금지, WSL↔Windows 실행 규칙)은 이미 CLAUDE.md/메모리에
  있으므로, 향후 "프로젝트 운영 규칙"으로 이 가이드 적용분과 통합할지 검토.
