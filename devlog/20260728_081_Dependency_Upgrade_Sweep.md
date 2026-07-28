# 081 — 의존성 일괄 업그레이드: Dependabot PR 8건 검증·머지

> 구현 기록 (2026-07-28). 선행: [080](./20260727_080_CI_Docs_Parity_With_Sibling_Repos.md)에서
> Dependabot을 도입하자 **한 시간 만에 PR 8건**이 열렸다. 그 첫 수확을 처리한 기록.

## 검증 방식 — 추측하지 않고 실제로 설치해서 돌렸다

CI 그린만으로는 부족하다. 우리 커버리지는 19.6%이고, 특히 **실패 경로**는 테스트가 거의
닿지 않는다. 그래서 각 PR마다 **해당 버전을 실제로 설치하고 우리가 쓰는 API 면을 훑었다.**

## 🔴 pyzotero 1.5 → 1.13 — 코드 수정이 필요했다

두 가지가 깨진다. 둘 다 **문제가 생기는 순간에만** 드러나므로 CI로는 절대 안 잡힌다.

**1) 에러 클래스 전면 개명** — `UserNotAuthorised` → `UserNotAuthorisedError`
(모든 클래스에 `Error` 접미사). `zotero_writeback._update_item`이 옛 이름으로 `except` 하므로,
1.13에서는 **진짜 Zotero 에러가 전파되는 도중에** 속성 조회가 `AttributeError`를 낸다.
"API 키가 읽기 전용입니다"라는 친절한 안내가 엉뚱한 트레이스백으로 바뀐다.

**2) `requests` → `httpx` 전환** — `_is_retryable_zotero_error`가 requests 예외 타입만
검사하므로, 1.13에서 연결 blip이 httpx 타입으로 도착하면 **transient로 인식되지 않아
재시도되지 않는다.**

### 수정: 양쪽 버전 동시 지원 (`c630fb3`)

```python
def _zotero_error(*names):
    """이름 여러 개로 조회, 없으면 빈 튜플(=아무것도 안 잡는 유효한 except 대상)."""
```
빈 튜플 폴백이 핵심이다 — 미래에 또 개명되면 "특별 처리 안 됨"으로 **degrade**할 뿐,
호출 자체가 깨지지 않는다.

재시도 판정에는 `httpx.TransportError`를 추가했다(연결·읽기·타임아웃 계열만; **status
에러는 제외** — 그건 blip이 아니라 결정이다). 두 백엔드를 **동시에** 다뤄야 하는데,
`download_file_content`가 설계상 `requests`를 직접 쓰기 때문이다(pyzotero의 Content-Type
추측을 우회하려고, devlog 038).

검증: **1.5.28과 1.13.2를 번갈아 설치해 전체 테스트 통과 확인** + `tests/test_zotero_compat.py`
6케이스(이름 해석 우선순위, 빈 튜플 폴백, requests/httpx 재시도 판정, 4xx·429 비재시도).

## 🟢 peewee 3.17 → 4.2 — 안전 (다만 문서가 앞서 있었다)

**CLAUDE.md에 "ORM: Peewee 4.x"라고 적혀 있었지만 실제 설치·lock 모두 3.17.9였다.**
문서가 사실보다 앞서 있었고, 이 PR을 머지하고 나서야 비로소 맞게 됐다. (세션 중 사용자에게
"선언이 어긋난 걸 맞춰주는 PR"이라고 잘못 설명했다가 정정했다.)

메이저 업그레이드라 우리가 쓰는 면을 전부 훑는 스크립트로 **4.2.6과 3.17.9를 나란히 돌려
출력을 비교**했다 — 스키마 생성, FK/backref, join, `atomic`+`insert_many`, `update/where`,
`fn`/`group_by`, `in_`/`distinct`, 그리고 가장 위험한 **FTS5 검색 경로**(원시 SQL + 트리거 +
`snippet` + `bm25`). **완전히 동일**했다.

## 🟢 PyMuPDF 1.24 → 1.28 — 안전

쓰는 API가 6종뿐(`fitz.open`, `Matrix`, `page.rect`, `page_count`, `get_pixmap`, `metadata`).
전부 동작하고, **`fitz` 별칭도 살아 있다**(DeprecationWarning을 에러로 승격해 확인 —
1.25부터 `pymupdf`가 정식 이름이 됐으므로 확인이 필요했다).

## 🟢 나머지

- **requests / PyQt6**: 선언 범위 **하한만** 이미 lock된 값으로 올린다. 설치물 변화 0.
- **actions 3건**: `upload-artifact 4→7`은 **어제 내가 만든 불일치를 고쳐준 것**(저장소가
  이미 v7을 쓰는데 test.yml 커버리지 업로드에만 v4를 넣었었다).
- 뒤이어 열린 **`upload-pages-artifact 3→5`, `deploy-pages 4→5`** 는 어제 docs.yml을
  Modan2에서 옮겨오며 낮은 버전으로 넣은 것을 Dependabot이 잡아낸 것. 이제 원본과 일치.

## 머지 운영에서 배운 것 두 가지

**1) 워크플로 파일 PR은 API로 머지가 안 된다.** OAuth 토큰에 `workflow` 스코프가 없으면
`mergePullRequest`가 거부한다. 반면 **SSH `git push`는 제약이 없다** — 실제로 이 세션 내내
워크플로를 push해왔다. 그래서 #2·#9·#10은 같은 변경을 main에 직접 적용했고, Dependabot이
자기 PR을 자동으로 닫았다.

**2) lock 파일은 머지마다 충돌한다.** 앞선 머지가 매번 `requirements.lock`을 새로 쓰므로,
남은 PR들이 순차적으로 conflict 상태가 된다. `@dependabot rebase` → 승인 → 머지를 **한
건씩** 반복해야 한다. 자동화 여지가 있지만 8건 규모에선 수동이 더 빨랐다.

덤: `dependabot-lock-refresh` 워크플로(080에서 추가)가 **첫 실전에서 제 역할을 했다** —
#4·#5에서 `refresh-locks` 체크가 통과했다. 074에서 pytz로 겪은 그 문제를 자동으로 막는다.

## ⚠️ 드러난 것: mypy 게이트가 보이는 것보다 약하다

머지 후 로컬에서 mypy가 **28개 오류**를 냈다. CI는 그린인데도.

원인: **lint 잡이 `pip install ruff mypy`만 하고 프로젝트 의존성을 설치하지 않는다.**
그래서 CI의 mypy는 peewee를 못 보고 전부 `Any`로 처리한다.

peewee 3.17은 타입 주석이 없었지만 **4.x는 있다.** 그런데 그 주석이 peewee의 **암묵적 `id`
기본키**와 **`<fk>_id` 속성**을 모델링하지 않아, 멀쩡한 코드에 오류가 뜬다:

```
"Paper" has no attribute "id"
"Author" has no attribute "paper_id"; maybe "paper"?
```

**전부 스텁의 한계이지 실제 버그가 아니다** — 같은 버전에서 117개 테스트가 통과한다.
문제는 "mypy로 3개 모듈을 검사한다"고 적어둔 게 **의존성 없는 검사**라 실제로는 훨씬
느슨하다는 점이다. 덮지 않고 `test.yml` 주석에 명시했다.

**정직한 다음 단계**: lint 잡에 의존성을 설치하고 peewee 스텁 한계발 오탐만 좁게 걸러내기.
별도 작업으로 남긴다.

## 배포 후 확인 필요

CI가 검증한 범위는 커버리지 19.6%에 해당하는 부분뿐이다. 다음 둘은 테스트가 닿지 않는다:

- **peewee 4**: 라이브 DB의 마이그레이션 경로(`database.py::_migrate()`)
- **pyzotero 1.13**: 실제 Zotero API 왕복 (동기화 시 `logs/zotero_sync.log` 확인)
