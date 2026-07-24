# 073 — CI 패리티: lockfile + CodeQL + 버전 일치 테스트

> 구현 기록 (2026-07-24). 근거: `../CTHarvester/docs/CI_RECOMMENDATIONS_FOR_MODAN2.md`
> (CTHarvester가 Modan2에 역제안한 CI 개선안) + Modan2의 채택 검토
> (`../Modan2/devlog/20260724_R06_...`, 구현 244). Modan2가 최근 채택한 것과 동등하게 맞춤.

## 권고 4건 대비 PaperMeister

| # | 권고 | 결정 |
|---|---|---|
| 1 | Lockfile + `--require-hashes` + `lock-check` | ☑ 추가 |
| 2 | CodeQL SAST | ☑ 추가 |
| 3 | ruff `S`(bandit) | **이미 있음**(P15 Phase 1부터) — 앞섬 |
| 4 | 버전 단일소스 테스트 | ☑ 추가(경량) |

CHANGELOG 소싱 릴리스 노트·commit-count build number도 이미 보유(v0.1.1에서 완성).

## 1. Lockfile (재현 가능 빌드)

느슨한 `requirements.txt`(범위 지정)는 CI·기여자·릴리스가 각기 다른 wheel을 resolve할 수 있음
(CODE_QUALITY_GUIDE §6 경고). `uv pip compile --universal --python-version 3.12 --generate-hashes`로
2개 락 생성:
- `requirements.lock` (runtime, from `requirements.txt`)
- `requirements-dev.lock` (runtime+dev, from `requirements-dev.txt`)

`--universal`이라 Linux/macOS/Windows 매트릭스에 한 파일. **CI·release는 `pip install
--require-hashes -r <lock>`** 로 설치 → 배포 설치본이 CI가 테스트한 바로 그 패키지임이 증명됨.
`Makefile`의 `lock`/`lock-check`(임시 재컴파일 후 헤더 제외 diff) + `security.yml`의 **lock-check
job**(`make lock-check`)으로 의존성 변경 후 re-lock 누락을 게이팅. 결정: 소스는 `requirements.txt`
+ `requirements-dev.txt`(후자가 `-r requirements.txt` 포함), PY_FLOOR=3.12(앱 타깃).
- reusable_build 3레그·test.yml 전부 lock 설치로 전환. pyinstaller는 빌드툴이라 별도 설치(비해시).

## 2. CodeQL (`codeql.yml`)

pip-audit(의존성 CVE)가 못 보는 **자체 코드 data-flow 분석**(injection/path traversal/tainted
file). GitHub 네이티브·무료·무유지보수. push-to-main + 주간 + PR. `paths-ignore`: tests/devlog/
docs/build/dist/.build-venv. 의존성 설치 불필요(추출만).

## 3. 버전 일치 테스트 (`tests/test_version_consistency.py`)

PaperMeister의 버전 표면은 작음 — `version.py`(진실), `.iss.template`(`{{VERSION}}` 파생),
`pyproject.toml`(version 필드 없음), `CHANGELOG.md`(버전 헤더). 테스트: (a) semver 형식,
(b) **현재 버전의 CHANGELOG 섹션 존재**(태그 전 CHANGELOG 갱신 강제), (c) 인스톨러 템플릿이
하드코딩 아닌 placeholder 사용, (d) pyproject가 diverging 버전 하드코딩 안 함.

## 채택 안 함 (문서 §Not recommended 동의)
dependency-review(PR only·pip-audit 중복), 전용 성능 워크플로, README 배지 봇. `ruff format` 게이트는
포맷 패스 전까지 계속 보류(P15).

## 검증
`make lock-check` 통과, `--require-hashes` resolve 확인, ruff clean, **81 tests**(버전 4 추가) green,
YAML 6개 유효. CodeQL·lock-check·lock 설치 라이브는 첫 CI push가 확인.
