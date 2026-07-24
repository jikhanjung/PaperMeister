#!/usr/bin/env python3
"""Verify the OCR image path works with the installed Pillow / PyMuPDF.

Exercises exactly what papermeister/ocr.py does to render a PDF page for the OCR
server: fitz pixmap -> PIL Image.frombytes('RGB', ...) -> save JPEG -> base64.
Self-contained (builds a 1-page PDF in memory), so it needs no data files.

Run after bumping Pillow (requirements went 10.x -> 12.x):

    python scripts/verify_image.py
"""
import base64
import io
import sys


def main() -> int:
    import fitz
    import PIL
    from PIL import Image

    print(f"Pillow {PIL.__version__}, PyMuPDF {getattr(fitz, 'VersionBind', '?')}")

    # A tiny 1-page PDF in memory.
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((20, 60), "PaperMeister image check", fontsize=14)

    # Mirror ocr._render_page_b64: pixmap -> Image.frombytes -> JPEG -> base64.
    pix = page.get_pixmap(dpi=150)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    if img.size != (pix.width, pix.height):
        raise RuntimeError(f"size mismatch: {img.size} vs {(pix.width, pix.height)}")
    if len(b64) < 100 or not b64.isascii():
        raise RuntimeError("base64 output looks wrong")

    print(f"OK — {img.size[0]}x{img.size[1]} page -> {len(buf.getvalue())} B JPEG "
          f"-> {len(b64)} B base64")
    print("PASS: the OCR image path works with this Pillow / PyMuPDF.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        sys.exit(1)
