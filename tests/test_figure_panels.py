"""The panel stage from the client's side, and the five-count review.
Replies are hand-made in the shape the client's own schema (G) defines."""
import json
import os
import tempfile

import pytest

from papermeister.figures import PLATE_KIND, SINGLE, AssembledFigure

HASH = 'ab' * 32
PROMPT = 'panels-v1-test'


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-panels-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def plate(db):
    """A linked plate with three entries, and a body figure with one."""
    from papermeister import figure_store
    from papermeister.models import Figure, FigureEntry, Paper, PaperFile
    paper = Paper.create(title='Lee 2004')
    pf = PaperFile.create(paper=paper, path='lee.pdf', hash=HASH, status='processed')
    figs = [AssembledFigure(page=2, bbox=(100, 100, 900, 800), blocks=((100, 100, 480, 480), (520, 100, 900, 480),
                                                                       (100, 520, 900, 800)),
                            assembly='caption_group_union', name_hint='Figure 2', page_kind=PLATE_KIND),
            AssembledFigure(page=3, bbox=(100, 100, 900, 600), blocks=((100, 100, 900, 600),), assembly=SINGLE)]
    figure_store.apply_plan(figure_store.plan_store(pf, figs))
    rows = {r.page: r for r in Figure.select()}
    for row, entries in ((rows[2], ['A', 'B', 'C']), (rows[3], ['1'])):
        row.caption = f'Caption of page {row.page}.'
        row.caption_source = 'same_page'
        row.save()
        for i, label in enumerate(entries):
            FigureEntry.create(figure=row.id, order=i, label=label, description=f'entry {label}')
    return pf, rows


def reply(**overrides):
    r = {'is_compound': True, 'figure_kind': 'fossil_plate', 'non_compound_reason': '', 'notes': [],
         'panels': [{'label': 'A', 'bbox_figure_1000': [0, 0, 480, 480], 'caption_indices': [0], 'confidence': 'high'},
                    {'label': 'B', 'bbox_figure_1000': [520, 0, 1000, 480], 'caption_indices': [1], 'confidence': 'high'},
                    {'label': '', 'bbox_figure_1000': [0, 520, 1000, 1000], 'caption_indices': [], 'confidence': 'medium'}],
         'annotation_indices': [], 'image_size': [1860, 1500]}
    r.update(overrides)
    return r


@pytest.mark.unit
def test_targets_name_every_exclusion(plate):
    from papermeister import figure_panels as fp
    pf, rows = plate
    t = fp.split_targets(pf, PROMPT)
    assert [r.page for r in t.due] == [2] and [why for _, why in t.excluded] == ['entries_lt_2']
    rows[2].panels_locked = True
    rows[2].save()
    assert [why for _, why in fp.split_targets(pf, PROMPT).excluded] == ['panels_locked', 'entries_lt_2']


@pytest.mark.unit
def test_the_key_is_the_image_not_the_entries(plate):
    from papermeister import figure_panels as fp
    pf, rows = plate
    k = fp.panel_key(rows[2], PROMPT)
    assert k.startswith(f'{HASH}|2|[100, 100, 900, 800]|216|') and 'entry' not in k


@pytest.mark.unit
def test_piece_boxes_travel_in_the_figures_frame(plate):
    from papermeister import figure_panels as fp
    pf, rows = plate
    item = fp.panel_item(rows[2], PROMPT)
    assert item['key'].startswith(f'{rows[2].id}@') and item['page'] == 2
    assert item['piece_boxes_figure_1000'] == [[0, 0, 475, 543], [525, 0, 1000, 543], [0, 600, 1000, 1000]]
    assert [e['label'] for e in item['entries']] == ['A', 'B', 'C']
    assert fp.to_page_frame([100, 100, 900, 800], [0, 0, 475, 543]) == [100, 100, 480, 480]


@pytest.mark.unit
def test_a_good_reply_is_written_with_the_orphan_panel_filled_in(plate):
    from papermeister import figure_panels as fp
    from papermeister.models import Figure, FigurePanel
    pf, rows = plate
    item = fp.panel_item(rows[2], PROMPT)
    r = reply()
    check = fp.validate_panel_result(item, r)
    assert check.ok and check.review == []
    # the third panel had no label and no match; one entry was unused: they go together
    assert check.panels[2]['label'] == 'C' and check.panels[2]['caption_indices'] == [2]
    applied = fp.apply_panels(rows[2], item, r, check, PROMPT, 'gpt-6-astra')
    assert applied.written == 1
    panels = list(FigurePanel.select().where(FigurePanel.figure == rows[2].id).order_by(FigurePanel.order))
    assert [p.label for p in panels] == ['A', 'B', 'C']
    assert json.loads(panels[1].entry_orders_json) == [1] and json.loads(panels[2].bbox_figure_1000) == [0, 520, 1000, 1000]
    row = Figure.get_by_id(rows[2].id)
    assert row.kind == 'fossil_plate' and row.is_compound and row.panel_key == fp.panel_key(row, PROMPT)
    assert row.panel_entries_digest == fp.entries_digest(fp.entries_of(row))
    # the same reply again: unchanged; the lane sees it as split
    assert fp.apply_panels(row, item, r, check, PROMPT, 'm').unchanged == 1
    assert [why for _, why in fp.split_targets(pf, PROMPT).excluded][0] == 'split'


@pytest.mark.unit
def test_bad_replies_are_rejected_and_count_an_attempt(plate):
    from papermeister import figure_panels as fp
    from papermeister.models import Figure
    pf, rows = plate
    item = fp.panel_item(rows[2], PROMPT)
    for bad, why in (
        (reply(panels=[{'label': 'A', 'bbox_figure_1000': [900, 0, 100, 480], 'caption_indices': [0], 'confidence': 'high'}]),
         'invalid_box'),
        (reply(panels=[{'label': 'A', 'bbox_figure_1000': [0, 0, 480, 480], 'caption_indices': [7], 'confidence': 'high'}]),
         'invalid_caption_index'),
        (reply(is_compound=False), 'single_figure_many_panels'),
        (reply(figure_kind='painting'), 'invalid_figure_kind'),
        (reply(non_compound_reason='dunno'), 'invalid_non_compound_reason'),
    ):
        check = fp.validate_panel_result(item, bad)
        assert not check.ok and check.why == why
    applied = fp.apply_panels(rows[2], item, reply(is_compound=False), fp.validate_panel_result(item, reply(is_compound=False)), PROMPT, 'm')
    assert applied.failed == 1 and Figure.get_by_id(rows[2].id).panel_attempts == 1


@pytest.mark.unit
def test_doubts_a_person_should_see(plate):
    from papermeister import figure_panels as fp
    pf, rows = plate
    item = fp.panel_item(rows[2], PROMPT)
    assert fp.validate_panel_result(item, reply(panels=[], is_compound=False)).review == [fp.PANELS_0]
    one = reply(is_compound=False, non_compound_reason='single_image_many_captions',
                panels=[{'label': '', 'bbox_figure_1000': [0, 0, 1000, 1000], 'caption_indices': [], 'confidence': 'high'}])
    assert fp.validate_panel_result(item, one, siblings_on_page=2).review == [fp.PANELS_1_WITH_SIBLINGS, fp.SINGLE_IMAGE_MANY_CAPTIONS]
    many = reply(panels=[{'label': str(i), 'bbox_figure_1000': [i * 100, 0, i * 100 + 90, 500], 'caption_indices': [], 'confidence': 'low'}
                         for i in range(8)])
    assert fp.validate_panel_result(item, many).review == [fp.PANEL_COUNT_OUT_OF_RANGE]
    # legend marks are not counted as entries when judging the panel count
    legend = reply(annotation_indices=[1, 2], panels=[reply()['panels'][0]])
    assert fp.validate_panel_result(item, legend).review == []
    # one entry on two panels (Naimark 2006 Fig. 2: a photograph and its
    # outline drawing per specimen) is accepted and marked for a look
    paired = reply(panels=[
        {'label': '', 'bbox_figure_1000': [0, 0, 480, 480], 'caption_indices': [0], 'confidence': 'high'},
        {'label': 'A', 'bbox_figure_1000': [520, 0, 1000, 480], 'caption_indices': [0], 'confidence': 'high'},
        {'label': 'B', 'bbox_figure_1000': [0, 520, 1000, 1000], 'caption_indices': [1], 'confidence': 'high'}])
    check = fp.validate_panel_result(item, paired)
    assert check.ok and check.review == [fp.ENTRY_ON_SEVERAL_PANELS]
    assert [p['label'] for p in check.panels] == ['A', 'A', 'B']       # the unlabelled twin takes its entry's label
    # the same index twice on one panel is still a fault
    assert fp.validate_panel_result(item, reply(panels=[
        {'label': 'A', 'bbox_figure_1000': [0, 0, 480, 480], 'caption_indices': [0, 0], 'confidence': 'high'}])).why == 'duplicate_caption_index'


@pytest.mark.unit
def test_changed_entries_re_attach_by_label_and_re_cut_only_when_they_cannot(plate):
    from papermeister import figure_panels as fp
    from papermeister.models import Figure, FigureEntry, FigurePanel
    pf, rows = plate
    item = fp.panel_item(rows[2], PROMPT)
    r = reply()
    fp.apply_panels(rows[2], item, r, fp.validate_panel_result(item, r), PROMPT, 'm')
    # a person fixes entry B's description and adds nothing: same labels
    e = FigureEntry.get((FigureEntry.figure == rows[2].id) & (FigureEntry.label == 'B'))
    e.description = 'entry B, corrected'
    e.save()
    t = fp.split_targets(pf, PROMPT)
    assert t.due == [] and [x.id for x in t.rematch] == [rows[2].id]
    done, note = fp.rematch(Figure.get_by_id(rows[2].id))
    assert done and fp.split_targets(pf, PROMPT).rematch == []
    # now the labels change to numbers: nothing to match by → flagged, not re-cut silently
    for e in FigureEntry.select().where(FigureEntry.figure == rows[2].id):
        e.label = str(e.order + 1)
        e.save()
    done, note = fp.rematch(Figure.get_by_id(rows[2].id))
    assert not done and 'matches 0' in note
    assert fp.ENTRIES_CHANGED_UNMAPPED in json.loads(Figure.get_by_id(rows[2].id).uncertain_reasons_json)
    assert FigurePanel.select().where(FigurePanel.figure == rows[2].id).count() == 3   # boxes kept


@pytest.mark.unit
def test_maps_are_skipped_only_on_a_re_cut(plate):
    from papermeister import figure_panels as fp
    pf, rows = plate
    rows[2].kind = 'map'
    rows[2].save()
    assert [r.id for r in fp.split_targets(pf, PROMPT).due] == [rows[2].id]     # never cut: kind is a guess
    rows[2].panel_key = 'old|key'
    rows[2].save()
    assert [why for _, why in fp.split_targets(pf, PROMPT).excluded][0] == 'map'
    assert [r.id for r in fp.split_targets(pf, PROMPT, include_maps=True).due] == [rows[2].id]


@pytest.mark.unit
def test_the_review_reports_five_counts_from_the_lanes_judgements(plate):
    from papermeister import figure_review as fr
    pf, rows = plate
    rows[3].uncertain_reasons_json = json.dumps(['no_caption', 'text_as_figure'])
    rows[3].bbox_locked = True
    rows[3].save()
    pages = ['<div data-label="Text" data-bbox="0 0 10 10">x</div>'] * 4
    rv = fr.review_file(pf, pages, 'link-v1', PROMPT)
    assert rv.figures == 2
    assert rv.auto_pending['link'] == 2 and rv.auto_pending['panels'] == 1
    assert rv.auto_pending['detect'] == 0            # the locked row is a person's; detect keeps off
    assert rv.human['no_caption'] == 1 and rv.human['text_as_figure'] == 1
    assert rv.outside['panels: entries_lt_2'] == 1 and rv.preserved['bbox_locked'] == 1
    text = fr.format_review(rv, 1)
    assert '1. Waiting for a stage' in text and '5. Preserved' in text
