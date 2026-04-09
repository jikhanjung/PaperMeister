# OCR 비용 분석 — Serverless vs Reserved GPU

## 현재 상황

- Zotero 라이브러리: ~10,000편, ~300,000페이지
- OCR 엔진: Chandra2-vllm (RunPod serverless, A40/A6000 48GB)
- 현재 비용: 페이지당 약 4원

## 비용 비교

| 방식 | 단가 | 30만 페이지 비용 | 비고 |
|------|------|----------------|------|
| Serverless (현재) | ~4원/페이지 | **~120만원** | 요청당 과금, cold start 있음 |
| Reserved A40 (~$0.39/hr) | ~0.03~0.1원/페이지 | **~1~3만원** | 시간당 과금, 직접 관리 |

→ Reserved가 **40~100배 저렴**.

## 일반 연구자 기준 (PDF 3,000편)

- 평균 30페이지 × 3,000편 = 90,000페이지
- Serverless: ~36만원
- Reserved: ~1만원
- 텍스트 레이어 활용 시 (OCR 20~30%만): serverless 7~11만원, reserved 수천원

## Reserved GPU 세팅 계획

- GPU: A40 (48GB) — 현재 serverless와 동일 사양
- Docker: 기존 serverless endpoint의 Docker 이미지 재사용 가능
- vLLM continuous batching: 동시 요청 처리로 throughput 3~10배 향상 기대
- 주의: 배치 완료 후 인스턴스 종료 필수 (안 끄면 계속 과금)

## 운영 전략 (하이브리드)

| 용도 | 방식 | 이유 |
|------|------|------|
| 대량 배치 (수천~수만 페이지) | Reserved A40 | 압도적 가격 차이 |
| 일상 소량 (논문 몇 편 추가) | Serverless 유지 | 관리 편의, cold start 허용 |

## 추가 절감: 텍스트 레이어 활용

현재 "일관성을 위해 항상 OCR" 정책이지만, 대부분의 최근 학술 PDF는 텍스트 레이어 보유 (70~80%).
PyMuPDF 텍스트 추출 → 품질 체크 → 충분하면 OCR 스킵하는 2단계 전략 적용 시:

- 300,000페이지 × 20~30%만 OCR = 60,000~90,000페이지
- Reserved A40 기준 수천원 수준

## 다음 단계

- [ ] Reserved A40 인스턴스에 Chandra2-vllm Docker 세팅
- [ ] 소규모 테스트 (100페이지)로 실제 throughput 측정
- [ ] serverless 대비 페이지당 단가 실측
- [ ] 텍스트 레이어 품질 체크 로직 검토 (PyMuPDF 텍스트 추출 → OCR skip 조건)
