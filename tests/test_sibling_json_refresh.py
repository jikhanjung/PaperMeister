"""An OCR JSON sibling another machine replaced on Zotero reaches a machine
that already has the paper's cache — the sync compares Zotero's md5 with
the cache file's and refetches, landing the figures the JSON carries."""
import hashlib
import json
import os
import tempfile

import pytest

from papermeister.figures import PLATE_KIND, PLATE_UNION, AssembledFigure

HASH = 'ab' * 32
PAGES = ['<div data-label="Text" data-bbox="1 1 2 2">x</div>',
         '<div data-label="Image" data-bbox="100 100 900 480"><img alt="a"/></div>']


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-sib-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


class FakeZotero:
    def __init__(self, content: bytes):
        self.content = content
        self.downloads = []

    def download_file_content(self, key):
        self.downloads.append(key)
        return self.content


@pytest.fixture
def paper(db):
    """A processed paper with its cache JSON and a JSON sibling row, and a
    plate row (①) with no caption yet."""
    from papermeister import figure_store
    from papermeister.models import Paper, PaperFile
    from papermeister.paths import OCR_JSON_DIR
    from papermeister.text_extract import ocr_json_filename
    p = Paper.create(title='t', zotero_key='PARENT')
    pdf = PaperFile.create(paper=p, path='a.pdf', hash=HASH, status='processed', zotero_key='PDFKEY')
    figure_store.apply_plan(figure_store.plan_store(pdf, [
        AssembledFigure(page=1, bbox=(100, 100, 900, 480), blocks=((100, 100, 900, 480),),
                        assembly=PLATE_UNION, plate=2, name_hint='Plate 2', page_kind=PLATE_KIND)]))
    name = ocr_json_filename(pdf)
    sib = PaperFile.create(paper=p, path=name, hash='', status='processed', zotero_key='JSONKEY')
    os.makedirs(OCR_JSON_DIR, exist_ok=True)
    local = os.path.join(OCR_JSON_DIR, name)
    with open(local, 'w', encoding='utf-8') as f:
        json.dump({'pages': [{'page': i, 'markdown': t} for i, t in enumerate(PAGES)]}, f)
    return pdf, sib, local


def _remote_with_caption(pdf, local):
    """What the other machine uploaded: the same pages plus a linked caption."""
    from papermeister import figure_share
    from papermeister.models import Figure
    row = Figure.get(Figure.paper_file == pdf.id)
    row.caption, row.caption_source, row.link_key, row.name = 'PLATE 2. Oistodus.', 'explanation_page', 'k', 'Plate 2'
    row.linked_at = __import__('datetime').datetime.fromisoformat('2026-09-22T10:00:00')
    row.save()
    data = json.load(open(local, encoding='utf-8'))
    data['figures'] = figure_share.export_figures(pdf, PAGES)
    # undo locally: this machine has not seen the caption
    row.caption, row.caption_source, row.link_key, row.linked_at = '', '', '', None
    row.save()
    return json.dumps(data, ensure_ascii=False).encode('utf-8')


@pytest.mark.unit
def test_a_replaced_sibling_is_refetched_and_its_figures_land(paper):
    from papermeister.ingestion import _refresh_sibling_json
    from papermeister.models import Figure
    pdf, sib, local = paper
    remote = _remote_with_caption(pdf, local)
    client = FakeZotero(remote)
    att = {'key': 'JSONKEY', 'filename': sib.path, 'content_type': 'application/json',
           'md5': hashlib.md5(remote).hexdigest()}  # noqa: S324 — Zotero's content hash
    notes = []
    assert _refresh_sibling_json(sib, att, client, notes.append) is True
    assert client.downloads == ['JSONKEY']
    assert json.load(open(local, encoding='utf-8')).get('figures')
    assert Figure.get(Figure.paper_file == pdf.id).caption == 'PLATE 2. Oistodus.'
    assert any('figures:' in n for n in notes)


@pytest.mark.unit
def test_an_unchanged_or_uncached_sibling_is_left_alone(paper):
    from papermeister.ingestion import _refresh_sibling_json
    pdf, sib, local = paper
    same = open(local, 'rb').read()
    client = FakeZotero(same)
    att = {'key': 'JSONKEY', 'filename': sib.path, 'content_type': 'application/json',
           'md5': hashlib.md5(same).hexdigest()}  # noqa: S324 — Zotero's content hash
    assert _refresh_sibling_json(sib, att, client) is False          # same content: no download
    assert _refresh_sibling_json(sib, {**att, 'md5': ''}, client) is False   # no md5 from Zotero
    assert _refresh_sibling_json(pdf, {**att, 'content_type': 'application/pdf'}, client) is False
    os.remove(local)
    assert _refresh_sibling_json(sib, {**att, 'md5': 'ffff'}, client) is False   # no cache: the OCR step fetches
    assert client.downloads == []


def _export_at(pdf, local, stamp, caption=None, linked_at=None):
    """The cache JSON with the file's figures exported as of `stamp`; the row
    carries `caption` (linked at `linked_at`) while exporting and is put back."""
    from papermeister import figure_share
    from papermeister.models import Figure
    row = Figure.get(Figure.paper_file == pdf.id)
    saved = (row.caption, row.caption_source, row.link_key, row.linked_at)
    if caption is not None:
        row.caption, row.caption_source, row.link_key = caption, 'explanation_page', 'k'
        row.linked_at = __import__('datetime').datetime.fromisoformat(linked_at)
        row.save()
    data = json.load(open(local, encoding='utf-8'))
    data['figures'] = figure_share.export_figures(pdf, PAGES)
    data['figures']['exported_at'] = stamp
    row.caption, row.caption_source, row.link_key, row.linked_at = saved
    row.save()
    return data


def _att(sib, remote):
    return {'key': 'JSONKEY', 'filename': sib.path, 'content_type': 'application/json',
            'md5': hashlib.md5(remote).hexdigest()}  # noqa: S324 — Zotero's content hash


@pytest.mark.unit
def test_an_older_zotero_copy_does_not_replace_a_newer_cache(paper):
    """A push from here that failed leaves Zotero behind; the md5 differs but
    the cache is the newer one (2026-10-22: 39 papers went back this way)."""
    from papermeister.ingestion import _refresh_sibling_json
    from papermeister.models import Figure
    pdf, sib, local = paper
    remote = json.dumps(_export_at(pdf, local, '2026-10-19T10:00:00+00:00', 'PLATE 2. old.', '2026-10-19T09:00:00'),
                        ensure_ascii=False).encode('utf-8')
    mine = _export_at(pdf, local, '2026-10-20T10:00:00+00:00', 'PLATE 2. new.', '2026-10-20T09:00:00')
    with open(local, 'w', encoding='utf-8') as f:
        json.dump(mine, f)
    row = Figure.get(Figure.paper_file == pdf.id)
    row.caption, row.linked_at = 'PLATE 2. new.', __import__('datetime').datetime.fromisoformat('2026-10-20T09:00:00')
    row.save()
    notes = []
    assert _refresh_sibling_json(sib, _att(sib, remote), FakeZotero(remote), notes.append) is False
    assert json.load(open(local, encoding='utf-8'))['figures']['exported_at'] == '2026-10-20T10:00:00+00:00'
    assert Figure.get(Figure.paper_file == pdf.id).caption == 'PLATE 2. new.'
    assert any('kept' in n for n in notes)


@pytest.mark.unit
def test_a_newer_stage_in_an_older_zotero_copy_still_lands(paper):
    """The cache was exported later, but the other machine linked a caption
    this one never saw: the row takes it and the cache is written again."""
    from papermeister.ingestion import _refresh_sibling_json
    from papermeister.models import Figure
    pdf, sib, local = paper
    remote = json.dumps(_export_at(pdf, local, '2026-10-01T10:00:00+00:00', 'PLATE 2. Oistodus.', '2026-09-22T10:00:00'),
                        ensure_ascii=False).encode('utf-8')
    mine = _export_at(pdf, local, '2026-10-21T10:00:00+00:00')
    with open(local, 'w', encoding='utf-8') as f:
        json.dump(mine, f)
    assert _refresh_sibling_json(sib, _att(sib, remote), FakeZotero(remote)) is False
    assert Figure.get(Figure.paper_file == pdf.id).caption == 'PLATE 2. Oistodus.'
    rows = json.load(open(local, encoding='utf-8'))['figures']['rows']
    assert rows[0]['caption'] == 'PLATE 2. Oistodus.'


@pytest.mark.unit
def test_a_re_ocr_on_zotero_replaces_the_cache_whatever_its_exports(paper):
    from papermeister.ingestion import _refresh_sibling_json
    pdf, sib, local = paper
    mine = _export_at(pdf, local, '2026-10-21T10:00:00+00:00')
    mine['processed_at'] = '2026-05-01T00:00:00'
    with open(local, 'w', encoding='utf-8') as f:
        json.dump(mine, f)
    theirs = {'pages': mine['pages'], 'processed_at': '2026-10-01T00:00:00'}
    remote = json.dumps(theirs).encode('utf-8')
    assert _refresh_sibling_json(sib, _att(sib, remote), FakeZotero(remote)) is True
    assert json.load(open(local, encoding='utf-8'))['processed_at'] == '2026-10-01T00:00:00'
