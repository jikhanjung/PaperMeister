FROM vllm/vllm-openai:latest

# Download model at build time → baked into image
# No re-download on every container start
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download('datalab-to/chandra-ocr-2')"

ENV VLLM_MODEL_NAME=chandra
ENV MAX_MODEL_LEN=12384

EXPOSE 8000

# vLLM OpenAI-compatible server
# --gpu-memory-utilization: leave some headroom on 48GB A40
# --max-model-len: matches Chandra2 MAX_OUTPUT_TOKENS
# --trust-remote-code: required for some custom model architectures
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server", "--model", "datalab-to/chandra-ocr-2", "--served-model-name", "chandra", "--host", "0.0.0.0", "--port", "8000", "--gpu-memory-utilization", "0.90", "--max-model-len", "12384", "--trust-remote-code"]
