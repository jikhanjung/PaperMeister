# 080 — Modan2/CTHarvester 프로세스 정렬: CI 격차 + Sphinx 매뉴얼

> 구현 기록 (2026-07-27). 요청: "../Modan2, ../CTHarvester 에 각종 테스트와 CI, release
> 만드는 방법 기록이 잘 되어 있으니 PaperMeister도 그 프로세스를 충실히 따르면 좋겠어."
> 이어서: "매뉴얼도 그 두 repo 참고해서 만들어야 한다."

073에서 한 차례 맞춘 뒤 벌어진 격차를 다시 좁혔다. 처음부터 만드는 게 아니라 **차분(diff)**
작업이었다.

## 격차 목록

| 항목 | 두 리포 | 우리(이전) | 조치 |
|------|---------|-----------|------|
| `dependabot.yml` | 있음 | **없음** | 추가 |
| `dependabot-lock-refresh.yml` | 있음 | **없음** | 추가 |
| `manual-release.yml` | 있음 | **없음** | 추가 |
| 커버리지 측정·게이트 | 60%/75% ratchet | **없음** | 추가(18% floor) |
| 복잡도 리포트(C901) | Modan2 있음 | 없음 | 추가(비게이팅) |
| `docs.yml` + 매뉴얼 | 있음 | **없음** | 추가 |
| `test-full.yml` | CTHarvester | 없음 | **미채택** |
| `ruff format --check` | Modan2 게이팅 | 없음 | **보류** |

## 1. Dependabot — P15 판단을 뒤집었다

P15에서는 Dependabot을 "1인 도구에 과잉"으로 **의도적으로 제외**했었다
(devlog 071). 그런데 **오늘 그 부재로 CI가 red가 됐다** — pytz가 새 버전을 내면서
커밋된 lock과 어긋났고(devlog 074), 원인 파악에 시간을 썼다.

`dependabot-lock-refresh.yml`이 정확히 이 문제를 처리한다: requirements 변경 PR에서
lock을 자동 재생성해 lock-check 게이트를 통과시킨다. 판단을 뒤집을 근거가 생겼으므로 채택.

Modan2 것을 그대로 못 쓰고 조정한 부분: 그쪽은 **플랫폼별 lock 3개**(linux/windows/macos),
우리는 `--universal`로 **파일 2개**(runtime/dev). 그리고 우리 `make lock`은 기존 핀을
선호하므로(074) 바뀐 것만 움직인다.

`pull_request_target` + `dependabot[bot]` 게이팅의 안전성 근거는 워크플로 주석에 원문
그대로 옮겼다 — 이건 잘못 이해하면 보안 구멍이 되는 지점이라 요약하지 않았다.

## 2. 커버리지 — 처음으로 측정했다

`papermeister` + `desktop` 기준 **19.6%**. Modan2 ~64%, CTHarvester 75%에 한참 못 미친다.
이 프로젝트의 테스트는 **"픽스마다 회귀 테스트"** 관례로 쌓인 것이라 특정 버그 지점에
집중돼 있고, 넓은 커버리지를 목표로 한 적이 없기 때문이다.

**floor를 18%로 두고 주석에 "이건 회귀 방지용이지 충실함의 주장이 아니다"라고 명시**했다.
숫자를 부풀리거나 게이트를 생략하는 대신, 낮은 값에서 시작해 올리는 ratchet 패턴을 따른다.

스코프는 `papermeister` + `desktop` 두 패키지. `scripts/`는 운영용 일회성 도구라 제외했다
(CTHarvester도 `core`/`ui`/`utils`/`security`만 잡는다).

## 3. 미채택 — 근거를 남긴다

**`test-full.yml`**(야간 전체 테스트): CTHarvester는 성능·스트레스 테스트가 느려서 평상시
분리해두고 야간에 돌린다. 우리는 **전체 111개가 2초**에 끝나 분리할 느린 테스트가 없다.
스케줄 실행의 환경 드리프트 감지 가치는 있지만, security.yml·codeql.yml이 이미 주간
스케줄로 돌고 있어 중복이다.

**`ruff format --check`**: Modan2는 게이팅한다. 우리는 코드가 ruff-format된 적이 없어
채택하려면 **대량 diff 커밋이 선행**돼야 한다(P15에서 이미 보류한 항목). 오늘 배치가
돌고 있어 타이밍도 아니다. 별도 작업으로 남긴다.

## 4. 매뉴얼

`docs/manual/` — Modan2와 동일 골격(conf.py / index / installation / quick_start /
user_guide / faq / troubleshooting / developer_guide / changelog + locale).

**내용은 이식이 아니라 새로 썼다.** 특히 troubleshooting은 **이 프로젝트가 실제로 겪은
장애**로 채웠다 — 502/500 크래시 루프 시그니처와 앱의 대응, PARTIAL의 의미와 사유 읽는 법,
Zotero 403/400, conda DLL 함정, WSL에서 라이브 DB 건드려 인덱스 깨진 건과 복구법. 사람이
실제로 검색할 항목들이다.

두 가지를 single-source로 묶었다:
- `conf.py`가 `version.py`에서 버전을 읽음 → `tests/test_version_consistency.py`가 고정하는
  바로 그 파일이라 문서 버전이 어긋날 수 없음
- `changelog.rst`가 루트 `CHANGELOG.md`를 **include**(복사 아님) → 릴리스 노트와 문서가
  갈라질 수 없음

한국어는 sphinx-intl 스캐폴딩까지. 번역 전에는 문자열 단위로 영어로 폴백하므로 **ko 빌드도
완전한 사이트**가 나온다. `.po`는 커밋해뒀고 번역은 후속. (`.mo`도 커밋 — docs.yml이
컴파일 단계를 두지 않고 sphinx-build가 `.mo`를 직접 읽기 때문. Modan2와 동일.)

로컬 en/ko 빌드 둘 다 성공 확인.

## 후속

- 한국어 `.po` 번역
- GitHub 저장소 설정에서 **Pages source를 GitHub Actions로** 지정해야 첫 배포가 붙는다
- `LOCK_REFRESH_TOKEN` 시크릿(선택) — 없으면 lock은 갱신되지만 PR 체크 재실행이 수동
- `ruff format` 패스 후 게이트 활성화
