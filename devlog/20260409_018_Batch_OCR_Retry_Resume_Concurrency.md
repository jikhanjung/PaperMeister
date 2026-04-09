# Batch OCR Retry/Resume/Concurrency 개선

## 배경

Reserved GPU 환경에서 `deploy/chandra2-vllm-pod/batch_ocr.py`를 대량 OCR용으로 돌릴 때,
기존 구현은 다음 문제가 있었다.

- 페이지 요청에 텍스트 프롬프트가 없어 출력 형식 안정성이 낮음
- 일시적 vLLM 오류가 나면 해당 페이지가 즉시 실패 처리됨
- JSON을 최종 파일에 바로 써서 중간 종료 시 손상 파일 위험이 있음
- `--resume`이 "같은 hash의 json 파일 존재 여부"만 보고 skip해서 손상/부분완료 결과를 구분하지 못함
- 실패 페이지가 일부만 남아도 같은 PDF를 다시 돌릴 때 전체 페이지를 다시 처리해야 함
- 기본 처리 방식이 완전 직렬이라 48GB GPU 활용이 보수적임

## Rationale

- OCR 배치는 transient failure를 전제로 설계하는 편이 운영 비용이 낮다.
- 부분 성공 결과를 버리지 않고 재사용해야 reserved GPU 시간을 아낄 수 있다.
- PDF 전체 재처리보다 실패 페이지만 재시도하는 편이 멱등성과 비용 측면에서 유리하다.
- GPU 메모리가 충분한 환경에서는 페이지 단위 동시 요청이 직렬 처리보다 throughput 개선 가능성이 높다.
- 다만 multi-page 단일 request batching보다 page-level parallelism이 현재 실패 페이지 재시도 구조와 더 잘 맞는다.

## 작업 내용

### 1. OCR 요청 안정화

- 이미지-only 요청에 텍스트 지시 추가
  - `Extract all text from this page in markdown.`
- `max_tokens`를 `12384` → `8192`로 조정
- `ocr_page()`에 page-level retry/backoff 추가
  - 기본 3회 재시도
  - backoff: 2초, 4초

### 2. 렌더링 안정성

- `get_pixmap(matrix=mat, alpha=False)`로 고정
- RGB 변환 시 alpha/channel mismatch 가능성 축소

### 3. 저장/재개 안정성

- JSON 저장을 atomic write로 변경
  - `{hash}.json.tmp`에 먼저 기록
  - 완료 후 `os.replace()`로 최종 파일 교체
- `--resume` 판단 강화
  - JSON parse 가능 여부
  - `total_pages`, `done_pages`, `failed_pages`, `pages` 구조 검증
  - `done_pages + failed_pages == total_pages` 확인
  - `failed_pages == 0` 인 경우만 완료본으로 간주

### 4. 실패 페이지 재시도

- 페이지 자체 요청은 내부 retry 3회
- 그래도 실패한 페이지는 PDF 종료 직후 한 번 더 재패스
- 재패스 후 복구되면 해당 PDF는 성공으로 처리
- 끝까지 실패 페이지가 남으면 JSON은 저장하되 파일 집계는 실패로 처리

### 5. 부분 완료 JSON 재사용

- 동일 PDF의 기존 JSON이 부분 실패 상태면 성공 페이지는 그대로 재사용
- `failed_page_numbers`에 기록된 페이지만 다시 OCR
- 완료된 JSON은 partial resume 대상으로 사용하지 않음
- 결과적으로:
  - `--resume` + 완료본 있음 → skip
  - `--resume` + 부분 실패본 있음 → 실패 페이지들만 재처리
  - `--resume` 없이 재실행 → 전체 PDF 재처리

### 6. 페이지 단위 동시 처리

- `--concurrency` 옵션 추가
- 기본값 `4`
- 구현 방식:
  - page별 독립 request를 `ThreadPoolExecutor`로 병렬 실행
  - multi-page single request batching은 도입하지 않음
- 이유:
  - 현재 JSON 구조와 실패 페이지 재시도 로직을 유지하기 쉬움
  - page-level fallback/재개와 충돌이 적음

### 7. 결과 JSON 보강

- `source_pdf`
- `dpi`
- `failed_page_numbers`

## 기대효과

- transient timeout/500/connection reset에 덜 취약해짐
- 중간 종료 후에도 손상 JSON 때문에 `--resume`이 잘못 skip할 가능성 감소
- 부분 실패 PDF 재실행 시 성공 페이지를 재사용해서 GPU 시간 절감
- 실패 페이지 재패스로 전체 파일 성공률 상승 기대
- 기본 `concurrency=4`로 직렬 처리 대비 throughput 개선 가능

## Fallback

- vLLM이 동시 요청에 불안정하면 `--concurrency 1`로 즉시 되돌릴 수 있음
- 부분 완료 JSON 구조가 맞지 않거나 손상되면 partial resume을 무시하고 전체 PDF 재처리
- 재패스 후에도 실패 페이지가 남으면 JSON은 보존하고 다음 실행에서 다시 실패 페이지만 재시도 가능

## 확인 사항

- `python3 -m py_compile batch_ocr.py` 통과
- `python3 batch_ocr.py --help`에서 `--concurrency` 노출 확인

## 다음 단계

- [ ] `--concurrency 2/4/8` 실측 비교로 최적값 결정
- [ ] 실제 vLLM 로그와 GPU utilization 기반으로 throughput 병목 확인
- [ ] 필요 시 `retry_wait_seconds`나 `ocr_timeout`을 CLI 옵션으로 노출
