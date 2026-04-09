# Chandra2-vLLM Pod (RunPod)

Chandra2 OCR 모델을 RunPod Reserved Pod에서 vLLM으로 서빙하는 Docker 이미지.

## Build

```bash
docker build -t chandra-pod .
```

모델(datalab-to/chandra-ocr-2)이 빌드 시 다운로드되어 이미지에 포함됨.
이미지 크기가 클 수 있음 (~10-20GB).

## RunPod Pod 세팅

1. RunPod > Pods > Deploy
2. GPU: A40 (48GB) 선택
3. Docker Image: `your-registry/chandra-pod:latest` (또는 RunPod에 직접 빌드)
4. Expose HTTP Port: 8000
5. Volume 불필요 (모델이 이미지에 포함)

## 사용

Pod가 시작되면 vLLM OpenAI-compatible API가 `http://<pod-ip>:8000`에서 제공됨.

```bash
# Health check
curl http://<pod-ip>:8000/health

# 모델 목록
curl http://<pod-ip>:8000/v1/models

# OCR 요청 (OpenAI chat completions 형식)
curl http://<pod-ip>:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chandra",
    "messages": [{"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]}],
    "max_tokens": 12384
  }'
```

## PaperMeister 연동

PaperMeister의 OCR 코드(`papermeister/ocr.py`)가 현재 RunPod serverless API를 사용 중.
Pod 사용 시 API endpoint를 Pod의 vLLM 서버 주소로 변경 필요.

## 비용 참고

- A40 reserved: ~$0.39/hr
- 30만 페이지 기준: ~$8-22 (1~3만원)
- Serverless 대비 40-100배 저렴
- **주의: 배치 완료 후 Pod 반드시 종료!**
