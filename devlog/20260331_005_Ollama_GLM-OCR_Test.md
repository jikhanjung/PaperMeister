# Ollama glm-ocr 로컬 OCR 테스트

**날짜:** 2026-03-31
**결론:** glm-ocr 탈락, Chandra2 유지

## 목적

RunPod(Chandra2-vllm) 대신 로컬 Ollama에서 glm-ocr 모델을 사용할 수 있는지 평가.

## 테스트 환경

- **모델:** glm-ocr:latest (2.2 GB) on Ollama
- **API:** `http://localhost:11434/api/generate` (Ollama native endpoint)
- **참고:** https://github.com/zai-org/GLM-OCR/blob/main/examples/ollama-deploy/README.md
- **테스트 스크립트:** `test_ollama_ocr.py`

## 처리 결과

| PDF | 페이지 수 | 총 소요시간 | 페이지당 평균 |
|-----|-----------|------------|--------------|
| `2937.pdf` | 19 | 95.0s | 5.0s |
| `2822.pdf` | 24 | 103.7s | 4.3s |
| `2822_ocr.pdf` | 24 | 101.4s | 4.2s |

결과 파일: `docs/ocr_results/` (JSON + TXT)

## 품질 비교: glm-ocr vs Chandra2 (2937.pdf 1페이지)

### 한국어 인식 오류 (glm-ocr)

| glm-ocr (오류) | Chandra2 | 정답 |
|---|---|---|
| 포항 **복부** | 포항 **북부** | 북부 |
| 연일**충균** | 연일**층군** | 층군 |
| **화전충** | **학전층** | 학전층 |
| **헤면칼플** | **해면침골** | 해면침골 |
| 식물**구소체** | 식물**규모소체** | 식물**규소체** |
| **신출** | **산출** | 산출 |
| **전날**대학교 | **전남**대학교 | 전남대학교 |
| **산타장** | **센터장** | 센터장 |

※ Chandra2도 "식물규소체"를 "식물규모소체"로 오인식 — 완벽하지는 않음

### 영문 오류

- `oxeas` → `oxes` (glm-ocr 학술 용어 오류)
- 저널명/DOI 등 상단 헤더 정보 누락 (glm-ocr)

### 종합 평가

- **영문 본문:** glm-ocr 비교적 양호하나 학술 용어에서 오류 발생
- **한국어:** glm-ocr은 한자어 기반 학술 용어 인식 정확도 심각하게 낮음
- **메타데이터:** glm-ocr은 상단 저널 정보 누락
- **Chandra2:** 대체로 정확하나 한국어 일부 오류 존재

## 결론

glm-ocr(2.2GB 경량 모델)은 한국어 학술 논문 OCR에 부적합.
Chandra2(RunPod)를 OCR 엔진으로 유지한다.
