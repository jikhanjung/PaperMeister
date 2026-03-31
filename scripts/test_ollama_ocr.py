"""
Ollama glm-ocr 로컬 OCR 테스트 스크립트.

docs/2937.pdf 의 첫 페이지를 Ollama glm-ocr 모델로 OCR 처리한다.
Usage: python test_ollama_ocr.py [--pages N] [--pdf PATH]
"""

import argparse
import base64
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path

import fitz
import requests
from PIL import Image

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "glm-ocr:latest"
DEFAULT_PDF = "docs/2937.pdf"
OUTPUT_DIR = "docs/ocr_results"


def render_page(pdf_path: str, page_idx: int, dpi: int = 150, quality: int = 85) -> str:
    """PDF 페이지를 base64 JPEG로 렌더링."""
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = doc[page_idx].get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def ocr_page(image_b64: str) -> str:
    """Ollama glm-ocr로 단일 이미지 OCR."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": "OCR this image. Extract all text exactly as it appears.",
            "images": [image_b64],
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def main():
    parser = argparse.ArgumentParser(description="Ollama glm-ocr OCR test")
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="PDF file path")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to OCR")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI")
    args = parser.parse_args()

    doc = fitz.open(args.pdf)
    total_pages = doc.page_count
    doc.close()
    n_pages = min(args.pages, total_pages)

    print(f"PDF: {args.pdf} ({total_pages} pages)")
    print(f"OCR 대상: 1~{n_pages} 페이지 | DPI: {args.dpi}")
    print(f"Model: {MODEL} @ {OLLAMA_URL}")
    print("=" * 60)

    pages_result = []

    for i in range(n_pages):
        print(f"\n[Page {i + 1}/{n_pages}] 렌더링 중...")
        img_b64 = render_page(args.pdf, i, dpi=args.dpi)
        print(f"  이미지 크기: {len(img_b64) * 3 // 4 // 1024} KB")

        print(f"  OCR 요청 중...")
        t0 = time.time()
        text = ocr_page(img_b64)
        elapsed = time.time() - t0

        pages_result.append({"page": i + 1, "text": text, "elapsed": elapsed})

        print(f"  완료 ({elapsed:.1f}s)")
        print("-" * 60)
        print(text)
        print("-" * 60)

    # 결과 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf_stem = Path(args.pdf).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON 저장
    json_path = os.path.join(OUTPUT_DIR, f"{pdf_stem}_{timestamp}.json")
    output_data = {
        "pdf": args.pdf,
        "model": MODEL,
        "dpi": args.dpi,
        "processed_at": datetime.now().isoformat(),
        "total_pages": total_pages,
        "ocr_pages": n_pages,
        "pages": pages_result,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 텍스트 저장
    txt_path = os.path.join(OUTPUT_DIR, f"{pdf_stem}_{timestamp}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for p in pages_result:
            f.write(f"=== Page {p['page']} ===\n")
            f.write(p["text"])
            f.write("\n\n")

    print(f"\n결과 저장 완료:")
    print(f"  JSON: {json_path}")
    print(f"  TXT:  {txt_path}")


if __name__ == "__main__":
    main()
