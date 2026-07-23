# P15 — 코드 품질 도입 실행 계획

> 계획 문서 (2026-07-23). 근거: [R01 검토](20260723_R01_Code_Quality_Guide_Adoption.md)
> (원본 `../Modan2/docs/CODE_QUALITY_GUIDE.md`). R01이 "무엇을 왜"를 판단했다면, 이 문서는
> **"어떻게·어떤 순서로"** 구현할지 단계별로 못 박는다. 각 단계는 독립적으로 착수·완료 가능.

## 목표

린트/테스트/CI가 전무한 현 상태에서, **저비용·고효율 순으로** 품질 인프라를 얹는다.
완료 기준: (a) 커밋마다 ruff 통과, (b) 핵심 순수로직 회귀 테스트 존재, (c) Windows 포함 CI가
import 깨짐을 red build로 잡음, (d) 미처리 슬롯 예외가 앱을 조용히 죽이지 않음.

## 제약·원칙 (R01에서 계승)

- **1인·단일 머신 개인 도구** → 배포 지향 항목(코드사이닝/공증, Dependabot, 엄격 coverage gate,
  branch protection 필수화, 성능 벤치 스위트)은 **범위 밖**. 규모 커지면 재검토.
- **WSL 편집 / Windows 실행 분리** → CI에 **Windows 러너 필수**(WSL-only 검증은 사용자 환경 미검증).
- **점진 도입** — 성숙 코드베이스에 새 룰 일괄 적용은 수백 findings. 제로-위반 그룹 먼저, 나머지는
  전용 패스. **bulk `# noqa` 금지** — 고치거나 사유 달아 ignore.
- 커밋은 논리 단위로, 버그 픽스는 회귀 테스트 동반.

## Python 최소 버전 (선결)

코드가 PEP 604 union(`str | None`, `int | None`, `tuple[...]`)을 런타임 어노테이션에 씀 → **최소
3.10**. 계획 착수 전 확정하고 `pyproject.toml`의 `requires-python`·CI 매트릭스 하한에 명시.
(가이드 §5: 최소 버전을 테스트하거나 설치 시 강제 — 암묵 방치 금지.)

---

## Phase 1 — 린트 기반 (ruff)  · 최우선, 저비용

**산출물**
- `pyproject.toml` 신설: `[tool.ruff]` 설정.
  - 룰셋: 기본 `E,F,I,N,UP,B,C4` + **`DTZ`**(naive datetime 15곳)·**`RUF012`**(mutable class default)·
    **`S`**(bandit) + 저위반 `SIM,RET,PIE,A`.
  - Qt 관례: `N802,N803,N806`(camelCase) 전역 ignore + 주석.
  - per-file ignore: `scripts/*`는 `T201`(print) 허용, `S101`(assert) 등 테스트 예외.
  - `line-length` 합의(현 코드 관찰 후, 99 제안).
- `.build-venv/`, `dist/`, `build/`는 exclude.

**절차**
1. 설정 추가 → `ruff check` 전량 스캔(현황 파악).
2. `ruff check --fix` 안전 자동수정(I/UP/SIM 등) → **테스트 없음 상태이므로 diff 눈으로 검토** +
   `python -c "import ..."` 스모크로 회귀 없음 확인.
3. 남은 findings: 그룹별로 고치거나(특히 `DTZ`·`RUF012`) 사유 달아 ignore.
4. `ruff format` 적용은 **별도 커밋**(대량 diff 분리).

**수용 기준**: `ruff check` 0 findings(또는 명시적 ignore만), CI 없이도 로컬 통과.
**주의**: `S`(보안)는 Qt `.exec()` 등 오탐 가능 → 확인 후 정당한 것만 ignore.

## Phase 2 — 테스트 씨앗 (pytest)  · 최우선

**산출물**
- `pyproject.toml`에 `[tool.pytest.ini_options]`: `testpaths=["tests"]`, `--strict-markers`,
  마커 등록(`unit`,`ui`,`integration`).
- `tests/` 디렉토리 + 순수로직 유닛부터:
  - `tests/test_references.py` — **`_score_title`/`resolve_one`** 회귀:
    이번 세션 A/B에서 검증한 케이스를 고정 — 짧은 제목 토큰겹침 FP 차단("On Growth and Form"류),
    near-exact 정규화 제목 FN 회수, year mismatch가 near-exact를 veto하지 않음. **가이드 §3
    "픽스마다 회귀 테스트"의 첫 적용.**
  - `tests/test_biblio_refs.py` — references 섹션 헤딩 탐지(다국어)·엔트리 분할·`complete=False`
    부분결과 계약(HTML-flavored 포함).
  - `tests/test_search.py` — 토크나이저(영문/구문/CJK).
  - `tests/test_server_guard.py` — `ServerGuard` 상태머신(이미 스모크 존재 → 정식화):
    pause@N·blip리셋·resume·cancel.
- **DB 의존 테스트**: peewee `SqliteDatabase(':memory:')` + `bind`로 격리(라이브 DB 미접근).

**수용 기준**: `pytest -m unit`가 WSL headless로 통과. 최소 4개 파일·핵심 로직 커버.

## Phase 3 — CI + 스모크 테스트  · WSL↔Windows 갭 방어의 핵심

**산출물**
- `tests/test_smoke.py` — **import 스모크**: `papermeister/`·`desktop/` 전 모듈을 import
  (pkgutil walk). 버전-온리 심볼·누락 의존·문법 깨짐을 즉시 red로. *가장 저비용 고효율.*
  - 2차(후속): `QT_QPA_PLATFORM=offscreen`로 `MainWindow` 생성까지 — 단 startup에서 Zotero
    sync/DB를 건드리므로 **`PM_SMOKE` 등 no-network/no-autosync 플래그** 선도입 필요(설계 항목).
- `.github/workflows/ci.yml` — 매트릭스 `{ubuntu-latest, windows-latest} × {3.10, 3.12}`:
  1. checkout → setup-python → `pip install -r requirements.txt`(+ dev)
  2. `ruff check` (gating)
  3. `pytest -m "unit or (not ui)"` + import 스모크
  - 외부 의존(`claude -p`, RunPod, Zotero)은 **런타임**이라 CI 불필요 — import/유닛만.
- **처음엔 advisory로 관찰**(그린 확인) → 안정되면 required.

**수용 기준**: PR/푸시 시 Windows·Linux 양쪽에서 import 스모크+유닛+ruff 그린.
**주의**: PyQt6/PyMuPDF의 Windows 러너 설치 가능 여부 초기 확인. offscreen Qt 필수.

## Phase 4 — 런타임 견고성 + pre-commit  · 이미 절반, 마무리

**산출물**
- **전역 `sys.excepthook`** — `desktop/app.py::main()`에 설치: 미처리 예외를 로깅 +
  비치명 `QMessageBox`로 표시(창이 조용히 죽는 것 방지). 기존 `BackgroundTask.failed`·
  ServerGuard 견고성과 backstop 이중화. (가이드 §8. CLI(`cli.py`)는 별도 top-level try/except.)
- (선택) `guard_slot` 데코레이터 — I/O·DB·파싱 하는 사용자 트리거 슬롯에 점진 적용. 부분 커버리지는
  거짓 안심이므로 **적용 목록을 문서화**.
- **`.pre-commit-config.yaml`** — `ruff`(check+format) + 파일 위생 훅(end-of-file-fixer,
  trailing-whitespace, check-merge-conflict, check-added-large-files, check-yaml/json). 로컬 저비용.

**수용 기준**: 미guard 경로 예외가 로그+다이얼로그로 표면화. `pre-commit run --all-files` 통과.

## Phase 5 — 의존성·타입·데드코드  · 중간 우선

**산출물**
- **의존성**: `requirements.txt` → runtime/dev 분리(`requirements-dev.txt`: ruff/pytest/mypy/vulture)
  + 버전 핀. 락파일은 **conda+venv 혼용 특수성**(devlog 061) 때문에 무거운 pip-tools보다
  **"검증된 클린 리빌드 1커맨드 문서화"**(`build_desktop_clean.bat` 계보)를 우선. `pip-audit` 1회.
- **타입체크**: `mypy`를 코어 순수모듈(`references.py`,`biblio.py`,`search.py`)에 **한정** 도입,
  `[[tool.mypy.overrides]]` 화이트리스트로 확장. 모듈이 clean해지면 그 모듈만 gating.
- **데드코드**: `vulture` 1회 — `papermeister/ui/`(동결) vs `desktop/`(신규) 병행 구현,
  멀티패스 OCR 등에서 dead/parallel 경로 표면화(가이드 §13). 삭제는 테스트 대조 후 신중히.

**수용 기준**: dev 의존 분리, 코어 3모듈 mypy clean, vulture 리포트 1회 검토.

## Phase 6 — 패키징 검증·인코딩 마무리  · 경량

- **패키지 아티팩트 스모크**(가이드 §7): `.exe` 빌드 후 clean 환경에서 실행 체크리스트를 문서화
  (Qt/SQLite/PyMuPDF/FTS5/Zotero import). 이미 P02에서 수동 검증했으나 **체크리스트로 정착**.
- **인코딩 마무리**(가이드 §10): `open()` without `encoding=` 잔여 3곳(`main.py`,`refs_progress.py`)
  수정 + 출처 불명 텍스트는 tolerant decode(utf-8-sig→locale→latin-1) 확인. (대부분 이미 양호.)

---

## 단계 의존성·순서

```
Phase 1 (ruff) ──┬─► Phase 3 (CI: ruff gating)
Phase 2 (pytest)─┘        │
                          ▼
        Phase 4 (excepthook + pre-commit) ─► Phase 5 (deps/types/deadcode) ─► Phase 6 (packaging/encoding)
```
- **Phase 1+2를 첫 PR**(R01 §5 제안)로 묶어 착수 → Phase 3 CI가 그 둘을 gating.
- Phase 4~6은 독립적이라 여유 있을 때 순차.

## 범위 밖 (재확인)

코드사이닝/공증, Dependabot/Renovate, 엄격 coverage gate(diff-cover), branch protection 필수화,
성능 벤치 스위트, hypothesis 대규모 fuzz — 1인 개인도구 단계에선 과잉. 배포 확대 시 R02에서 재검토.

## 비고

- 각 Phase 구현 완료 시 devlog `999`(구현 기록) 남김. 이 P15는 살아있는 로드맵으로, 완료분은 체크.
- R01(판단) → P15(실행계획) → 999(기록)의 3단 구조. 후속 감사는 R02로.
