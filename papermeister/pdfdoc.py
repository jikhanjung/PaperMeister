"""The five things PaperMeister asks of a PDF, over pypdfium2.

Page count, whether it is password-protected, its embedded metadata, a page
rendered to an image, and page dimensions. That is the whole surface —
collecting it here is
what made it possible to move off PyMuPDF (AGPL-3.0) to pypdfium2
(BSD-3-Clause / Apache-2.0) and out of the AGPL; see
devlog/20260813_R03_License_Audit.md.

Verified against PyMuPDF on the live library before the swap: page counts and
encryption detection matched on every file, OCR of pages rendered by each
engine agreed to 0.9991 character similarity, and the same image OCR'd twice
is byte-identical, so that residue is the rasterizer rather than model noise.
The differences that remain are sub-pixel edge rendering — the glyphs land in
the same places.
"""
import logging

import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger('ocr')


def _repair_mojibake(s: str) -> str:
    """Undo UTF-8 bytes that were decoded as Latin-1.

    PDFium hands back some metadata strings decoded byte-per-character, so a
    UTF-8 title arrives as 'SystÃªme silurien' where PyMuPDF gave us
    'Systême silurien'. Re-encoding to Latin-1 and decoding as UTF-8 recovers it.

    Only text that is *actually* mis-decoded survives that round trip: a
    correctly decoded Latin-1 'ê' is 0xEA, which is not valid UTF-8 on its own
    and raises, so genuine Latin-1 text is returned untouched.
    """
    if not s or s.isascii():
        return s
    try:
        repaired = s.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return repaired


def open_document(path: str):
    """Open a PDF. Raises pdfium.PdfiumError on a broken or encrypted file."""
    return pdfium.PdfDocument(path)


def page_count(path: str) -> int:
    doc = pdfium.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


def is_encrypted(path: str) -> bool:
    """True if the PDF needs a password.

    A file that cannot be opened at all (corrupt) is reported as *not*
    encrypted, so the normal path surfaces — and records — its real error
    rather than mislabelling it. That matches the previous behaviour.
    """
    try:
        doc = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        return 'password' in str(exc).lower()
    except Exception:
        return False
    doc.close()
    return False


def read_metadata(path: str) -> dict:
    """Embedded title / author / year, or empty values when absent."""
    out = {'title': '', 'author': '', 'year': None}
    try:
        doc = pdfium.PdfDocument(path)
    except Exception as exc:
        logger.debug('metadata: cannot open %s: %s', path, exc)
        return out
    try:
        meta = doc.get_metadata_dict() or {}
    finally:
        doc.close()

    out['title'] = _repair_mojibake((meta.get('Title') or '').strip())
    out['author'] = _repair_mojibake((meta.get('Author') or '').strip())
    for key in ('CreationDate', 'ModDate'):
        raw = meta.get(key) or ''
        if raw and len(raw) >= 6:
            try:
                year = int(raw.replace('D:', '')[:4])
            except (ValueError, IndexError):
                continue
            if 1900 <= year <= 2100:
                out['year'] = year
                break
    return out


def page_sizes(path: str, indices=None) -> list[tuple[float, float]]:
    """Page (width, height) in points, without rasterizing anything.

    The Text tab needs these to reserve space for a figure before its pixels
    exist: OCR gives figure bounds as fractions of the page, and turning those
    into a width and height on screen takes the page's own proportions.

    Pass `indices` to measure only the pages you care about, in that order —
    loading a page costs a few milliseconds, which is nothing for one paper and
    seconds for a 477-page plate volume where a handful of pages hold figures.
    Omit it for every page, in document order.
    """
    doc = pdfium.PdfDocument(path)
    try:
        wanted = range(len(doc)) if indices is None else indices
        return [tuple(doc[i].get_size()) for i in wanted]
    finally:
        doc.close()


def render_page(path: str, page_idx: int, dpi: int = 150) -> Image.Image:
    """One page as an RGB PIL image at `dpi`."""
    doc = pdfium.PdfDocument(path)
    try:
        return doc[page_idx].render(scale=dpi / 72).to_pil().convert('RGB')
    finally:
        doc.close()
