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


# ── D: protection in one place, a person's rows speak for their blocks, page doubts (100)

@pytest.mark.unit
def test_the_migration_adds_the_new_columns_to_an_older_figure_table(db):
    """A library whose figure tables were made before D still gets the columns."""
    from papermeister.database import init_db
    from papermeister.paths import DB_PATH
    for table, column in (('figure', 'bbox_locked'), ('figure', 'uncertain_reasons_json'),
                          ('figureentry', 'printed_label'), ('figurepanel', 'annotation')):
        db.execute_sql(f'ALTER TABLE {table} DROP COLUMN {column}')   # (a FK column cannot be dropped)
    db.close()
    database = init_db(DB_PATH)
    for table, column in (('figure', 'bbox_locked'), ('figure', 'continuation_of_id'),
                          ('figureentry', 'printed_label'), ('figurepanel', 'annotation')):
        columns = {row[1] for row in database.execute_sql(f"PRAGMA table_info('{table}')").fetchall()}
        assert column in columns, (table, column)


@pytest.mark.unit
def test_protection_is_one_judgement(paper_file):
    from papermeister.figure_store import protection
    from papermeister.models import Figure
    def row(**kw):
        return Figure(paper=paper_file.paper_id, paper_file=paper_file.id, file_hash=HASH, page=1,
                      bbox_page_1000='[0, 0, 1, 1]', **kw)
    from dataclasses import astuple
    assert not protection(row()).any
    assert astuple(protection(row(user_confirmed=True))) == (True, True, True)
    assert astuple(protection(row(bbox_locked=True))) == (True, False, False)
    assert astuple(protection(row(caption_locked=True))) == (False, True, False)
    assert astuple(protection(row(panels_locked=True))) == (False, False, True)
    assert protection(row(dismissed=True, dismissed_by='user')).any
    assert not protection(row(dismissed=True, dismissed_by='reassembly')).any


@pytest.mark.unit
def test_a_persons_merged_row_keeps_its_pieces_from_coming_back(paper_file):
    """fsis EC §6-14: widen a box and the nightly sync raised the OCR blocks
    inside it as new rows, every night. The merged row lists its blocks."""
    from papermeister import figure_curation as cur
    from papermeister.figure_store import plan_store
    pieces = [fig(page=4, bbox=b, name='') for b in ((100, 100, 480, 480), (520, 100, 900, 480))]
    store(paper_file, pieces)
    cur.apply(cur.plan('merge', rows(paper_file), 'one figure'), os.path.join(
        os.environ['PAPERMEISTER_DATA_DIR'], 'rec.json'))
    survivor = rows(paper_file)[0]
    assert survivor.bbox_locked and json.loads(survivor.bbox_page_1000) == [100, 100, 900, 480]

    plan = plan_store(paper_file, pieces)
    # the first piece's box is now the survivor's union, so it is found by its
    # block; the second still matches the row the person folded
    assert plan.create == [] and plan.absorbed == 1 and plan.untouched_by_rule == 2
    # a new figure the person's row does not cover is still created
    plan = plan_store(paper_file, [*pieces, fig(page=4, bbox=(100, 520, 900, 900))])
    assert len(plan.create) == 1


@pytest.mark.unit
def test_a_block_two_persons_rows_both_claim_is_made_by_neither(paper_file):
    from papermeister.figure_store import plan_store
    from papermeister.models import Figure
    piece = fig(page=4, bbox=(100, 100, 480, 480), name='')
    for box in ((100, 100, 900, 480), (100, 100, 480, 900)):
        Figure.create(paper=paper_file.paper_id, paper_file=paper_file.id, file_hash=HASH, page=4,
                      bbox_page_1000=json.dumps(list(box)), blocks_json=json.dumps([list(piece.bbox)]),
                      bbox_locked=True)
    plan = plan_store(paper_file, [piece])
    assert plan.create == [] and plan.contested == 1


@pytest.mark.unit
def test_a_locked_box_is_left_alone_and_not_reproduced(paper_file):
    from papermeister import figure_curation as cur
    from papermeister.figure_store import plan_store
    original = fig(page=2, bbox=(100, 100, 480, 480))
    store(paper_file, [original])
    cur.apply(cur.plan('set-bbox', rows(paper_file), 'right column left out', bbox=[100, 100, 900, 480]),
              os.path.join(os.environ['PAPERMEISTER_DATA_DIR'], 'rec.json'))
    plan = plan_store(paper_file, [original])
    assert plan.create == [] and plan.move == [] and plan.absorbed == 1 and plan.dismiss == []


@pytest.mark.unit
def test_reassembly_revives_only_its_own_folds(paper_file):
    from papermeister.figure_store import plan_store
    from papermeister.models import Figure
    f = fig()
    store(paper_file, [f])
    row = rows(paper_file)[0]
    row.dismissed, row.dismissed_by = True, 'detect'
    row.save()
    plan = plan_store(paper_file, [f])
    assert plan.restore == [] and plan.untouched_by_rule == 1
    row.dismissed_by = 'reassembly'
    row.save()
    assert len(plan_store(paper_file, [f]).restore) == 1
    assert Figure.select().count() == 1


@pytest.mark.unit
def test_doubts_are_stored_and_refreshed(paper_file):
    from papermeister.figure_store import plan_store
    doubted = AssembledFigure(page=3, bbox=(100, 100, 900, 800), blocks=((100, 100, 900, 800),),
                              assembly=SINGLE, reasons=('no_caption',))
    store(paper_file, [doubted])
    assert json.loads(rows(paper_file)[0].uncertain_reasons_json) == ['no_caption']
    settled = AssembledFigure(page=3, bbox=(100, 100, 900, 800), blocks=((100, 100, 900, 800),),
                              assembly=SINGLE, caption_hint='Fig. 1. Found.')
    plan = plan_store(paper_file, [settled])
    assert len(plan.refresh) == 1
    store(paper_file, [settled])
    assert json.loads(rows(paper_file)[0].uncertain_reasons_json) == []


@pytest.mark.unit
def test_a_page_doubt_gets_a_placeholder_row_that_the_text_tab_does_not_list(paper_file):
    from papermeister import figures
    from papermeister.figure_store import PAGE, figures_for_paper, plan_store, with_placeholders
    from papermeister.models import Figure
    empty_plate = figures.PageAssembly(page=7, picture_blocks=1, verdict='plate',
                                       suspicions=['plate_without_pictures'])
    body = figures.PageAssembly(page=8, picture_blocks=1, figures=[fig(page=8)])
    assembled = with_placeholders([empty_plate, body])
    assert [f.assembly for f in assembled] == [PAGE, SINGLE]
    store(paper_file, assembled)
    placeholder = Figure.get(Figure.assembly == PAGE)
    assert placeholder.page == 7 and json.loads(placeholder.bbox_page_1000) == [0, 0, 1000, 1000]
    assert json.loads(placeholder.uncertain_reasons_json) == ['plate_without_pictures']
    assert [f.page for f in figures_for_paper(paper_file.paper_id)] == [8]
    # settled next time: the placeholder folds like any row
    plan = plan_store(paper_file, [fig(page=8)])
    assert [r.id for r in plan.dismiss] == [placeholder.id] and plan.create == []
