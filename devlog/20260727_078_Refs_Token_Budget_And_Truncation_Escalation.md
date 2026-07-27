# 078 — references 토큰 예산 보정 + 절단 시 에스컬레이션

> 구현 기록 (2026-07-27). 선행: [077](./20260727_077_Biblio_Log_And_Partial_Attribution.md)이
> 심은 `biblio.log`가 바로 원인을 잡아냈다.

## 로그가 준 결정적 증거

077 반영 후 첫 PARTIAL:

```
[16:07:52] [1/6024] End-to-End Object Detection with Transformers
                    — 34 refs PARTIAL (bad JSON x1, 3 refs lost)
```

`biblio.log`:
```
16:07:50 WARNING refs 27/27: bad JSON for batch 3
                 (Expecting value: line 1 column 6545 (char 6544)) → skipping 3 refs
16:07:50 DEBUG   bad JSON body (6544 chars, max_tokens=2322)
  head: '[{"authors": [{"family": "Redmon", ...}], "title": "You only look once", ...'
  tail: '..."title": "Upsnet: A unified panoptic segmentation network", "container": "'
```

**절단 확정.** 파싱이 죽은 위치(char 6544)가 본문의 **맨 끝**이고, tail이 값 중간에서
끊겨 닫는 대괄호가 없다. 모델이 딴소리를 한 게 아니라 `max_tokens`에서 생성이 잘렸다.
077에서 `no_array`와 `bad_json`을 분리해둔 것이 여기서 값을 했다 — 분리 전이었다면
"bad JSON" 한 덩어리로 뭉뚱그려져 방향을 못 잡았다.

## 산식이 얼마나 모자랐나 (실측)

```python
mt = min(8192, max(len(batch) * 256, in_chars // 2) + 1024)   # → 2322
```
역산: `in_chars ≈ 2596`.

로그의 `refs 27/27: 3`은 "엔트리 3개"지만 head를 보면 YOLO·UPSNet 등 레퍼런스가 훨씬
많다. 번호 분할이 안 된 blob 하나가 엔트리 1개로 세어진 것 — 코드 주석이 이미 경고하던
그 함정이고, `in_chars // 2`는 그 완화책이었는데 **계수가 여전히 부족했다**.

측정값:
- 6,544자 / 2,322토큰 = **2.8자/토큰** (`{"family": …, "given": …}`처럼 구두점이 빽빽한 JSON)
- 레퍼런스당 출력 ≈ 300자 ≈ **107토큰** → 기존 주석의 "80~130 tok/entry"와 일치
- 따라서 필요한 출력 토큰 ≈ **입력 문자 × 0.87**

`in_chars // 2`는 0.5배만 줬으니 **약 1.7배 과소**. → `in_chars`로 보정(0.87 + 여유).

## 핵심: 그냥 skip하면 영원히 실패한다

배치 분할도 `mt` 산식도 **입력에 대해 결정적**이다. 같은 논문을 재시도하면 같은 배치가
같은 예산으로 또 잘린다. 즉 DETR은 34/37개로 **영구 PARTIAL**이고, PARTIAL은
`references_checked`가 안 찍혀 `paper.desc()` 정렬상 **매 배치 선두에 계속 돌아온다**.
077 §4의 편지 케이스와 **정확히 같은 구조의 비수렴 버그**다.

그래서 skip 대신 **에스컬레이션**:

1. 절단(`JSONDecodeError`)이면 → **같은 배치를 `_MT_CEILING`(8192)으로 1회 재시도**
2. 그래도 잘리고 배치가 2개 이상이면 → **배치 축소 후 재시도**(타임아웃 경로와 동일)
3. 엔트리 1개가 상한으로도 안 되면 → 그때 skip (PARTIAL)

`boost_at`으로 "이 위치는 이미 상한으로 시도했다"를 기억해 루프를 막는다. 축소는
`_refs_batcher.size > MIN`일 때만 하므로 종료가 보장된다. claude 백엔드는 `mt == 0`이라
1·2를 건너뛰고 기존 동작 그대로다.

## 상한(8192)은 올리지 않았다 — 의도적

`max_tokens`는 vLLM의 KV 캐시 헤드룸 계산에 들어간다. 075/076에서 **엔진이 OOM으로
의심되는 크래시**를 반복한 정황이 있는데, 모든 호출의 상한까지 올리면 그 압력을 키운다.
그래서 **추정만 정확하게** 만들고, 8192는 실패했을 때만 드물게 쓰는 재시도 경로로 남겼다.
(추정이 맞으면 상한은 거의 발동하지 않는다.)

## 검증

`tests/test_refs_partial_reporting.py` **10케이스**(+2):
- 절단 → **같은 배치를 상한으로 재시도해 복구**, 손실 0·`complete=True`, 첫 호출은 추정값
- 상한에서도 절단 → **배치 축소**, 끝내 안 되면 PARTIAL, 배처가 floor까지 내려감(무한루프 없음)
- 기존 8케이스(사유 분리 집계, high는 PARTIAL 유지, fallback+배열부재는 checked-empty,
  fallback이어도 타임아웃이면 checked-empty 아님) 전부 유지

`ruff` clean, `mypy`(게이트 3모듈) clean, 전체 **97 passed**, headless desktop import OK.

## 라이브 검증 — 같은 논문이 통과했다

재기동 후 첫 논문이 바로 그 DETR이었다.

```
before: [1/6024] End-to-End Object Detection ... — 34 refs PARTIAL (bad JSON x1, 3 refs lost)
after:  [1/6023] End-to-End Object Detection ... — 53 references, 6 in library
```

**+19개.** "3 refs lost"로 보고됐던 손실이 실제로는 레퍼런스 19개였다. 잃은 배치의
*엔트리* 3개가 각각 번호 분할이 안 된 blob이라 레퍼런스를 6~7개씩 품고 있었던 것 —
절단된 응답 6,544자 ≈ 레퍼런스 22개 분량과도 맞는다. **blob 가설이 실측으로 확정**됐고,
동시에 토큰 예산이 왜 그렇게까지 빗나갔는지도 설명된다.

### 그래서 지표 이름을 고쳤다: `refs_lost` → `entries_lost`

077에서 넣은 `refs_lost`는 실제로 **배치 엔트리 수**를 센다. 위 사례에서 "3 refs lost"는
진짜로는 19개 손실이었으니 **심각도를 6배 축소 보고**한 셈이다. PARTIAL 로그를 보고
대응 우선순위를 정하게 될 텐데 그 판단을 왜곡한다.

표시도 `3 entries lost`로 바꿨다. 실제 손실 레퍼런스 수는 파싱을 못 했으니 **애초에 알 수
없고**, 아는 척하는 것보다 "엔트리 3개(= 레퍼런스 몇 개인지는 미상)"가 정직하다.

## 관찰 메모

같은 로그의 배처 거동이 건강하다: `1건 42.7s → 1건 5.5s → 2건 8.8s → 4건 14.4s →
8건 33.1s → 8건 62.4s`. 첫 호출 42.7초는 콜드 스타트고 이후 정상 워밍업. 즉 이 논문의
PARTIAL은 서버 문제가 전혀 아니었다.
