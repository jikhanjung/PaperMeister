"""Review tools for the P16 Phase 1 gate: sheets that show what assembly did,
and a record of what a person decided that survives re-assembly.

The sheet tests use a synthetic OCR page and a one-page PDF made with Pillow;
the curation tests use the real schema on a temporary database, like
`test_figure_store`.
"""
import json
import os
import tempfile
from collections import Counter

import pytest
from PIL import Image

from papermeister import figure_sheet, figures
from papermeister.figures import CAPTION_GROUP, PLATE_UNION, SINGLE, AssembledFigure, PageAssembly

HASH = 'cd' * 32


def block(label, bbox, text=''):
    x0, y0, x1, y1 = bbox
    return (f'<div data-label="{label}" data-bbox="{x0} {y0} {x1} {y1}">'
            f'{"<img alt=x>" if label in ("Figure", "Image") else text}</div>')


PLATE_PAGE = ''.join([
    block('Page-Header', (100, 20, 900, 40), 'PLATE IV'),
    block('Image', (100, 100, 480, 480)), block('Image', (520, 100, 900, 480)),
    block('Image', (100, 520, 900, 900)),
])


# ── classification ───────────────────────────────────────────────────

def assembly(figs, verdict='', pictures=None):
    return PageAssembly(page=3, picture_blocks=pictures if pictures is not None else max(1, len(figs)),
                        verdict=verdict, figures=figs)


def fig(**kw):
    base = {'page': 3, 'bbox': (100, 100, 900, 900), 'blocks': ((100, 100, 900, 900),), 'assembly': SINGLE}
    base.update(kw)
    return AssembledFigure(**base)


@pytest.mark.unit
def test_pages_without_pictures_are_not_reviewed():
    assert figure_sheet.classify_page(PageAssembly(page=0, picture_blocks=0)) is None


@pytest.mark.unit
def test_a_picture_page_with_no_figure_is_the_first_stratum():
    assert figure_sheet.classify_page(assembly([], pictures=3)) == 'dropped'


@pytest.mark.unit
def test_inferred_plate_numbers_come_before_everything_else():
    a = assembly([fig(assembly=PLATE_UNION, page_kind=figures.PLATE_KIND, plate=4, plate_inferred=True)])
    assert figure_sheet.classify_page(a) == 'plate_inferred'


@pytest.mark.unit
def test_strata_by_what_the_rule_did():
    assert figure_sheet.classify_page(assembly([fig()], verdict=figures.DUP_NUMBER)) == 'dup_number'
    assert figure_sheet.classify_page(assembly([fig()], verdict=figures.MANY_MARKS)) == 'many_marks'
    assert figure_sheet.classify_page(assembly([fig(page_kind=figures.CAPTIONED_PLATE)])) == 'captioned_plate'
    assert figure_sheet.classify_page(assembly([fig(assembly=PLATE_UNION, page_kind=figures.PLATE_KIND)])) == 'plate_union'
    assert figure_sheet.classify_page(assembly([fig(page_kind=figures.PLATE_KIND)])) == 'plate_single'
    assert figure_sheet.classify_page(assembly([fig(assembly=CAPTION_GROUP)])) == 'cut_up'
    assert figure_sheet.classify_page(assembly([fig()])) == 'body'


@pytest.mark.unit
def test_sampling_is_per_stratum_and_repeatable():
    cards = [figure_sheet.Card(paper_id=i, paper_file_id=i, title='', pdf_path=None, page=0,
                               page_text='', assembly=assembly([fig()]), stratum='body' if i % 2 else 'cut_up')
             for i in range(40)]
    a = figure_sheet.sample_cards(cards, 5, seed=1)
    b = figure_sheet.sample_cards(cards, 5, seed=1)
    assert Counter(c.stratum for c in a) == {'body': 5, 'cut_up': 5}
    assert [c.paper_id for c in a] == [c.paper_id for c in b]
    assert len(figure_sheet.sample_cards(cards, None, seed=1)) == 40


# ── drawing and writing ──────────────────────────────────────────────

@pytest.mark.unit
def test_drawing_marks_figures_and_captions_on_the_page():
    facts = figures.read_page(3, PLATE_PAGE)
    figs = figures.assemble_page(3, PLATE_PAGE).figures
    assert len(figs) == 1 and figs[0].assembly == PLATE_UNION
    image = figure_sheet.draw_page(Image.new('RGB', (200, 300), 'white'), facts, figs)
    # the plate union box is red; its top-left corner lands at (20, 30)
    assert image.getpixel((20, 30)) == (220, 40, 40)
    # a picture block edge inside the union is drawn faintly (grey, 1px)
    assert image.getpixel((96, 60)) == (140, 140, 140)


@pytest.mark.unit
def test_sheets_name_the_stratum_and_say_what_to_check(tmp_path):
    a = figures.assemble_page(3, PLATE_PAGE)
    card = figure_sheet.Card(paper_id=7, paper_file_id=9, title='Bruton 2004', pdf_path=None, page=3,
                             page_text=PLATE_PAGE, assembly=a, stratum='plate_union',
                             row_ids={(3, a.figures[0].bbox, PLATE_UNION): 55})
    files = figure_sheet.write_sheets([card], Counter({'plate_union': 12}), str(tmp_path))
    assert files == {'plate_union': 'plate_union.html'}
    page = (tmp_path / 'plate_union.html').read_text(encoding='utf-8')
    assert '1 of 12 pages' in page and 'every photograph inside' in page
    assert '#55' in page and 'Plate IV' in page and 'PDF not on this machine' in page
    index = (tmp_path / 'index.html').read_text(encoding='utf-8')
    assert 'plate_union.html' in index


@pytest.mark.unit
def test_unstored_figures_are_identified_by_key(tmp_path):
    a = figures.assemble_page(3, PLATE_PAGE)
    card = figure_sheet.Card(paper_id=7, paper_file_id=9, title='', pdf_path=None, page=3,
                             page_text=PLATE_PAGE, assembly=a, stratum='plate_union')
    assert card.key(a.figures[0]) == '9:3:100,100,900,900'
    figure_sheet.write_sheets([card], Counter({'plate_union': 1}), str(tmp_path))
    assert '9:3:100,100,900,900' in (tmp_path / 'plate_union.html').read_text(encoding='utf-8')


@pytest.mark.unit
def test_rendering_a_card_draws_the_pdf_page(tmp_path):
    pdf = tmp_path / 'one.pdf'
    Image.new('RGB', (400, 600), 'white').save(pdf)
    a = figures.assemble_page(0, PLATE_PAGE)
    card = figure_sheet.Card(paper_id=1, paper_file_id=2, title='', pdf_path=str(pdf), page=0,
                             page_text=PLATE_PAGE, assembly=a, stratum='plate_union')
    figure_sheet.render_card(card, str(tmp_path / 'out'), dpi=36)
    assert card.image == 'img/p2_0000.jpg'
    drawn = Image.open(tmp_path / 'out' / card.image)
    assert drawn.size[0] > 0 and drawn.getpixel((5, 5)) != (220, 40, 40)


# ── curation ─────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-curate-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def stored(db):
    """Three figures on one page of one file, as assembly would store them."""
    from papermeister import figure_store
    from papermeister.models import Paper, PaperFile
    paper = Paper.create(title='Henningsmoen 1957')
    pf = PaperFile.create(paper=paper, path='h.pdf', hash=HASH, status='processed')
    figs = [AssembledFigure(page=5, bbox=b, blocks=(b,), assembly=SINGLE, name_hint=n, caption_hint='')
            for b, n in (((100, 100, 480, 480), 'Fig. 1'), ((520, 100, 900, 480), 'Fig. 2'),
                         ((100, 520, 900, 900), ''))]
    figure_store.apply_plan(figure_store.plan_store(pf, figs))
    from papermeister.models import Figure
    return pf, list(Figure.select().order_by(Figure.id)), figs


def record_path(db):
    return os.path.join(os.environ['PAPERMEISTER_DATA_DIR'], 'tmp', 'p16_curation', 'test.json')


@pytest.mark.unit
def test_a_reason_is_required(stored):
    from papermeister import figure_curation as cur
    _, rows, _ = stored
    with pytest.raises(cur.CurationError, match='reason'):
        cur.plan('confirm', rows[:1], '')


@pytest.mark.unit
def test_keys_find_rows_the_way_the_sheet_prints_them(stored):
    from papermeister import figure_curation as cur
    pf, rows, _ = stored
    found = cur.find_rows(keys=[f'{pf.id}:5:520,100,900,480'])
    assert [r.id for r in found] == [rows[1].id]
    with pytest.raises(cur.CurationError, match='no figure'):
        cur.find_rows(keys=[f'{pf.id}:5:1,1,2,2'])
    with pytest.raises(cur.CurationError, match='not a figure key'):
        cur.parse_key('nonsense')


@pytest.mark.unit
def test_dismissing_folds_by_the_person_and_reassembly_leaves_it(db, stored):
    from papermeister import figure_curation as cur
    from papermeister import figure_store
    from papermeister.models import Figure
    pf, rows, figs = stored
    cur.apply(cur.plan('dismiss', [rows[2]], 'a journal ornament'), record_path(db))
    row = Figure.get_by_id(rows[2].id)
    assert row.dismissed and row.dismissed_by == cur.USER and row.user_confirmed
    # the rule still produces that figure; the store must not revive it
    plan = figure_store.plan_store(pf, figs)
    assert plan.restore == [] and plan.create == [] and plan.untouched_by_rule == 1
    assert Figure.get_by_id(rows[2].id).dismissed


@pytest.mark.unit
def test_merge_keeps_the_survivor_with_the_union_and_folds_the_rest(db, stored):
    from papermeister import figure_curation as cur
    from papermeister.models import Figure
    _, rows, _ = stored
    plan = cur.plan('merge', rows, 'one plate, three photographs')
    assert any('→' in line for line in plan.describe())
    cur.apply(plan, record_path(db))
    survivor = Figure.get_by_id(rows[0].id)
    assert json.loads(survivor.bbox_page_1000) == [100, 100, 900, 900]
    assert len(json.loads(survivor.blocks_json)) == 3 and survivor.user_confirmed
    assert all(Figure.get_by_id(r.id).dismissed for r in rows[1:])
    with pytest.raises(cur.CurationError, match='one page'):
        other = Figure.create(paper=survivor.paper_id, paper_file=survivor.paper_file_id, file_hash=HASH,
                              page=6, bbox_page_1000='[0, 0, 10, 10]')
        cur.plan('merge', [survivor, other], 'x')


@pytest.mark.unit
def test_rename_and_set_bbox_take_one_figure(stored):
    from papermeister import figure_curation as cur
    _, rows, _ = stored
    with pytest.raises(cur.CurationError, match='exactly one'):
        cur.plan('rename', rows[:2], 'x', name='Plate I')
    with pytest.raises(cur.CurationError, match='bbox'):
        cur.plan('set-bbox', rows[:1], 'x', bbox=[900, 100, 100, 480])
    plan = cur.plan('set-bbox', rows[:1], 'right column left out', bbox=[100, 100, 900, 480])
    assert plan.changes[0].after['bbox_page_1000'] == '[100, 100, 900, 480]'


@pytest.mark.unit
def test_the_record_replays_onto_rows_found_by_identity(db, stored):
    """After re-assembly the ids are new; the decisions must still land."""
    from papermeister import figure_curation as cur
    from papermeister.models import Figure
    pf, rows, figs = stored
    path = record_path(db)
    cur.apply(cur.plan('rename', [rows[2]], 'the caption is on the next page', name='Fig. 3'), path)
    cur.apply(cur.plan('dismiss', [rows[1]], 'logo'), path)
    entries = cur.load_record(path)
    assert [e['op'] for e in entries] == ['rename', 'dismiss']
    assert entries[0]['targets'][0]['before']['name'] == ''

    # a rebuilt library: same identities, new rows
    Figure.delete().execute()
    from papermeister import figure_store
    figure_store.apply_plan(figure_store.plan_store(pf, figs))
    fresh = list(Figure.select().order_by(Figure.id))
    assert not any(r.user_confirmed or r.dismissed for r in fresh)

    lines = cur.replay(entries, None, execute=False)
    assert all(line.startswith('  would') for line in lines)
    assert not Figure.get_by_id(fresh[2].id).user_confirmed
    cur.replay(entries, path, execute=True)
    assert Figure.get_by_id(fresh[2].id).name == 'Fig. 3'
    assert Figure.get_by_id(fresh[1].id).dismissed

    # a decision about a row that no longer exists is skipped, not half-applied
    entries[0]['targets'][0]['key']['bbox'] = [1, 1, 2, 2]
    assert cur.replay(entries[:1], None, execute=False)[0].startswith('  skip')
