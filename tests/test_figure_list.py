"""The Text tab's figure list: what a person reviews assembly against (P16 Phase 1)."""
import pytest

from desktop.services.paper_service import FigureRow


def row(**kw):
    base = {'id': 1, 'page': 0, 'name': 'Fig. 1', 'assembly': 'single', 'pieces': 1,
            'caption': '', 'caption_hint': ''}
    base.update(kw)
    return FigureRow(**base)


@pytest.mark.ui
def test_each_figure_says_its_page_and_how_it_was_assembled(qapp):
    from desktop.components.figure_list import FigureList

    widget = FigureList([
        row(name='Plate 2', page=39, assembly='plate_page_union', pieces=8),
        row(name='Figure 2', page=1, assembly='caption_group_union', pieces=4, caption_hint='Figure 2 | ...'),
        row(name='', page=4),
    ])
    lines = [widget.list.item(i).text() for i in range(widget.list.count())]

    assert lines == [
        'Plate 2  ·  p. 40  ·  plate, 8 photos  ·  no caption found',
        'Figure 2  ·  p. 2  ·  4 pieces  ·  caption hint',
        'Unnamed figure  ·  p. 5  ·  no caption found',
    ]


@pytest.mark.ui
def test_an_inferred_plate_number_says_so(qapp):
    """The number was read off a neighbouring page, not this one — the reviewer should know."""
    from desktop.components.figure_list import FigureList

    widget = FigureList([row(name='Plate I', page=13, assembly='plate_page_union', pieces=12, plate_inferred=True)])
    assert 'plate number inferred' in widget.list.item(0).text()


@pytest.mark.ui
def test_a_caption_hint_is_not_presented_as_the_caption(qapp):
    from desktop.components.figure_list import FigureList

    widget = FigureList([row(caption_hint='Fig. 1. Guessed by assembly.')])
    assert widget.list.item(0).toolTip().startswith('Caption hint (not yet linked)')


@pytest.mark.ui
def test_choosing_a_figure_asks_for_its_page(qapp):
    from desktop.components.figure_list import FigureList

    widget = FigureList([row(page=0), row(page=12)])
    asked = []
    widget.page_requested.connect(asked.append)
    widget.list.itemClicked.emit(widget.list.item(1))

    assert asked == [12]


@pytest.mark.ui
def test_the_line_says_what_the_split_left(qapp):
    """Phase 5 step 1: a plate with 33 panels for 33 entries reads as done; an
    entry no panel claims is the reviewer's first stop; a failed split says so."""
    from desktop.components.figure_list import FigureList

    widget = FigureList([
        row(name='Plate I', page=34, assembly='plate_page_union', pieces=33, caption='PLATE I.',
            entries=33, panels=33, panel_state='split'),
        row(name='Plate XI', page=44, assembly='plate_page_union', pieces=22, caption='PLATE XI.',
            entries=23, panels=22, unmatched=1, panel_state='split'),
        row(name='Fig. 11', page=27, caption='Fig. 11.', entries=6, panel_state='failed'),
        row(name='Fig. 4', page=3, caption='Fig. 4.', panel_state='single'),
        row(name='Fig. 5', page=5, caption='Fig. 5.', entries=4),
    ])
    lines = [widget.list.item(i).text() for i in range(widget.list.count())]
    assert lines[0].endswith('caption  ·  33 panels / 33 entries')
    assert lines[1].endswith('22 panels / 23 entries  ·  1 unmatched')
    assert lines[2].endswith('caption  ·  panels failed, 6 entries')
    assert lines[3].endswith('caption  ·  single image')
    assert lines[4].endswith('caption  ·  4 entries')
    assert 'no panel' in widget.list.item(1).toolTip() and widget.list.item(1).toolTip().startswith('PLATE XI.')
