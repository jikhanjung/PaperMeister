# 089 — 데스크톱 references 추출을 논문 단위 병렬로

2026-08-13

## 발단

"레퍼런스 추출이 이렇게 오래 걸릴 일이야?"

7/29 실측 이후 2주 동안 코드 커밋 없이 배치만 돌았고, `references_checked`는
4,248편(43%) → 7,761편(78.5%)이 됐다. 남은 2,130편이 현 속도로 약 9일.

## 측정

**추출은 놀고 있지 않았다.** 8월 로그 기준 LLM 요청 26,162건, 요청에 쓴 시간
합계 268.9시간 / 경과 288시간 — **가동률 93%**. 쉬지 않고 도는데 느린 것이다.

먼저 의심한 건 적응형 배처였다. "배치 크기가 시간이 지나며 올라가니 점점
빨라지지 않나?" 로그를 배치 크기별로 집계하면 N=1에서 53.3 s/ref, N=20에서
1.99 s/ref로 **26배 차이**가 나서 그럴듯해 보였다.

**그 수치는 교란된 것이었다.** 배처는 elapsed를 TARGET_LO(25s)~TARGET_HI(130s)
구간에 유지하도록 설계돼 있으므로, N은 참고문헌 길이에 반비례해 정해진다 —
N=20은 짧은 인용이 많은 논문이고 N=1은 거대한 인용 하나다. 즉 sec/ref 차이는
배칭 효과가 아니라 **참고문헌 길이 차이**였다.

같은 레퍼런스 12건을 고정하고 통제 실험을 했다:

| | 결과 | 디코딩 속도 |
|---|---|---|
| 배치 12건 한 번에 | 2.98 s/ref | 21.8 tok/s |
| 1건씩 12번 | 3.66 s/ref | 21.4 tok/s |
| | **1.23배** | **동일** |

**디코딩 속도가 배치 크기와 무관하게 21 tok/s로 고정**이다. 한 요청 안에서
토큰은 어차피 한 개씩 순차 생성되므로, 레퍼런스를 몰아넣으면 생성할 토큰도
비례해서 는다. 배칭이 아끼는 건 호출당 고정비(프리필 + 네트워크) ~1.5초뿐이고,
배처는 이미 그걸 다 걷어간 상태다. **더 기다려도 나아질 여지가 없다.**

동시성은 다른 축이다. 같은 작업을 4스트림으로:

| | wall | 총 처리량 |
|---|---|---|
| 순차 4회 | 47.3s | 21.6 tok/s |
| 동시 4개 | **11.9s** | **86.1 tok/s** |

**3.98배.** 1→6으로 올려도 요청당 지연은 18.7s → 19.5s로 사실상 그대로고 총
처리량만 21.4 → 123.1 tok/s(5.75배)로 는다. vLLM이 동시 요청을 가중치 한 번
읽는 forward pass에 묶기 때문이다 — 디코딩은 메모리 대역폭 병목이라 배칭이
거의 공짜다. 서버도 `/api/stats`에서 `concurrency: 6`을 보고한다.

## 이미 있었다

`scripts/extract_references.py`에는 **`--workers`가 2026-06-25부터 있었다**
(`05c79d6`). 커밋 메시지에 같은 결론이 그대로 적혀 있다 — "vLLM batches
concurrent requests with GPU headroom", "The shared adaptive batcher tolerates
concurrent use (benign int races) — verified with a 4-thread extraction test",
그리고 **"Desktop stays serial for now."**

즉 느렸던 진짜 이유는 **추출을 desktop에서 돌리고 있었기 때문**이다. 오늘
로그에 CLI가 stdout으로 찍는 `[i/N] … ok |` 줄이 0건이다. `--workers`를 가진
쪽으로 아무도 옮겨가지 않았고, desktop은 "for now"인 채 두 달을 보냈다.

## 구현

desktop을 CLI와 같은 방식으로 맞췄다.

**1. DB를 워커 스레드 밖으로.** 이게 핵심이다. 기존 `_do_extract`는 워커
스레드에서 LLM 호출 후 `save_references` + `resolve_paper_references`까지 했다.
직렬일 때는 무해했지만 N개가 동시에 돌면 (a) peewee 연결이 thread-local이라
스레드마다 DB를 열고 (b) SQLite는 writer가 하나뿐이며 (c) `_refs_index` /
`_refs_work_index`를 여러 스레드가 동시에 lazy 빌드한다(주석에 "refs run
serialized, so no race"라고 명시돼 있던 그 전제가 깨진다).

CLI가 이미 택한 분할을 그대로 가져왔다 — 워커는 **LLM 호출만**, 저장·resolve·
인덱스 빌드는 전부 `_on_refs_extracted`에서 **메인 스레드**로. 메인 스레드는
한 번에 한 논문씩 처리하므로 인덱스는 여전히 배치당 한 번만 만들어지고,
SQLite는 동시 writer를 보지 않는다.

**2. 슬롯 방식 드레인.** `_refs_task` 하나 → `_refs_tasks: {paper_id: task}`.
`_drain_refs_queue`가 `if 돌고 있으면 return`에서 `while 슬롯 남으면 채우기`로.
dict가 QThread 참조도 붙들어 준다(GC 방지).

**3. `refs_workers` pref, 기본 4, 1~8로 clamp.** qwen 백엔드에서만 >1 —
claude는 요청을 묶어줄 서버가 없고 병렬로 쏘면 Max 플랜 사용량만 빨리 닳는다.

**4. UI.** 여러 편이 동시에 돌면 `Parsing: <title>` 대신 `Parsing N papers…`.
논문 내 진행바(088에서 겨우 배선한 것)는 **N>1이면 억제**한다 — 서로 무관한
논문들의 배치 카운트 사이를 튀어서 진행처럼 안 보인다.

**5. 재귀 제거.** 파일이 없는 큐 항목에서 `_drain_refs_queue()`를 다시 부르던
경로를 그냥 return으로. 드레인이 루프가 된 이상 호출자가 계속 슬롯을 채우고,
쓸 수 없는 항목이 연달아 있으면 항목마다 한 겹씩 중첩될 수 있었다.

## 안 건드린 것

**`_refs_batcher` 전역 싱글턴.** 처음엔 이게 선행 과제라고 봤는데 `05c79d6`이
이미 4스레드로 검증했고("benign int races"), 오늘 측정에서 동시성이 올라가도
요청당 지연이 변하지 않으므로 배처가 보는 타이밍 신호 자체가 왜곡되지 않는다.
GIL 아래 int 대입이라 깨질 것도 없다. 다만 백오프는 스레드 수만큼 겹칠 수
있으니 — 현재 TARGET_HI(130s) 초과 호출이 전체의 1.7%뿐이라 여유는 있다 —
`next batch`가 1~2로 주저앉는지 보고 워커 수를 올리는 게 안전하다.

## 검증

- 새 테스트 13개(`tests/test_refs_concurrency.py`): 슬롯이 하나가 아니라 전부
  차는지 / 완료마다 정확히 하나씩 리필되는지 / pause 중엔 아무것도 시작 안
  하는지 / 큐보다 많이 시작하지 않는지 / 쓸 수 없는 항목에서 재귀 없이 넘어가는지
  / claude는 직렬인지 / pref 파싱·clamp. 스케줄링 메서드를 MainWindow에서
  unbound로 떼어 가벼운 stand-in에 붙였다 — 진짜 코드를 돌리면서 앱 전체와 DB를
  띄우지 않기 위해서.
- 전체 164 passed, ruff·mypy clean.
- `python -m desktop --self-test` offscreen 통과(임시 데이터 디렉터리).

## 남은 것

라이브에서 `refs_workers=4`로 실제 처리율을 재보는 것. 남은 2,130편이 9일에서
2일 남짓으로 줄어야 한다.
