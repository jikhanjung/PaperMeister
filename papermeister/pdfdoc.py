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

PDFium is not thread-safe — not even for different documents — and the app
calls it from several threads at once: the Text and Figures tabs crop on
worker threads, OCR renders on its own, the PDF tab on the GUI thread. So
every call into it, closing included, goes through `LOCK`. Nothing PDFium
owns leaves a function here: images come back as copies, and a document
held open is a `Document` whose methods take the lock themselves.
"""
import logging
import threading
import weakref

import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger('ocr')

# Reentrant: a `Document` method may run inside a module function that already holds it.
LOCK = threading.RLock()


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


def _close(doc) -> None:
    with LOCK:
        doc.close()


class Document:
    """An open PDF for callers that read several pages; every call takes `LOCK`.

    Closed by `close()`, by leaving a `with` block, or when the last reference
    goes — in each case under the lock, which PDFium's own finalizer would not take.
    """

    def __init__(self, path: str):
        with LOCK:
            self._doc = pdfium.PdfDocument(path)
        self._finalizer = weakref.finalize(self, _close, self._doc)

    def __len__(self) -> int:
        with LOCK:
            return len(self._doc)

    def page_size(self, index: int) -> tuple[float, float]:
        """(width, height) in points."""
        with LOCK:
            page = self._doc[index]
            try:
                return tuple(page.get_size())
            finally:
                page.close()

    def render(self, index: int, scale: float) -> Image.Image:
        """One page as an RGB image, `scale` pixels per point."""
        with LOCK:
            page = self._doc[index]
            try:
                # RGB byte order from PDFium itself, so no channel swap per page
                bitmap = page.render(scale=scale, rev_byteorder=True, prefer_bgrx=False)
                try:
                    return bitmap.to_pil().convert('RGB')   # a copy: the bitmap is freed below
                finally:
                    bitmap.close()
            finally:
                page.close()

    def text(self, index: int) -> str:
        """The page's text layer ('' for a scan without one)."""
        with LOCK:
            page = self._doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    return textpage.get_text_range() or ''
                finally:
                    textpage.close()
            finally:
                page.close()

    def metadata(self) -> dict:
        """The Info dictionary as PDFium decodes it (see `_repair_mojibake`)."""
        with LOCK:
            return self._doc.get_metadata_dict() or {}

    def close(self) -> None:
        self._finalizer()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_document(path: str) -> Document:
    """Open a PDF. Raises pdfium.PdfiumError on a broken or encrypted file."""
    return Document(path)


def page_count(path: str) -> int:
    with open_document(path) as doc:
        return len(doc)


def is_encrypted(path: str) -> bool:
    """True if the PDF needs a password.

    A file that cannot be opened at all (corrupt) is reported as *not*
    encrypted, so the normal path surfaces — and records — its real error
    rather than mislabelling it. That matches the previous behaviour.
    """
    try:
        open_document(path).close()
    except pdfium.PdfiumError as exc:
        return 'password' in str(exc).lower()
    except Exception:
        return False
    return False


def read_metadata(path: str) -> dict:
    """Embedded title / author / year, or empty values when absent."""
    out = {'title': '', 'author': '', 'year': None}
    try:
        doc = open_document(path)
    except Exception as exc:
        logger.debug('metadata: cannot open %s: %s', path, exc)
        return out
    with doc:
        meta = doc.metadata()

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
    with open_document(path) as doc:
        wanted = range(len(doc)) if indices is None else indices
        return [doc.page_size(i) for i in wanted]


def render_page(path: str, page_idx: int, dpi: int = 150) -> Image.Image:
    """One page as an RGB PIL image at `dpi`."""
    with open_document(path) as doc:
        return doc.render(page_idx, dpi / 72)
