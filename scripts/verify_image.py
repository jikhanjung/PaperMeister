#!/usr/bin/env python3
"""Verify the OCR image path works with the installed Pillow / pypdfium2.

Exercises exactly what papermeister/pdfdoc.render_page does to prepare a page
for the OCR server: PDF -> pypdfium2 bitmap -> PIL Image -> JPEG -> base64.

Self-contained: the 1-page PDF below is assembled here rather than authored by
the PDF library, because pypdfium2 renders PDFs and does not write them (this
is what PyMuPDF used to do for us). A literal keeps the script dependency-free
and exercises the real decode path rather than a synthetic bitmap.

Run after bumping Pillow or pypdfium2:

    python scripts/verify_image.py
"""
import base64
import io
import os
import sys
import tempfile


def _minimal_pdf() -> bytes:
    """A valid 1-page PDF with a line of text, offsets computed for the xref."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        None,  # content stream, built below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = b"BT /F1 14 Tf 20 60 Td (PaperMeister image check) Tj ET"
    objs[3] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref_at))
    return bytes(out)


def main() -> int:
    from importlib.metadata import version

    import PIL
    print(f"Pillow {PIL.__version__}, pypdfium2 {version('pypdfium2')}")

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from papermeister import pdfdoc

    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_minimal_pdf())

        pages = pdfdoc.page_count(path)
        if pages != 1:
            raise RuntimeError(f"expected 1 page, got {pages}")
        if pdfdoc.is_encrypted(path):
            raise RuntimeError("plain PDF reported as encrypted")

        img = pdfdoc.render_page(path, 0, dpi=150)
    finally:
        os.unlink(path)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    if img.mode != "RGB":
        raise RuntimeError(f"expected RGB, got {img.mode}")
    if min(img.size) < 50:
        raise RuntimeError(f"page rendered too small: {img.size}")
    if len(b64) < 100 or not b64.isascii():
        raise RuntimeError("base64 output looks wrong")

    print(f"OK — {img.size[0]}x{img.size[1]} page -> {len(buf.getvalue())} B JPEG "
          f"-> {len(b64)} B base64")
    print("PASS: the OCR image path works with this Pillow / pypdfium2.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        sys.exit(1)
