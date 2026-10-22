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


# ── one lock for PDFium ─────────────────────────────────────────
#
# PDFium is not thread-safe even across documents, and the app calls it from
# the Text/Figures crop workers, OCR and the PDF tab at once.

@pytest.mark.unit
def test_a_held_document_reads_pages_and_closes(pdf_path):
    with pdfdoc.open_document(pdf_path(text=b'Trilobita')) as doc:
        assert len(doc) == 1
        w, h = doc.page_size(0)
        assert (round(w), round(h)) == (200, 120)
        assert 'Trilobita' in doc.text(0)
        img = doc.render(0, 2.0)
        assert img.mode == 'RGB' and img.size == (400, 240)
    assert not doc._finalizer.alive


@pytest.mark.unit
def test_a_dropped_document_closes_itself(pdf_path):
    """Through our finalizer, which takes the lock; PDFium's own would not."""
    doc = pdfdoc.Document(pdf_path())
    finalizer = doc._finalizer
    del doc
    assert not finalizer.alive


@pytest.mark.unit
def test_every_pdfium_call_holds_the_lock(pdf_path, monkeypatch):
    """Eight threads at once through every entry point; PDFium is never entered unlocked."""
    from concurrent.futures import ThreadPoolExecutor

    path = pdf_path(text=b'PaperMeister', title=b'Trilobites')
    unlocked = []

    class Watched(pdfdoc.pdfium.PdfDocument):
        def _check(self, what):
            if not pdfdoc.LOCK._is_owned():
                unlocked.append(what)

        def __init__(self, *a, **kw):
            self._check('open')
            super().__init__(*a, **kw)

        def __len__(self):
            self._check('len')
            return super().__len__()

        def __getitem__(self, i):
            self._check('page')
            return super().__getitem__(i)

        def get_metadata_dict(self, *a, **kw):
            self._check('metadata')
            return super().get_metadata_dict(*a, **kw)

        def close(self):
            self._check('close')
            return super().close()

    monkeypatch.setattr(pdfdoc.pdfium, 'PdfDocument', Watched)
    expected = pdfdoc.render_page(path, 0, dpi=100).tobytes()

    def everything(_):
        assert pdfdoc.page_count(path) == 1
        assert pdfdoc.is_encrypted(path) is False
        assert pdfdoc.read_metadata(path)['title'] == 'Trilobites'
        assert pdfdoc.page_sizes(path) == [(200.0, 120.0)]
        with pdfdoc.open_document(path) as doc:
            assert 'PaperMeister' in doc.text(0)
        return pdfdoc.render_page(path, 0, dpi=100).tobytes()

    with ThreadPoolExecutor(8) as pool:
        images = list(pool.map(everything, range(40)))
    assert unlocked == []
    assert all(img == expected for img in images)
