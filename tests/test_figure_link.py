"""The caption stage from the client's side: what goes out, what is believed,
what is written — all without a server. The replies are hand-made in the
shape ocrserver will return; the checks are what fsis learned to make.
"""
import json
import os
import tempfile

import pytest

from papermeister.figures import CAPTIONED_PLATE, PLATE_KIND, PLATE_UNION, SINGLE, AssembledFigure

HASH = 'ef' * 32
DIGEST = 'd' * 64
PROMPT = 'link-v1-test'


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-link-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


def block(label, bbox, text):
    return (f'<div data-label="{label}" data-bbox="{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}">'
            f'{text}</div>')


PAGES = [
    block('Text', (100, 100, 900, 900), 'Introduction. ' * 30),
    block('Section-Header', (100, 100, 900, 130), 'Explanation of Plate 2')
    + block('Text', (100, 150, 900, 900),
            'PLATE 2. Oistodus aff. breviconus. Fig. 1. Lateral view of the holotype, YSUG 00287. '
            'Fig. 2. Posterior view of the same specimen, YSUG 00288. Fig. 3. Drepanodus arcuatus, YSUG 00290.'),
    block('Page-Header', (300, 20, 700, 45), 'PLATE 2')
    + block('Image', (100, 100, 480, 480), '<img alt="a">') + block('Image', (520, 100, 900, 480), '<img alt="b">'),
    block('Image', (100, 100, 900, 600), '<img alt="c">')
    + block('Caption', (100, 610, 900, 660), 'Fig. 4. Stratigraphic column of the Dumugol Formation.')
    + block('Text', (100, 700, 900, 900), 'Body text. ' * 40),
]


@pytest.fixture
def stored(db):
    """A paper with a plate (p.2, explained on p.1) and a body figure (p.3)."""
    from papermeister import figure_store
    from papermeister.models import Figure, Paper, PaperFile
    paper = Paper.create(title='Lee 2004')
    pf = PaperFile.create(paper=paper, path='lee.pdf', hash=HASH, status='processed')
    figs = [
        AssembledFigure(page=2, bbox=(100, 100, 900, 480), blocks=((100, 100, 480, 480), (520, 100, 900, 480)),
                        assembly=PLATE_UNION, plate=2, name_hint='Plate 2', page_kind=PLATE_KIND),
        AssembledFigure(page=3, bbox=(100, 100, 900, 600), blocks=((100, 100, 900, 600),), assembly=SINGLE,
                        name_hint='Fig. 4', caption_hint='Fig. 4. Stratigraphic column of the Dumugol Formation.'),
    ]
    figure_store.apply_plan(figure_store.plan_store(pf, figs))
    return pf, {r.page: r for r in Figure.select()}


def reply(plate_id, body_id, **overrides):
    r = {
        'figures': [
            {'figure_id': plate_id, 'name': 'Plate 2', 'caption': 'PLATE 2. Oistodus aff. breviconus.',
             'caption_source': 'explanation_page', 'caption_pages': [1],
             'entries': [
                 {'label': '1', 'description': 'Lateral view of the holotype, YSUG 00287', 'specimen_number': 'YSUG 00287'},
                 {'label': '2', 'description': 'Posterior view of the same specimen, YSUG 00288'},
                 {'label': '3', 'description': 'Drepanodus arcuatus, YSUG 00290'}]},
            {'figure_id': body_id, 'name': 'Fig. 4',
             'caption': 'Fig. 4. Stratigraphic column of the Dumugol Formation.',
             'caption_source': 'same_page', 'caption_pages': [3], 'entries': []},
        ],
        'skipped': [], 'pages_consulted': [1, 2, 3],
    }
    r.update(overrides)
    return r


@pytest.mark.unit
def test_targets_name_every_exclusion(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    assert [r.page for r in t.due] == [2, 3] and t.context == [] and t.excluded == []
    # a locked caption is context; a captioned-plate photo and a placeholder are out
    rows[3].caption_locked = True
    rows[3].save()
    Figure.create(paper=pf.paper_id, paper_file=pf.id, file_hash=HASH, page=5, bbox_page_1000='[0, 0, 1000, 1000]',
                  assembly='page', uncertain_reasons_json='["plate_without_pictures"]')
    Figure.create(paper=pf.paper_id, paper_file=pf.id, file_hash=HASH, page=6, bbox_page_1000='[1, 1, 2, 2]',
                  page_kind=CAPTIONED_PLATE, name='Plate 3, Fig. 1')
    t = fl.link_targets(pf, DIGEST, PROMPT)
    assert [r.page for r in t.due] == [2] and [r.page for r in t.context] == [3]
    assert sorted(why for _, why in t.excluded) == ['own_caption', 'page_placeholder']
    # exhausted attempts stay out until asked for
    rows[2].link_attempts = 3
    rows[2].save()
    assert fl.link_targets(pf, DIGEST, PROMPT).due == []
    assert [r.page for r in fl.link_targets(pf, DIGEST, PROMPT, retry_errors=True).due] == [2]


@pytest.mark.unit
def test_the_payload_carries_figures_and_hints_but_no_page_text(stored):
    from papermeister import figure_link as fl
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'papermeister-test')
    assert p['file_hash'] == HASH and p['ocr_digest'] == DIGEST and p['page_count'] == 4
    assert [f['page'] for f in p['figures']] == [2, 3] and all(not f['locked'] for f in p['figures'])
    assert p['figures'][0]['page_kind'] == 'plate' and p['figures'][0]['plate'] == 2
    assert p['hints'] == {'plate_pages': [1, 2], 'explanation_pages': [1], 'caption_pages': [3]}
    assert 'pages' not in p
    ws = fl.workspace_payload(pf, PAGES)
    assert ws['ocr_digest'] == fl.ocr_digest(PAGES) and [x['page'] for x in ws['pages']] == [0, 1, 2, 3]


@pytest.mark.unit
def test_a_good_reply_is_accepted_and_written(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure, FigureEntry
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    check = fl.validate_link_result(p, r, PAGES, {str(x.id): x for x in t.due})
    assert check.rejected == [] and check.review == {} and set(check.accepted) == {str(rows[2].id), str(rows[3].id)}
    applied = fl.apply_link(t, check, r, DIGEST, PROMPT, 'gpt-6-astra')
    assert applied.written == 2 and applied.failed == 0
    plate = Figure.get_by_id(rows[2].id)
    assert plate.caption.startswith('PLATE 2.') and plate.caption_source == 'explanation_page'
    assert plate.caption_page == 1 and json.loads(plate.caption_pages_json) == [1]
    assert plate.link_key == fl.link_key(plate, DIGEST, PROMPT) and plate.linked_at is not None
    entries = list(FigureEntry.select().where(FigureEntry.figure == plate.id).order_by(FigureEntry.order))
    assert [e.label for e in entries] == ['1', '2', '3']
    assert entries[0].specimen_number == 'YSUG 00287' and entries[0].label_status == 'printed'
    # the same reply again is unchanged, not rewritten
    t2 = fl.link_targets(pf, DIGEST, PROMPT)
    assert t2.due == [] and sorted(why for _, why in t2.excluded) == ['linked', 'linked']


@pytest.mark.unit
def test_replies_about_figures_we_did_not_send_or_pages_the_paper_lacks_are_rejected(stored):
    from papermeister import figure_link as fl
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'][0]['caption_pages'] = [9]           # the paper has four pages
    r['figures'].append({'figure_id': '999', 'caption': 'x', 'caption_pages': [0], 'entries': []})
    check = fl.validate_link_result(p, r, PAGES)
    assert (str(rows[2].id), 'caption_pages_outside_paper') in check.rejected
    assert check.unknown == ['999'] and str(rows[3].id) in check.accepted


@pytest.mark.unit
def test_an_invented_description_is_flagged_not_stored_silently(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'][0]['entries'][1]['description'] = 'Fossil specimen shown in dorsal aspect with prominent glabella'
    r['figures'][1]['caption'] = 'A map of the study area with sampling localities marked'
    check = fl.validate_link_result(p, r, PAGES)
    assert check.review[str(rows[2].id)] == [fl.DESCRIPTION_NOT_PRINTED]
    assert check.review[str(rows[3].id)] == [fl.CAPTION_NOT_PRINTED]
    fl.apply_link(t, check, r, DIGEST, PROMPT, 'm')
    # written — the model may be right — but the doubt is on the row for a person
    assert fl.DESCRIPTION_NOT_PRINTED in json.loads(Figure.get_by_id(rows[2].id).uncertain_reasons_json)


@pytest.mark.unit
def test_a_skipped_figure_keeps_what_it_had_and_counts_an_attempt(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    rows[3].caption, rows[3].caption_source = 'Fig. 4. Old but real.', 'same_page'
    rows[3].save()
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'] = r['figures'][:1]
    r['skipped'] = [{'figure_id': str(rows[3].id), 'reason': 'explanation_not_found'}]
    check = fl.validate_link_result(p, r, PAGES)
    assert check.skipped == [str(rows[3].id)]
    applied = fl.apply_link(t, check, r, DIGEST, PROMPT, 'm')
    body = Figure.get_by_id(rows[3].id)
    assert applied.failed == 1 and body.caption == 'Fig. 4. Old but real.' and body.link_attempts == 1


@pytest.mark.unit
def test_fewer_entries_than_a_sourced_result_is_a_question(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure, FigureEntry
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    fl.apply_link(t, fl.validate_link_result(p, r, PAGES), r, DIGEST, PROMPT, 'm')
    assert FigureEntry.select().where(FigureEntry.figure == rows[2].id).count() == 3
    # a re-run with a new prompt returns two entries for the plate
    t = fl.link_targets(pf, DIGEST, 'link-v2')
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r['figures'][0]['entries'] = r['figures'][0]['entries'][:2]
    check = fl.validate_link_result(p, r, PAGES, {str(x.id): x for x in t.due})
    assert (str(rows[2].id), fl.ENTRIES_SHRANK) in check.rejected
    fl.apply_link(t, check, r, DIGEST, 'link-v2', 'm')
    assert FigureEntry.select().where(FigureEntry.figure == rows[2].id).count() == 3
    assert fl.ENTRIES_SHRANK in json.loads(Figure.get_by_id(rows[2].id).uncertain_reasons_json)


@pytest.mark.unit
def test_shared_captions_and_empty_plates_are_flagged(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    other = Figure.create(paper=pf.paper_id, paper_file=pf.id, file_hash=HASH, page=3,
                          bbox_page_1000='[100, 650, 900, 900]', blocks_json='[[100, 650, 900, 900]]')
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'][0]['entries'] = []
    r['figures'].append({**r['figures'][1], 'figure_id': str(other.id)})
    check = fl.validate_link_result(p, r, PAGES)
    assert check.review[str(rows[2].id)] == [fl.PLATE_NO_ENTRIES]
    assert fl.CAPTION_SHARED in check.review[str(rows[3].id)] and fl.CAPTION_SHARED in check.review[str(other.id)]


@pytest.mark.unit
def test_a_locked_caption_is_context_and_never_written(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    rows[3].caption, rows[3].caption_locked = 'Fig. 4. A person wrote this.', True
    rows[3].save()
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    locked = [f for f in p['figures'] if f['locked']]
    assert len(locked) == 1 and locked[0]['caption'] == 'Fig. 4. A person wrote this.'
    r = reply(str(rows[2].id), str(rows[3].id))
    check = fl.validate_link_result(p, r, PAGES)
    assert (str(rows[3].id), 'locked') in check.rejected
    fl.apply_link(t, check, r, DIGEST, PROMPT, 'm')
    assert Figure.get_by_id(rows[3].id).caption == 'Fig. 4. A person wrote this.'
