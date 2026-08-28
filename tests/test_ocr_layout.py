"""Rebuilding a page from what the OCR said each block was.

Chandra2 returns HTML whose divs carry a label and a bbox, and the Text tab
used to hand the whole thing to a markdown renderer — which flattens headings,
captions and figures into one undifferentiated column. These tests pin the
parts of the rebuild that are easy to get quietly wrong: block boundaries when
a figure nests divs inside itself, the coordinate space the bboxes live in, and
the fact that a figure's pixels come from the PDF rather than from the OCR.
"""
import pytest

from papermeister import ocr_layout as layout

STRUCTURED = '''
<div data-bbox="85 47 158 61" data-label="Page-Header">
<p>Fossils 86</p>
</div>
<div data-bbox="85 466 210 479" data-label="Section-Header">
<h4>Etymology</h4>
</div>
<div data-bbox="85 481 479 629" data-label="Text">
<p>The generic name is derived from the Greek <i>meg&#225;lo</i>.</p>
</div>
<div data-bbox="240 89 760 293" data-label="Figure">
<img alt="Map of the equatorial Pacific."/>
</div>
<div data-bbox="85 295 205 308" data-label="Caption">
<p>Fig. 1. Studied locality.</p>
</div>
'''


@pytest.mark.unit
def test_structured_pages_are_recognised():
    assert layout.is_structured(STRUCTURED)
    assert not layout.is_structured('## Etymology\n\nThe generic name is...')
    assert not layout.is_structured('')


@pytest.mark.unit
def test_blocks_carry_their_label_and_box():
    blocks = layout.parse_blocks(STRUCTURED)
    assert [b.label for b in blocks] == [
        'Page-Header', 'Section-Header', 'Text', 'Figure', 'Caption']
    assert blocks[3].bbox == (240, 89, 760, 293)
    assert blocks[3].is_picture


@pytest.mark.unit
def test_a_nested_figure_does_not_end_at_its_first_close_tag():
    """Chandra sometimes draws a figure as HTML instead of describing it, and
    that markup nests divs. Ending the block at the first `</div>` would spill
    the rest of the figure into the document as loose markup."""
    page = (
        '<div data-bbox="10 10 90 90" data-label="Figure">'
        '<div style="border: 1px solid black;"><p>CG</p></div>'
        '<div style="border-radius: 50%;"></div>'
        '</div>'
        '<div data-bbox="10 95 90 99" data-label="Text"><p>after</p></div>'
    )
    blocks = layout.parse_blocks(page)
    assert [b.label for b in blocks] == ['Figure', 'Text']
    assert 'border-radius' in blocks[0].html
    assert blocks[1].html == '<p>after</p>'


@pytest.mark.unit
def test_a_block_left_unclosed_keeps_its_text():
    blocks = layout.parse_blocks('<div data-label="Text"><p>truncated mid-page')
    assert len(blocks) == 1
    assert 'truncated mid-page' in blocks[0].html


@pytest.mark.unit
def test_text_outside_any_block_survives():
    blocks = layout.parse_blocks('loose words<div data-label="Text"><p>in</p></div>')
    assert [b.label for b in blocks] == ['', 'Text']
    assert blocks[0].html == 'loose words'


@pytest.mark.unit
@pytest.mark.parametrize('bad', ['', 'nonsense', '1 2 3', '5 5 5 5', '90 90 10 10'])
def test_unusable_boxes_are_dropped_not_guessed(bad):
    blocks = layout.parse_blocks(f'<div data-bbox="{bad}" data-label="Figure"><p>x</p></div>')
    assert blocks[0].bbox is None
    assert not blocks[0].is_picture      # nothing to crop without a rectangle


@pytest.mark.unit
def test_boxes_are_fractions_of_each_axis_independently():
    """Verified against the live library: a bbox maps onto a rendered page as
    x/1000 of its width and y/1000 of its height. Treating the pair as one
    square canvas lands the crop on the wrong part of a portrait page."""
    left, top, right, bottom = layout.crop_box((107, 80, 653, 487), 1240, 1754, pad=0)
    assert (left, top) == (133, 140)
    assert (right, bottom) == (810, 854)


@pytest.mark.unit
def test_crops_are_padded_but_stay_on_the_page():
    box = layout.crop_box((0, 0, 1000, 1000), 800, 1000)
    assert box == (0, 0, 800, 1000)      # padding cannot push past the edge


@pytest.mark.unit
def test_a_full_width_figure_fills_the_panel():
    width, _ = layout.display_size((50, 100, 950, 400), 595, 842, available=700)
    assert width == 700


@pytest.mark.unit
def test_a_small_inset_stays_small():
    """Sized in proportion to the page it came from, so an inset is not blown
    up to the same width as a full-page plate."""
    width, _ = layout.display_size((100, 100, 400, 300), 595, 842, available=700)
    assert 200 < width < 300


@pytest.mark.unit
def test_display_height_follows_the_pages_own_proportions():
    # A square-looking bbox on a portrait page is taller than it is wide.
    width, height = layout.display_size((100, 100, 500, 500), 595, 842, available=700)
    assert height > width


@pytest.mark.unit
def test_figure_uri_round_trips():
    uri = layout.figure_uri(3, (107, 80, 653, 487))
    assert layout.parse_figure_uri(uri) == (3, (107, 80, 653, 487))
    assert layout.parse_figure_uri('https://example.com/x.png') is None
    assert layout.parse_figure_uri('pmfig:nonsense') is None


@pytest.mark.unit
def test_page_html_gives_each_label_its_own_shape():
    html = layout.page_html(STRUCTURED, page=2, sizer=lambda p, b: (400, 200))
    assert '<h2 class="pm-section">Etymology</h2>' in html   # h4 normalised
    assert 'class="pm-caption"' in html
    assert 'src="pmfig:2/240/89/760/293"' in html
    assert 'width="400" height="200"' in html                # space reserved
    assert 'Fossils 86' not in html                          # running head dropped


@pytest.mark.unit
def test_the_ocr_impression_of_a_figure_is_never_shown():
    """The alt text is kept as the image's description, but Chandra's HTML
    rendition of the artwork is dropped — it renders as nonsense."""
    page = (
        '<div data-bbox="10 10 90 90" data-label="Figure">'
        '<div style="border-radius: 50%;">CG</div>'
        '<img alt="A circle labelled CG."/>'
        '</div>'
    )
    html = layout.page_html(page, page=0, sizer=lambda p, b: (100, 100))
    assert 'border-radius' not in html
    assert 'A circle labelled CG.' in html


@pytest.mark.unit
def test_a_figure_with_no_pdf_degrades_to_its_description():
    html = layout.page_html(STRUCTURED, page=0, sizer=lambda p, b: None)
    assert '<img' not in html
    assert 'Map of the equatorial Pacific.' in html


@pytest.mark.unit
def test_tables_keep_their_markup():
    """A table is real text — it stays selectable rather than becoming a
    picture, which is the whole reason pictures are handled separately."""
    page = '<div data-bbox="1 1 99 99" data-label="Table"><table><tr><td>x</td></tr></table></div>'
    assert '<table>' in layout.page_html(page, page=0)


@pytest.mark.unit
def test_only_pages_with_croppable_pictures_are_listed():
    """Which pages get measured and rendered — the difference between opening
    a 477-page plate volume and hanging on it."""
    pages = [
        '<div data-label="Text"><p>no pictures here</p></div>',
        STRUCTURED,
        '## plain markdown page',
        '<div data-bbox="1 1 9 9" data-label="Image"><img alt="logo"/></div>',
    ]
    assert layout.picture_pages(pages) == [1, 3]


@pytest.mark.unit
def test_document_html_marks_pages_and_skips_empty_ones():
    html = layout.document_html(['', STRUCTURED, ''], sizer=lambda p, b: (10, 10))
    assert html.count('pm-page-mark') == 1
    assert 'page 2' in html      # numbered for the reader, not zero-based
