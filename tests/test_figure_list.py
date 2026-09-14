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
