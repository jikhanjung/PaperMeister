"""Keeping assembled figures: re-running assembly must never cost a person's work.

The assembly rules will keep changing — Phase 0 changed them twice in a day —
and each re-run lands on rows that may already carry a linked caption or panels
someone checked. fsis2026 deleted source rows mid-churn and lost 95 of them. So
these tests are about what survives a re-run, not about the insert.
"""
import json
import os
import tempfile

import pytest

from papermeister.figures import CAPTION_GROUP, PLATE_UNION, SINGLE, AssembledFigure

HASH = 'ab' * 32


@pytest.fixture
def db(monkeypatch):
    """A real SQLite database with the real schema, migrations included."""
    work = tempfile.mkdtemp(prefix='pm-figures-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def paper_file(db):
    from papermeister.models import Paper, PaperFile
    paper = Paper.create(title='Bruton et al. 2004')
    return PaperFile.create(paper=paper, path='bruton.pdf', hash=HASH, status='processed')


def fig(page=3, bbox=(100, 100, 900, 800), assembly=SINGLE, name='Fig. 1', caption='Fig. 1. A trilobite.'):
    return AssembledFigure(page=page, bbox=bbox, blocks=(bbox,), assembly=assembly,
                           name_hint=name, caption_hint=caption)


def store(pf, assembled):
    from papermeister import figure_store
    plan = figure_store.plan_store(pf, assembled)
    figure_store.apply_plan(plan)
    return plan


def rows(pf):
    from papermeister.models import Figure
    return list(Figure.select().where(Figure.paper_file == pf.id).order_by(Figure.id))


@pytest.mark.unit
def test_the_tables_exist_on_an_existing_database(db):
    tables = set(db.get_tables())
    assert {'figure', 'figureentry', 'figurepanel'} <= tables


@pytest.mark.unit
def test_an_assembly_is_stored_with_its_page_box_and_hints(paper_file):
    plate = AssembledFigure(page=40, bbox=(90, 100, 910, 880), blocks=((90, 100, 500, 400), (510, 100, 910, 880)),
                            assembly=PLATE_UNION, plate=2, name_hint='Plate 2')
    store(paper_file, [fig(), plate])

    stored = rows(paper_file)
    assert [(r.page, r.assembly, r.name) for r in stored] == [(3, SINGLE, 'Fig. 1'), (40, PLATE_UNION, 'Plate 2')]
    assert json.loads(stored[1].bbox_page_1000) == [90, 100, 910, 880]
    assert len(json.loads(stored[1].blocks_json)) == 2
    assert stored[1].plate == 2
    assert stored[0].caption_hint == 'Fig. 1. A trilobite.'
    assert stored[0].caption == ''          # a hint is not a caption
    assert stored[0].file_hash == HASH


@pytest.mark.unit
def test_a_dry_run_writes_nothing(paper_file):
    from papermeister import figure_store
    plan = figure_store.plan_store(paper_file, [fig()])
    assert len(plan.create) == 1
    assert rows(paper_file) == []


@pytest.mark.unit
def test_running_the_same_assembly_again_changes_nothing(paper_file):
    store(paper_file, [fig()])
    again = store(paper_file, [fig()])
    assert again.changes == 0
    assert len(rows(paper_file)) == 1


@pytest.mark.unit
def test_a_figure_a_new_rule_stops_producing_is_folded_not_deleted(paper_file):
    """The Phase 0 kind of change: two single figures become one cut-up figure."""
    left, right = fig(bbox=(100, 100, 480, 500)), fig(bbox=(520, 100, 900, 500), name='')
    store(paper_file, [left, right])
    first_ids = [r.id for r in rows(paper_file)]

    merged = AssembledFigure(page=3, bbox=(100, 100, 900, 500), blocks=(left.bbox, right.bbox),
                             assembly=CAPTION_GROUP, name_hint='Fig. 1', label_hints=('A', 'B'))
    plan = store(paper_file, [merged])

    assert (len(plan.create), len(plan.dismiss)) == (1, 2)
    by_id = {r.id: r for r in rows(paper_file)}
    assert all(by_id[i].dismissed and by_id[i].dismissed_by == 'reassembly' for i in first_ids)


@pytest.mark.unit
def test_a_folded_figure_comes_back_when_the_rule_is_reverted(paper_file):
    store(paper_file, [fig()])
    store(paper_file, [])
    plan = store(paper_file, [fig()])

    assert (len(plan.restore), len(plan.create)) == (1, 0)
    (row,) = rows(paper_file)
    assert not row.dismissed and row.dismissed_by == ''


@pytest.mark.unit
def test_a_figure_a_person_confirmed_is_never_touched(paper_file):
    store(paper_file, [fig()])
    (row,) = rows(paper_file)
    row.user_confirmed = True
    row.name = 'Fig. 1 (corrected)'
    row.save()

    store(paper_file, [])                                   # rule no longer produces it
    store(paper_file, [fig(name='Fig. 7')])                 # rule produces it with another name

    (row,) = rows(paper_file)
    assert not row.dismissed
    assert row.name == 'Fig. 1 (corrected)'


@pytest.mark.unit
def test_a_figure_a_person_dismissed_stays_dismissed(paper_file):
    store(paper_file, [fig()])
    (row,) = rows(paper_file)
    row.dismissed, row.dismissed_by = True, 'user'
    row.save()

    plan = store(paper_file, [fig()])

    assert plan.untouched_by_rule == 1
    assert rows(paper_file)[0].dismissed


@pytest.mark.unit
def test_hints_refresh_but_a_linked_name_is_kept(paper_file):
    import datetime
    store(paper_file, [fig()])
    (row,) = rows(paper_file)
    row.name, row.linked_at = 'Text-fig. 1', datetime.datetime.now()
    row.save()

    plan = store(paper_file, [fig(name='Fig. 1', caption='Fig. 1. A better-read caption.')])

    assert len(plan.refresh) == 1
    (row,) = rows(paper_file)
    assert row.caption_hint == 'Fig. 1. A better-read caption.'
    assert row.name == 'Text-fig. 1'


@pytest.mark.unit
def test_a_figure_whose_box_moved_after_a_re_ocr_keeps_its_row_and_caption(paper_file):
    """A re-OCR draws the same block a few permille differently. Folding the row and
    creating a new one would lose the linked caption (fsis 'shifted' rows)."""
    import datetime
    store(paper_file, [fig()])
    (row,) = rows(paper_file)
    row.caption, row.linked_at = 'Fig. 1. The linked caption.', datetime.datetime.now()
    row.save()

    plan = store(paper_file, [fig(bbox=(104, 97, 903, 806))])

    assert (len(plan.move), len(plan.create), len(plan.dismiss)) == (1, 0, 0)
    (row,) = rows(paper_file)
    assert json.loads(row.bbox_page_1000) == [104, 97, 903, 806]
    assert row.caption == 'Fig. 1. The linked caption.'


@pytest.mark.unit
def test_a_page_kind_and_an_inferred_plate_number_are_stored(paper_file):
    plate = AssembledFigure(page=14, bbox=(90, 100, 910, 880), blocks=((90, 100, 910, 880),),
                            assembly=SINGLE, plate=1, name_hint='Plate I', page_kind='plate',
                            plate_inferred=True)
    store(paper_file, [plate])
    (row,) = rows(paper_file)
    assert (row.page_kind, row.plate, row.plate_inferred) == ('plate', 1, True)


@pytest.mark.unit
def test_figures_of_an_earlier_pdf_edition_are_folded(paper_file):
    store(paper_file, [fig()])
    paper_file.hash = 'cd' * 32
    paper_file.save()

    plan = store(paper_file, [fig()])

    assert (len(plan.create), len(plan.dismiss)) == (1, 1)
    live = [r for r in rows(paper_file) if not r.dismissed]
    assert [r.file_hash for r in live] == ['cd' * 32]


@pytest.mark.unit
def test_the_paper_lists_live_figures_in_reading_order(paper_file):
    from papermeister import figure_store
    store(paper_file, [fig(page=9, name='Fig. 3'), fig(page=2, name='Fig. 2')])
    folded = rows(paper_file)[0]
    folded.dismissed, folded.dismissed_by = True, 'user'
    folded.save()

    assert [f.name for f in figure_store.figures_for_paper(paper_file.paper_id)] == ['Fig. 2']


@pytest.mark.unit
def test_deleting_the_file_deletes_its_figures(paper_file):
    from papermeister.models import Figure
    store(paper_file, [fig()])
    paper_file.delete_instance()
    assert Figure.select().count() == 0
