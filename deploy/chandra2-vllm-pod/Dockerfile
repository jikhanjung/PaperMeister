FROM vllm/vllm-openai:latest

# Dependencies for batch_ocr.py (PDF rendering + image processing)
RUN pip3 install --no-cache-dir PyMuPDF Pillow

# Download model at build time → baked into image
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download('datalab-to/chandra-ocr-2')"

# Batch OCR script
COPY batch_ocr.py /workspace/batch_ocr.py

# Default directories
RUN mkdir -p /workspace/pdfs /workspace/ocr_json

ENV VLLM_MODEL_NAME=chandra
ENV MAX_MODEL_LEN=12384

EXPOSE 8000

# Start vLLM server. Run batch_ocr.py separately via SSH:
#   python3 /workspace/batch_ocr.py --resume
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server", "--model", "datalab-to/chandra-ocr-2", "--served-model-name", "chandra", "--host", "0.0.0.0", "--port", "8000", "--gpu-memory-utilization", "0.90", "--max-model-len", "12384", "--trust-remote-code"]
