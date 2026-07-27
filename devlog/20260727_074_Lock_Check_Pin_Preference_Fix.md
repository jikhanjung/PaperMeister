# 074 — lock-check가 upstream 릴리스마다 red 되던 문제

> 구현 기록 (2026-07-27). 대상: [073](./20260724_073_CI_Parity_Lockfiles_CodeQL_Version_Test.md)에서 도입한 `make lock-check`

## 증상

7/26 push에서 Security 워크플로 실패. Tests·CodeQL은 그린.

```
requirements.lock is out of date. Run 'make lock' and commit.
< pytz==2026.2
> pytz==2026.3.post1
make: *** [Makefile:28: lock-check] Error 1
```

`requirements.txt`는 건드린 적이 없다. pytz는 pyzotero의 전이 의존이고,
2026.3.post1이 **7/25에 PyPI에 올라왔을 뿐**이다.

## 원인 — `lock` 과 `lock-check` 의 해석 방식이 달랐다

`uv pip compile`은 pip-tools와 마찬가지로 **출력 파일이 이미 존재하면 그 안의 핀을
선호(preference)** 한다. 여기서 두 타깃이 갈렸다.

| 타깃 | 출력 대상 | 결과 |
|------|-----------|------|
| `lock` | `requirements.lock` (기존 핀 존재) | 바꿔야만 하는 것만 이동 → pytz **2026.2 유지** |
| `lock-check` | `mktemp` **빈 파일** | 선호할 핀이 없음 → 전부 fresh 해석 → pytz **2026.3.post1** |

즉 게이트가 "우리가 re-lock을 빠뜨렸나"가 아니라 **"upstream이 그새 뭘 냈나"** 를
검사하고 있었다. 전이 의존 중 아무거나 릴리스하면 red가 되고, 소스 변경이 0인데도
lock 커밋을 강요당한다. Makefile 주석에 적어둔 의도("stale **relative to the
requirements files**")와도 어긋난다.

로컬 재현이 한 번 꼬였던 지점: `make lock`을 그냥 돌리면 헤더 주석만 바뀌고 pytz는
그대로라 "드리프트 없음"으로 보인다. `--refresh`를 붙여도 마찬가지다 — 캐시 문제가
아니라 **핀 선호** 때문이라서. `--no-cache`로 빈 출력에 컴파일해야 CI와 같은
2026.3.post1이 나온다. 이 비대칭이 그대로 원인이었다.

## 수정

`lock-check`의 temp 파일을 **커밋된 lock으로 seed** 해서 `lock`과 동일한 선호 조건을
주었다. 이제 diff는 requirements 편집에서 온 차이만 남는다.

```make
tmp_run=$(mktemp); tmp_dev=$(mktemp); \
cp requirements.lock $tmp_run; cp requirements-dev.lock $tmp_dev; \
$(COMPILE) requirements.txt -o $tmp_run ...
```

의도적 업그레이드 경로는 별도 타깃으로 분리했다.

```make
lock-upgrade:
	$(COMPILE) --upgrade requirements.txt -o requirements.lock
	$(COMPILE) --upgrade requirements-dev.txt -o requirements-dev.lock
```

## 왜 "핀을 묶어두는" 쪽이 맞나

`lock-check`가 지키는 건 **재현성**(배포 설치본 = CI가 테스트한 그 wheel)이지
최신성이 아니다. 최신성/보안은 이미 두 갈래로 덮여 있다.

- `security.yml`의 pip-audit이 **`requirements.lock`을 그대로** 감사 → 핀 박힌
  버전에 CVE가 뜨면 주간 스케줄로도 잡힌다 (커밋 없어도)
- 업그레이드가 필요하면 `make lock-upgrade`로 **의도적으로** 당긴다

옛 동작대로 `lock`에 `--upgrade`를 상시로 넣는 선택지도 있었지만, 그러면 며칠에 한 번씩
"upstream이 뭔가 냈으니 lock 커밋해라" 알림이 되어 게이트가 소음으로 전락한다. 채택 안 함.

## 검증

- `make lock-check` → `Lockfiles are up to date.` (lock 파일 변경 0)
- `requirements.txt`에 `tabulate` 임시 추가 → **정상적으로 실패**하며 누락 패키지 diff 출력
  → 게이트의 원래 목적은 그대로 살아있음
- `ruff check` clean, `pytest -q` **81 passed**

lock 파일 자체는 손대지 않았다 — 애초에 stale 하지 않았기 때문이다.
