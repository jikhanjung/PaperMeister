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
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'papermeister-test', {'version': 'link-v1-x'})
    assert p['file_hash'] == HASH and p['ocr_digest'] == DIGEST and p['prompt'] == {'version': 'link-v1-x'}
    item = p['items'][0]
    assert item['key'].endswith('@link-v1-x') and item['page_count'] == 4
    assert [f['page'] for f in item['figures']] == [2, 3] and all(not f['locked'] for f in item['figures'])
    assert item['figures'][0]['page_kind'] == 'plate' and item['figures'][0]['plate'] == 2
    assert item['hints'] == {'plate_pages': [1, 2], 'explanation_pages': [1], 'caption_pages': [3]}
    assert 'pages' not in p and 'pages' not in item
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
    # one word the OCR misread and the model corrected is not an invention
    r2 = reply(str(rows[2].id), str(rows[3].id))
    r2['figures'][1]['caption'] = 'Fig. 4. Stratigraphic column of the Dumugol Formatiön.'
    assert str(rows[3].id) not in fl.validate_link_result(p, r2, PAGES).review
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
    locked = [f for f in p['items'][0]['figures'] if f['locked']]
    assert len(locked) == 1 and locked[0]['caption'] == 'Fig. 4. A person wrote this.'
    r = reply(str(rows[2].id), str(rows[3].id))
    check = fl.validate_link_result(p, r, PAGES)
    assert (str(rows[3].id), 'locked') in check.rejected
    fl.apply_link(t, check, r, DIGEST, PROMPT, 'm')
    assert Figure.get_by_id(rows[3].id).caption == 'Fig. 4. A person wrote this.'


@pytest.mark.unit
def test_one_pdf_under_three_library_entries_is_linked_once_and_copied(stored):
    """The thesis filed under three Zotero parents went to the server three
    times (2026-09-17). The reply is applied to one entry and copied to the
    rows of the others that share the page and box."""
    from papermeister import figure_link as fl
    from papermeister import figure_store
    from papermeister.models import Figure, FigureEntry, Paper, PaperFile
    pf, rows = stored
    twins = []
    for title in ('이창숙 2004', 'Lee 2004 (again)'):
        other = PaperFile.create(paper=Paper.create(title=title), path='lee2.pdf', hash=HASH, status='processed')
        figs = [AssembledFigure(page=2, bbox=(100, 100, 900, 480), blocks=((100, 100, 480, 480), (520, 100, 900, 480)),
                                assembly=PLATE_UNION, plate=2, name_hint='Plate 2', page_kind=PLATE_KIND),
                AssembledFigure(page=3, bbox=(100, 100, 900, 600), blocks=((100, 100, 900, 600),), assembly=SINGLE)]
        figure_store.apply_plan(figure_store.plan_store(other, figs))
        twins.append(other)
    assert [o.id for o in fl.siblings(pf)] == [o.id for o in twins]

    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    fl.apply_link(t, fl.validate_link_result(p, r, PAGES), r, DIGEST, PROMPT, 'm')
    assert fl.propagate_link(pf) == 4
    for other in twins:
        plate = Figure.get((Figure.paper_file == other.id) & (Figure.page == 2))
        assert plate.caption.startswith('PLATE 2.') and plate.link_key == fl.link_key(plate, DIGEST, PROMPT)
        assert FigureEntry.select().where(FigureEntry.figure == plate.id).count() == 3
        assert fl.link_targets(other, DIGEST, PROMPT).due == []      # nothing left to send for the twin
    assert fl.propagate_link(pf) == 0                                 # idempotent
    # a person's caption on a twin is not overwritten by the copy
    plate = Figure.get((Figure.paper_file == twins[0].id) & (Figure.page == 2))
    plate.caption, plate.caption_locked, plate.link_key = 'mine', True, ''
    plate.save()
    assert fl.propagate_link(pf) == 0 and Figure.get_by_id(plate.id).caption == 'mine'


@pytest.mark.unit
def test_a_paper_with_many_figures_is_sent_as_several_items(stored):
    """Balašova 1976, 91 plates: one session could not deliver the answer
    (three attempts, two hours). Split by page into items of at most N; the
    locked context rides in every item; the checks merge back into one."""
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    for page in range(10, 20):
        Figure.create(paper=pf.paper_id, paper_file=pf.id, file_hash=HASH, page=page,
                      bbox_page_1000=json.dumps([100, 100, 900, 900]), blocks_json='[[100, 100, 900, 900]]')
    rows[3].caption_locked = True
    rows[3].save()
    t = fl.link_targets(pf, DIGEST, PROMPT)
    assert len(t.due) == 11 and len(t.context) == 1
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c', {'version': 'v'}, per_item=4)
    items = p['items']
    # the plate (weight 8) fills an item by itself; the ten body figures go four to an item
    assert [it['part'] for it in items] == [[1, 4], [2, 4], [3, 4], [4, 4]]
    assert [it['key'][-4:] for it in items] == ['#1/4', '#2/4', '#3/4', '#4/4']
    assert [len([f for f in it['figures'] if not f['locked']]) for it in items] == [1, 4, 4, 2]
    assert items[0]['figures'][0]['page_kind'] == 'plate'
    assert all(any(f['locked'] for f in it['figures']) for it in items)
    # pages ascend across items
    pages_sent = [f['page'] for it in items for f in it['figures'] if not f['locked']]
    assert pages_sent == sorted(pages_sent)
    # one item answered, one not: the answered figures are written, the rest count an attempt
    r = {'figures': [{'figure_id': f['figure_id'], 'name': '', 'caption': 'PLATE 2. Oistodus aff. breviconus.',
                      'caption_source': 'explanation_page', 'caption_pages': [1], 'entries': []}
                     for f in items[0]['figures'] if not f['locked']],
         'skipped': [], 'pages_consulted': [3]}
    check = fl.LinkCheck().merge(fl.validate_link_result(items[0], r, PAGES))
    applied = fl.apply_link(t, check, {}, DIGEST, PROMPT, 'm')
    assert applied.written == 1 and applied.failed == 10
    # a single-figure paper keeps the plain key
    assert fl.link_items(pf, PAGES, fl.LinkTargets(due=t.due[:1]), DIGEST, 'v')[0]['key'].endswith('@v')


@pytest.mark.unit
def test_inflection_and_misread_letters_do_not_read_as_invention(stored):
    """Sokolov 1983, Balašova 1976: the model's captions matched the Cyrillic
    pages except for case endings and Latin names the OCR had garbled — and
    were flagged as not printed. Words compare by stem, homoglyphs folded."""
    from papermeister import figure_link as fl
    pages = ['<div data-label="Text" data-bbox="0 0 1 1">Таблица XXV. 3. Мicatheca stupenda Sysoiev, 1972; с. 74. '
             'а — раковина с брюшной стороны, спинная сторона, приустьевая часть</div>']
    caption = 'Таблица XXV. 3. Micatheca stupenda Sysoiev, 1972; с. 74. а — раковина с брюшной стороны, спинной стороны, приустьевое'
    assert fl._share(fl._words(caption), fl._page_words(pages, [0])) >= fl.CAPTION_WORD_SHARE
    # a stored row is re-checked in place
    from papermeister.models import Figure
    pf, rows = stored
    row = rows[3]
    row.caption, row.caption_pages_json, row.linked_at = caption, '[0]', __import__('datetime').datetime.now()
    row.uncertain_reasons_json = json.dumps(['no_caption', fl.CAPTION_NOT_PRINTED])
    row.save()
    assert fl.apply_recheck(row, pages) is True
    assert json.loads(Figure.get_by_id(row.id).uncertain_reasons_json) == ['no_caption']


@pytest.mark.unit
def test_a_skipped_figure_carries_the_models_reason(stored):
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'] = r['figures'][:1]
    r['skipped'] = [{'figure_id': str(rows[3].id), 'reason': 'explanation_not_found'}]
    check = fl.validate_link_result(p, r, PAGES)
    fl.apply_link(t, check, r, DIGEST, PROMPT, 'm')
    assert 'link_skipped:explanation_not_found' in json.loads(Figure.get_by_id(rows[3].id).uncertain_reasons_json)


@pytest.mark.unit
def test_the_same_reply_collected_twice_is_not_a_second_attempt(stored):
    """collect re-reads old jobs; a figure the reply skipped must not lose an
    attempt every time (three collects would retire it)."""
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    p = fl.link_payload(pf, PAGES, t, DIGEST, 'c')
    r = reply(str(rows[2].id), str(rows[3].id))
    r['figures'] = r['figures'][:1]
    r['skipped'] = [{'figure_id': str(rows[3].id), 'reason': 'not_a_figure'}]
    for _ in range(3):
        t = fl.link_targets(pf, DIGEST, PROMPT)
        fl.apply_link(t, fl.validate_link_result(p, r, PAGES), r, DIGEST, PROMPT, 'm')
    assert Figure.get_by_id(rows[3].id).link_attempts == 1
    # a different reply is a new attempt
    r['skipped'][0]['reason'] = 'ambiguous'
    t = fl.link_targets(pf, DIGEST, PROMPT)
    fl.apply_link(t, fl.validate_link_result(p, r, PAGES), r, DIGEST, PROMPT, 'm')
    assert Figure.get_by_id(rows[3].id).link_attempts == 2


@pytest.mark.unit
def test_a_job_whose_split_moved_is_rebuilt_from_its_replies(stored):
    """Barrande (1191), 2026-09-19: submitted as six items at weight 80; by
    collect time three rows had left the due set, the same weight now cut
    five items, no key matched, and forty answered figures were stranded.
    The reply names its figures — rebuild the items from that."""
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    for page in range(10, 20):
        Figure.create(paper=pf.paper_id, paper_file=pf.id, file_hash=HASH, page=page,
                      bbox_page_1000=json.dumps([100, 100, 900, 900]), blocks_json='[[100, 100, 900, 900]]')
    rows[3].caption_locked = True
    rows[3].save()
    t = fl.link_targets(pf, DIGEST, PROMPT)
    items = fl.link_items(pf, PAGES, t, DIGEST, PROMPT, per_item=4)
    assert len(items) == 4
    replies = {}
    for it in items:
        figs = [f for f in it['figures'] if not f['locked']]
        replies[it['key']] = {'status': 'done', 'result': {
            'figures': [{'figure_id': f['figure_id'], 'name': '', 'caption': 'PLATE 2. Oistodus aff. breviconus.',
                         'caption_source': 'explanation_page', 'caption_pages': [1], 'entries': []}
                        for f in (figs[:-1] if len(figs) > 1 else figs)],
            'skipped': [{'figure_id': figs[-1]['figure_id'], 'reason': 'other'}] if len(figs) > 1 else [],
            'pages_consulted': [1]}}
    # a row folds after submission: the split now gives a different item count
    gone = t.due[-1]
    gone.dismissed = True
    gone.save()
    t2 = fl.link_targets(pf, DIGEST, PROMPT)
    rebuilt = fl.items_from_replies(pf, PAGES, t2, DIGEST, PROMPT, replies)
    assert [it['key'] for it in rebuilt] == [it['key'] for it in items]
    asked = {f['figure_id'] for it in rebuilt for f in it['figures'] if not f['locked']}
    assert str(gone.id) not in asked and len(asked) == len(t2.due)
    assert all(any(f['locked'] for f in it['figures']) for it in rebuilt)
    # another prompt version's job is not ours (the digest is not checked:
    # a reading-set digest moves as the paper's other rows get linked)
    assert fl.items_from_replies(pf, PAGES, t2, DIGEST, 'link-v1-other', replies) == []
    check = fl.LinkCheck()
    for it in rebuilt:
        check.merge(fl.validate_link_result(it, replies[it['key']]['result'], PAGES))
    applied = fl.apply_link(t2, check, {}, DIGEST, PROMPT, 'm')
    assert applied.written == 8 and applied.failed == 2
    assert check.unknown == [str(gone.id)]          # the folded row: named by the reply, no longer ours


@pytest.mark.unit
def test_a_reset_row_is_due_again_and_a_persons_caption_is_not(stored):
    """Barrande Pl. 1 came back 'done' with one entry naming five figures —
    the checks let it through, a person would not. Reset makes it due, drops
    the entry and the attempts; a locked caption is refused."""
    from papermeister import figure_link as fl
    from papermeister.models import Figure, FigureEntry
    pf, rows = stored
    t = fl.link_targets(pf, DIGEST, PROMPT)
    plate, body = rows[2], rows[3]
    check = fl.LinkCheck().merge(fl.validate_link_result(
        fl.link_item(pf, PAGES, t, DIGEST, PROMPT), reply(str(plate.id), str(body.id)), PAGES))
    fl.apply_link(t, check, {}, DIGEST, PROMPT, 'm')
    body = Figure.get_by_id(body.id)
    body.caption_locked = True
    body.save()
    assert FigureEntry.select().where(FigureEntry.figure == plate.id).count() == 3
    done, refused = fl.reset_link([plate.id, body.id])
    assert done == [plate.id] and refused == [body.id]
    plate = Figure.get_by_id(plate.id)
    assert plate.link_key == '' and plate.caption == '' and plate.link_attempts == 0 and plate.linked_at is None
    assert FigureEntry.select().where(FigureEntry.figure == plate.id).count() == 0
    assert Figure.get_by_id(body.id).caption.startswith('Fig. 4')
    t2 = fl.link_targets(pf, DIGEST, PROMPT)
    assert [r.id for r in t2.due] == [plate.id] and [r.id for r in t2.context] == [body.id]


@pytest.mark.unit
def test_the_reading_set_widens_with_the_attempts_and_follows_the_papers_habit(stored):
    """The caption is almost always close by, so the first attempt reads the
    figure's neighbourhood and the explanation pages; a failed attempt widens
    to every page naming the figure; a second failure reads it all."""
    from papermeister import figure_link as fl
    from papermeister.models import Figure
    pf, rows = stored
    plate, body = rows[2], rows[3]
    # a 40-page paper: the plate on p.2 (explained on p.1), a page far away
    # citing "Pl. 2" in passing, and a numbered caption on p.30
    pages = list(PAGES) + [''] * 36
    pages[25] = '<div data-bbox="10 10 900 100" data-label="Text"><p>see Pl. 2, fig. 3 for the holotype</p></div>'
    pages[30] = '<div data-bbox="10 10 900 100" data-label="Caption"><p>Fig. 9. Something else.</p></div>'
    tier0 = fl.reading_set(pages, [plate], 0)
    assert tier0 is not None and 1 in tier0 and 2 in tier0 and 25 not in tier0 and 30 not in tier0
    tier1 = fl.reading_set(pages, [plate], 1)
    assert 25 in tier1 and 30 in tier1
    assert fl.reading_set(pages, [plate], 2) is None                    # the whole text
    # the paper's habit: where its other figures were explained
    assert 35 in fl.reading_set(pages, [plate], 0, known_pages={35})
    # a tiny paper: the set is most of it → the whole text
    assert fl.reading_set(PAGES, [plate], 0) is None
    # the tier is the attempt count
    plate.link_attempts = 1
    assert fl.reading_tier([plate, body]) == 1
    plate.link_attempts = 5
    assert fl.reading_tier([plate]) == 2
    # the request names the pages and carries the reading digest; the whole-text one does not
    plate = Figure.get_by_id(plate.id)
    t = fl.link_targets(pf, DIGEST, PROMPT)
    req = fl.link_payload(pf, pages, t, DIGEST, 'c', {'version': PROMPT})
    assert req['reading_pages'] and req['ocr_digest'] == fl.reading_digest(pages, req['reading_pages'])
    assert req['items'][0]['key'].split('@')[1] == req['ocr_digest'][:12]
    ws = fl.workspace_for(pf, pages, req)
    assert [p['page'] for p in ws['pages']] == req['reading_pages'] and ws['ocr_digest'] == req['ocr_digest']
    for r in t.due:
        r.link_attempts = 2
        r.save()
    t = fl.link_targets(pf, DIGEST, PROMPT)
    req = fl.link_payload(pf, pages, t, DIGEST, 'c', {'version': PROMPT})
    assert 'reading_pages' not in req and req['ocr_digest'] == DIGEST
    assert len(fl.workspace_for(pf, pages, req)['pages']) == len(pages)


@pytest.mark.unit
def test_a_plate_run_reads_the_block_before_it_and_designations_in_both_numerals():
    from papermeister import figure_link as fl
    assert fl._block_before_run(12, {10, 11, 12, 13}) == {2, 3, 4, 5, 6, 7, 8, 9}
    assert fl._block_before_run(3, {3}) == {0, 1, 2}
    assert fl._number_forms('3') == ['3', 'III'] and fl._number_forms('IV') == ['IV', '4']
    assert fl._roman(14) == 'XIV' and fl._from_roman('XIV') == 14 and fl._from_roman('ABC') == 0
