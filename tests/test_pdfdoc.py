"""The PDF surface, after moving off PyMuPDF (AGPL) to pypdfium2.

The swap was verified against PyMuPDF on the live library before it happened —
page counts and encryption matched everywhere, OCR of pages rendered by each
engine agreed to 0.9991 character similarity. These are the regression tests
for the parts that behaved differently and needed code to paper over.
"""
import os
import tempfile

import pytest

from papermeister import pdfdoc


def _minimal_pdf(text=b'Hello PaperMeister', title=None, author=None) -> bytes:
    """A valid 1-page PDF, optionally carrying Info metadata."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = b"BT /F1 14 Tf 20 60 Td (" + text + b") Tj ET"
    objs[3] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)

    info_ref = b""
    if title is not None or author is not None:
        parts = []
        if title is not None:
            parts.append(b"/Title (" + title + b")")
        if author is not None:
            parts.append(b"/Author (" + author + b")")
        objs.append(b"<< " + b" ".join(parts) + b" >>")
        info_ref = b" /Info %d 0 R" % len(objs)

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
    out += (b"trailer\n<< /Size %d /Root 1 0 R" % (len(objs) + 1) + info_ref
            + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref_at)
    return bytes(out)


@pytest.fixture
def pdf_path():
    made = []

    def _make(**kw):
        fd, path = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as f:
            f.write(_minimal_pdf(**kw))
        made.append(path)
        return path

    yield _make
    for p in made:
        os.path.exists(p) and os.unlink(p)


# ── mojibake repair ─────────────────────────────────────────────
#
# PDFium hands back some metadata decoded byte-per-character, so a UTF-8 title
# arrives as 'SystÃªme' where PyMuPDF gave 'Systême'. Seen on the live library
# in 1 of 300 files — small, but silent, and it lands in Paper.title.

@pytest.mark.unit
def test_mojibake_is_repaired():
    assert pdfdoc._repair_mojibake('SystÃªme silurien') == 'Systême silurien'
    assert pdfdoc._repair_mojibake('BohÃªme') == 'Bohême'


@pytest.mark.unit
def test_ascii_is_left_alone():
    for s in ('', 'Trilobite morphology', 'A. B. Smith 1998'):
        assert pdfdoc._repair_mojibake(s) == s


@pytest.mark.unit
@pytest.mark.parametrize('text', [
    'Systême silurien',      # already correct — must not be double-decoded
    'Bohême',
    '日本産三葉虫の再検討',      # CJK: not Latin-1 encodable, must pass through
    '한국의 삼엽충',
    'Müller & Söderström',
])
def test_correct_text_survives_untouched(text):
    """The repair must be a no-op on text that was already decoded properly, or
    it would corrupt the 99.7% of files that were fine."""
    assert pdfdoc._repair_mojibake(text) == text


# ── the four operations ─────────────────────────────────────────

@pytest.mark.unit
def test_page_count(pdf_path):
    assert pdfdoc.page_count(pdf_path()) == 1


@pytest.mark.unit
def test_plain_pdf_is_not_encrypted(pdf_path):
    assert pdfdoc.is_encrypted(pdf_path()) is False


@pytest.mark.unit
def test_a_corrupt_file_is_not_reported_as_encrypted():
    """It reports False so the OCR path surfaces the real error instead of
    mislabelling it 'encrypted' — the behaviour PyMuPDF gave us."""
    fd, path = tempfile.mkstemp(suffix='.pdf')
    with os.fdopen(fd, 'wb') as f:
        f.write(b'this is not a PDF at all')
    try:
        assert pdfdoc.is_encrypted(path) is False
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_metadata_is_read(pdf_path):
    meta = pdfdoc.read_metadata(pdf_path(title=b'Trilobite morphology',
                                         author=b'Whittington, H. B.'))
    assert meta['title'] == 'Trilobite morphology'
    assert meta['author'] == 'Whittington, H. B.'


@pytest.mark.unit
def test_metadata_of_a_file_without_any(pdf_path):
    meta = pdfdoc.read_metadata(pdf_path())
    assert meta == {'title': '', 'author': '', 'year': None}


@pytest.mark.unit
def test_metadata_of_an_unopenable_file_is_empty():
    """Callers treat metadata as best-effort; a broken file must not raise."""
    assert pdfdoc.read_metadata('/nonexistent/nope.pdf') == {
        'title': '', 'author': '', 'year': None}


@pytest.mark.unit
def test_render_page_gives_an_rgb_image_scaled_by_dpi(pdf_path):
    p = pdf_path()
    img = pdfdoc.render_page(p, 0, dpi=150)
    assert img.mode == 'RGB'
    # 200x120pt at 150dpi -> ~417x250px
    assert 400 < img.width < 430
    assert 240 < img.height < 260
    bigger = pdfdoc.render_page(p, 0, dpi=300)
    assert bigger.width > img.width * 1.9


@pytest.mark.unit
def test_rendered_page_is_not_blank(pdf_path):
    """A page carrying text must produce both dark and light pixels — a blank
    bitmap would still be a valid image and pass every check above."""
    img = pdfdoc.render_page(pdf_path(text=b'PaperMeister'), 0, dpi=150)
    grey = img.convert('L')
    levels = set(grey.get_flattened_data() if hasattr(grey, 'get_flattened_data')
                 else grey.getdata())
    assert min(levels) < 100, 'no dark pixels — nothing was drawn'
    assert max(levels) > 200, 'no light pixels — page is not white'
