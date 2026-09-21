"""Figure results ride in the cache JSON: out of one library's DB, into
another's — matched by identity, guarded by the OCR digest, never over a
person's rows."""
import datetime
import json
import os
import tempfile

import pytest

from papermeister.figures import PLATE_KIND, PLATE_UNION, SINGLE, AssembledFigure

HASH = 'ab' * 32
PAGES = [f'<div data-label="Text" data-bbox="0 0 10 10">p{i}</div>' for i in range(5)]


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-share-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


def make_file(title='A', path='a.pdf'):
    from papermeister.models import Paper, PaperFile
    return PaperFile.create(paper=Paper.create(title=title), path=path, hash=HASH, status='processed')


def processed(pf):
    """A plate that went through link and panels, a body figure, a placeholder, a folded row."""
    from papermeister import figure_store
    from papermeister.models import Figure, FigureEntry, FigurePanel
    figs = [AssembledFigure(page=2, bbox=(100, 100, 900, 480), blocks=((100, 100, 480, 480), (520, 100, 900, 480)),
                            assembly=PLATE_UNION, plate=2, name_hint='Plate 2', page_kind=PLATE_KIND),
            AssembledFigure(page=3, bbox=(100, 100, 900, 600), blocks=((100, 100, 900, 600),), assembly=SINGLE,
                            caption_hint='Fig. 4. x', reasons=('no_caption',)),
            figure_store.placeholder(4, ['plate_without_pictures'])]
    figure_store.apply_plan(figure_store.plan_store(pf, figs))
    plate = Figure.get((Figure.paper_file == pf.id) & (Figure.page == 2))
    now = datetime.datetime.fromisoformat('2026-09-18T12:00:00')   # naive, as the rows store it
    plate.caption, plate.caption_source, plate.caption_pages_json = 'PLATE 2. Oistodus.', 'explanation_page', '[1]'
    plate.link_key, plate.linked_at, plate.name = 'k1', now, 'Plate 2'
    plate.panel_key, plate.paneled_at, plate.kind, plate.is_compound = 'pk', now, 'fossil_plate', True
    plate.save()
    for i, label in enumerate('12'):
        FigureEntry.create(figure=plate.id, order=i, label=label, printed_label=label, description=f'entry {label}')
    FigurePanel.create(figure=plate.id, order=0, label='1', bbox_figure_1000='[0, 0, 480, 1000]', entry_orders_json='[0]')
    FigurePanel.create(figure=plate.id, order=1, label='2', bbox_figure_1000='[520, 0, 1000, 1000]', entry_orders_json='[1]')
    body = Figure.get((Figure.paper_file == pf.id) & (Figure.page == 3))
    body.dismissed, body.dismissed_by, body.user_confirmed = True, 'user', True
    body.save()
    return plate, body


@pytest.mark.unit
def test_export_carries_everything_by_identity(db):
    from papermeister import figure_share as fs
    pf = make_file()
    plate, body = processed(pf)
    data = fs.export_figures(pf, PAGES)
    assert data['file_hash'] == HASH and data['ocr_digest'] and len(data['rows']) == 3
    p = next(r for r in data['rows'] if r['page'] == 2)
    assert p['caption'] == 'PLATE 2. Oistodus.' and p['linked_at'] == '2026-09-18T12:00:00'
    assert [e['label'] for e in p['entries']] == ['1', '2'] and len(p['panels']) == 2
    assert 'id' not in p and p['continuation_of'] is None
    b = next(r for r in data['rows'] if r['page'] == 3)
    assert b['dismissed'] and b['dismissed_by'] == 'user' and b['user_confirmed']
    json.dumps(data)   # serialisable


@pytest.mark.unit
def test_import_creates_a_second_librarys_rows_whole(db):
    from papermeister import figure_share as fs
    from papermeister.models import Figure, FigureEntry, FigurePanel
    src = make_file('A', 'a.pdf')
    processed(src)
    data = {'figures': fs.export_figures(src, PAGES)}
    dst = make_file('B (other library)', 'b.pdf')
    report = fs.import_figures(dst, data, PAGES)
    assert (report.created, report.updated, report.protected) == (3, 0, 0)
    plate = Figure.get((Figure.paper_file == dst.id) & (Figure.page == 2))
    assert plate.caption == 'PLATE 2. Oistodus.' and plate.kind == 'fossil_plate' and plate.linked_at is not None
    assert FigureEntry.select().where(FigureEntry.figure == plate.id).count() == 2
    assert FigurePanel.select().where(FigurePanel.figure == plate.id).count() == 2
    folded = Figure.get((Figure.paper_file == dst.id) & (Figure.page == 3))
    assert folded.dismissed and folded.dismissed_by == 'user'
    # again: nothing changes
    report = fs.import_figures(dst, data, PAGES)
    assert (report.created, report.updated, report.unchanged, report.protected) == (0, 0, 2, 1)


@pytest.mark.unit
def test_import_takes_newer_stage_results_but_never_a_persons_row(db):
    from papermeister import figure_share as fs
    from papermeister.figure_store import apply_plan, plan_store
    from papermeister.models import Figure
    src = make_file('A', 'a.pdf')
    processed(src)
    data = {'figures': fs.export_figures(src, PAGES)}
    # the other library assembled the same paper but has not linked it
    dst = make_file('B', 'b.pdf')
    figs = [AssembledFigure(page=2, bbox=(100, 100, 900, 480), blocks=((100, 100, 480, 480), (520, 100, 900, 480)),
                            assembly=PLATE_UNION, plate=2, name_hint='Plate 2', page_kind=PLATE_KIND)]
    apply_plan(plan_store(dst, figs))
    report = fs.import_figures(dst, data, PAGES)
    assert report.updated == 1 and report.created == 2
    assert Figure.get((Figure.paper_file == dst.id) & (Figure.page == 2)).caption == 'PLATE 2. Oistodus.'
    # a person's row here is left alone even when the export is newer
    mine = Figure.get((Figure.paper_file == dst.id) & (Figure.page == 2))
    mine.caption, mine.caption_locked = 'mine', True
    mine.save()
    data['figures']['rows'][0]['linked_at'] = '2026-12-31T00:00:00'
    report = fs.import_figures(dst, data, PAGES)
    assert report.protected == 2 and Figure.get_by_id(mine.id).caption == 'mine'   # mine + the imported person's fold


@pytest.mark.unit
def test_import_refuses_another_text_or_pdf(db):
    from papermeister import figure_share as fs
    src = make_file('A', 'a.pdf')
    processed(src)
    data = {'figures': fs.export_figures(src, PAGES)}
    dst = make_file('B', 'b.pdf')
    assert 're-OCR' in fs.import_figures(dst, data, PAGES[:4]).skipped_reason
    data['figures']['file_hash'] = 'cd' * 32
    assert 'another PDF' in fs.import_figures(dst, data, PAGES).skipped_reason
    assert 'no figures' in fs.import_figures(dst, {}, PAGES).skipped_reason


@pytest.mark.unit
def test_the_cache_json_round_trip(db, monkeypatch):
    """write_to_cache puts the block in the JSON next to the pages;
    import_from_cache reads it back into an empty library."""
    from papermeister import figure_share as fs
    from papermeister.models import Figure
    from papermeister.paths import OCR_JSON_DIR
    from papermeister.text_extract import ocr_json_filename
    src = make_file('A', 'a.pdf')
    processed(src)
    os.makedirs(OCR_JSON_DIR, exist_ok=True)
    path = os.path.join(OCR_JSON_DIR, ocr_json_filename(src))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'pages': [{'page': i, 'markdown': t} for i, t in enumerate(PAGES)],
                   'papermeister_meta': {'biblio_state': 'applied'}}, f)
    monkeypatch.setattr(fs, 'push_sibling_json', None, raising=False)
    assert fs.write_to_cache(src, push=False) is None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    assert data['papermeister_meta'] == {'biblio_state': 'applied'} and len(data['figures']['rows']) == 3
    Figure.delete().where(Figure.paper_file == src.id).execute()
    report = fs.import_from_cache(src)
    assert report.created == 3


@pytest.mark.unit
def test_a_changed_json_is_landed_once_per_export_an_unchanged_one_not_at_all(db, monkeypatch):
    """The app opens a paper's tabs many times a session; another machine
    may write new stages to the JSON in between. The JSON is read when its
    export stamp is new to this session, and the import only moves what is
    newer — so a second machine's panels land on rows this one already had."""
    from papermeister import figure_share as fs
    from papermeister.models import Figure, FigurePanel
    from papermeister.paths import OCR_JSON_DIR
    from papermeister.text_extract import ocr_json_filename
    src = make_file('A', 'a.pdf')
    plate, _body = processed(src)
    os.makedirs(OCR_JSON_DIR, exist_ok=True)
    path = os.path.join(OCR_JSON_DIR, ocr_json_filename(src))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'pages': [{'page': i, 'markdown': t} for i, t in enumerate(PAGES)]}, f)
    fs.write_to_cache(src, push=False)
    seen: dict[int, str] = {}
    first = fs.import_from_cache_if_new(src, seen)
    assert first is not None and first.created == 0 and src.id in seen
    assert fs.import_from_cache_if_new(src, seen) is None          # same export: not read again
    # the other machine: panels dropped locally, a newer paneled_at in the JSON
    FigurePanel.delete().where(FigurePanel.figure == plate.id).execute()
    plate = Figure.get_by_id(plate.id)
    plate.paneled_at = datetime.datetime.fromisoformat('2026-09-01T00:00:00')
    plate.save()
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['figures']['exported_at'] = '2026-09-22T00:00:00+00:00'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    again = fs.import_from_cache_if_new(src, seen)
    assert again is not None and again.updated == 1
    assert FigurePanel.select().where(FigurePanel.figure == plate.id).count() == 2
    assert fs.import_from_cache_if_new(src, seen) is None
    # a JSON without figures is never "new"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'pages': []}, f)
    assert fs.import_from_cache_if_new(src, {}) is None
