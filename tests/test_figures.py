"""Figure assembly: which OCR picture blocks make one figure.

The cases here are the ones fsis2026 found the expensive way on a live library —
a plate cut into a block per photograph, a body-figure page that also mentions a
plate, a header logo, a caption in the other column — because each of them
looks like a working assembler right up to the point where panel splitting is
handed the wrong rectangle.
"""
import pytest

from papermeister import figures


def div(label, bbox, inner=''):
    return f'<div data-bbox="{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}" data-label="{label}">{inner}</div>'


def page(*blocks):
    return ''.join(blocks)


PLATE_PAGE = page(
    div('Page-Header', (100, 30, 600, 50), '<p>S.Y. Yang, PLATE IV, Jour. Geol. Soc. Korea</p>'),
    div('Image', (100, 100, 450, 400)),
    div('Image', (500, 100, 900, 400)),
    div('Image', (100, 450, 900, 850)),
)


# ── plate pages ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_a_plate_page_is_one_figure_covering_every_photograph():
    result = figures.assemble_page(10, PLATE_PAGE)

    assert result.verdict == figures.PLATE
    assert len(result.figures) == 1
    plate = result.figures[0]
    assert plate.assembly == 'plate_page_union'
    assert plate.bbox == (100, 100, 900, 850)
    assert len(plate.blocks) == 3               # kept so the merge can be undone
    assert plate.plate == 4
    assert plate.name_hint == 'Plate IV'


@pytest.mark.unit
def test_small_plate_photographs_are_not_filtered_out():
    """fsis's width filter dropped 766 of 1,198 plate photographs. Plates are
    made of small pictures; the size floor does not apply to them."""
    small = page(
        div('Page-Header', (100, 30, 600, 50), '<p>Plate 2</p>'),
        *[div('Image', (100 + i * 70, 200, 160 + i * 70, 250)) for i in range(6)],
    )
    result = figures.assemble_page(0, small)

    assert result.verdict == figures.PLATE
    assert len(result.figures[0].blocks) == 6


@pytest.mark.unit
def test_a_header_logo_does_not_stretch_the_plate_into_the_page_chrome():
    with_logo = page(
        div('Page-Header', (300, 20, 700, 45), '<p>PLATE 3</p>'),
        div('Image', (40, 15, 90, 60)),           # journal logo in the running head
        div('Image', (100, 150, 500, 500)),
        div('Image', (520, 150, 900, 500)),
    )
    result = figures.assemble_page(0, with_logo)

    assert result.figures[0].bbox == (100, 150, 900, 500)
    assert result.dropped == {figures.CHROME: 1}


@pytest.mark.unit
def test_a_body_figure_page_is_not_merged_even_if_it_mentions_a_plate():
    """ref 3265 p.6 in fsis: Fig. 3 and Fig. 4 on a page whose caption also
    cites a plate."""
    body = page(
        div('Image', (100, 100, 450, 400)),
        div('Caption', (100, 410, 450, 440), '<p>Fig. 3. Specimen, compare Pl. 2.</p>'),
        div('Image', (500, 100, 900, 400)),
        div('Caption', (500, 410, 900, 440), '<p>Fig. 4. Another specimen.</p>'),
    )
    result = figures.assemble_page(5, body)

    assert result.verdict == figures.TEXT_FIGURE
    assert [f.assembly for f in result.figures] == ['single', 'single']
    assert [f.name_hint for f in result.figures] == ['Fig. 3', 'Fig. 4']


@pytest.mark.unit
def test_two_plate_numbers_on_one_page_are_left_alone():
    """Possibly two half-page plates. Merging would glue them into one."""
    two = page(
        div('Section-Header', (100, 60, 400, 80), '<h2>Plate 5</h2>'),
        div('Image', (100, 100, 900, 400)),
        div('Section-Header', (100, 460, 400, 480), '<h2>Plate 6</h2>'),
        div('Image', (100, 500, 900, 850)),
    )
    result = figures.assemble_page(0, two)

    assert result.verdict == figures.MANY_MARKS
    assert all(f.assembly == 'single' for f in result.figures)


@pytest.mark.unit
def test_one_plate_numbered_by_both_journal_and_authors_is_still_one_plate():
    """Bruton et al. 2004 in Palaeontographica: "Tafel 13" and "Plate 2" head the
    same page. Leaving it unmerged split every plate in the paper."""
    dual = page(
        div('Page-Header', (100, 20, 500, 40), '<p>Palaeontographica Abt. A Band 271, Tafel 13</p>'),
        div('Page-Header', (600, 20, 900, 40), '<p>BRUTON et al., Plate 2</p>'),
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
    )
    result = figures.assemble_page(40, dual)

    assert result.verdict == figures.PLATE
    assert (result.figures[0].plate, result.figures[0].name_hint) == (2, 'Plate 2')


@pytest.mark.unit
def test_two_numbers_in_one_scheme_are_two_plates():
    """Zhou et al. 1982 atlas: 图版 58 and 图版 59 share a page."""
    atlas = page(
        div('Caption', (100, 440, 400, 460), '<p>图版 58</p>'),
        div('Image', (100, 50, 900, 430)),
        div('Caption', (100, 900, 400, 920), '<p>图版 59</p>'),
        div('Image', (100, 480, 900, 890)),
    )
    assert figures.assemble_page(60, atlas).verdict == figures.MANY_MARKS


@pytest.mark.unit
def test_a_plate_mark_in_body_text_does_not_make_a_plate_page():
    cited = page(
        div('Text', (100, 50, 900, 90), '<p>The holotype is figured on Plate 7.</p>'),
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
    )
    assert figures.assemble_page(0, cited).verdict == figures.NO_MARK


@pytest.mark.unit
@pytest.mark.parametrize('header,number', [
    ('도판 3', 3), ('圖版 1', 1), ('図版 12', 12), ('图版 2', 2),
    ('Tafel XII', 12), ('Taf. 4', 4), ('Таблица I', 1), ('PLATE XXXI', 31),
    ('Planche 9', 9), ('Pl. 3', 3),
])
def test_plate_marks_in_the_languages_this_library_is_written_in(header, number):
    blocks = figures.ocr_layout.parse_blocks(div('Page-Header', (0, 0, 500, 40), f'<p>{header}</p>'))
    assert figures.plate_marks(blocks) == {number: header.split()[-1]}


@pytest.mark.unit
@pytest.mark.parametrize('text', ['Plate mix', 'plates show', 'Plate is shown', 'Pl. DCCCC'])
def test_words_after_the_keyword_are_not_numerals(text):
    """Printed plate numerals are capitals; "Plate mix" is not plate 1009, and a
    four-digit roman numeral is a misread."""
    blocks = figures.ocr_layout.parse_blocks(div('Page-Header', (0, 0, 500, 40), f'<p>{text}</p>'))
    assert figures.plate_marks(blocks) == {}


@pytest.mark.unit
@pytest.mark.parametrize('token,value', [('I', 1), ('IV', 4), ('XXXI', 31), ('XLIV', 44), ('Q', None), ('', None)])
def test_roman_numerals_are_computed_not_looked_up(token, value):
    """fsis's I..XXX table lost every plate after the thirtieth."""
    assert figures.roman_number(token) == value


# ── ordinary pages ───────────────────────────────────────────────────

@pytest.mark.unit
def test_one_picture_is_one_figure_with_its_caption_as_a_hint():
    single = page(
        div('Image', (100, 100, 900, 500)),
        div('Caption', (100, 520, 900, 560), '<p>Figure 2. Map of the study area.</p>'),
    )
    result = figures.assemble_page(1, single)

    assert result.verdict == figures.FEW_PICTURES
    figure = result.figures[0]
    assert figure.caption_hint == 'Figure 2. Map of the study area.'
    assert figure.name_hint == 'Figure 2'


@pytest.mark.unit
def test_a_caption_in_the_other_column_is_not_this_figures():
    two_columns = page(
        div('Image', (60, 100, 480, 400)),
        div('Caption', (520, 410, 940, 440), '<p>Fig. 5. Belongs to the right column.</p>'),
    )
    assert figures.assemble_page(0, two_columns).figures[0].caption_hint == ''


@pytest.mark.unit
def test_a_caption_above_the_figure_is_not_taken():
    above = page(
        div('Caption', (100, 60, 900, 90), '<p>Table 1. Measurements.</p>'),
        div('Image', (100, 100, 900, 500)),
    )
    assert figures.assemble_page(0, above).figures[0].caption_hint == ''


@pytest.mark.unit
def test_a_caption_too_far_below_is_not_taken():
    far = page(
        div('Image', (100, 100, 900, 300)),
        div('Caption', (100, 700, 900, 730), '<p>Fig. 9. Somewhere else.</p>'),
    )
    assert figures.assemble_page(0, far).figures[0].caption_hint == ''


@pytest.mark.unit
def test_tiny_pictures_on_ordinary_pages_are_dropped():
    icons = page(
        div('Image', (100, 300, 130, 330)),           # an inline symbol
        div('Image', (100, 400, 900, 800)),
    )
    result = figures.assemble_page(0, icons)

    assert len(result.figures) == 1
    assert result.dropped == {figures.TINY: 1}


@pytest.mark.unit
def test_pictures_without_a_box_are_not_figures():
    boxless = '<div data-label="Image"><img alt="x"/></div>'
    assert figures.assemble_page(0, boxless).figures == []


@pytest.mark.unit
def test_legacy_markdown_pages_assemble_to_nothing():
    assert figures.assemble_page(0, '## Results\n\nFigure 1 shows...').figures == []


@pytest.mark.unit
def test_a_document_keeps_page_order_and_zero_based_numbering():
    result = figures.assemble_document(['', PLATE_PAGE, ''])
    assert [p.page for p in result] == [0, 1, 2]
    assert result[1].figures[0].page == 1


# ── figures the OCR cut into pieces ──────────────────────────────────

@pytest.mark.unit
def test_pieces_over_one_figure_caption_are_one_figure_with_their_labels():
    """Iv et al. 2015 p.2: four photographs lettered A–D over "Figure 2"."""
    cut_up = page(
        div('Caption', (228, 63, 497, 78), '<p>A. Ajacingenia yanshini</p>'),
        div('Image', (265, 78, 454, 217)),
        div('Caption', (517, 63, 767, 78), '<p>C. Khaan mckennai</p>'),
        div('Image', (558, 84, 721, 171)),
        div('Caption', (226, 213, 503, 228), '<p>B. Conchoraptor gracilis</p>'),
        div('Image', (260, 229, 495, 350)),
        div('Caption', (518, 213, 770, 228), '<p>D. Khaan mckennai</p>'),
        div('Image', (556, 229, 715, 340)),
        div('Caption', (66, 358, 930, 399), '<p>Figure 2 | The first five caudal vertebrae.</p>'),
        div('Text', (66, 414, 492, 579), '<p>However, if it is true...</p>'),
    )
    result = figures.assemble_page(2, cut_up)

    assert len(result.figures) == 1
    figure = result.figures[0]
    assert figure.assembly == figures.CAPTION_GROUP
    assert len(figure.blocks) == 4
    assert figure.name_hint == 'Figure 2'
    assert figure.caption_hint.startswith('Figure 2 |')
    assert sorted(label[0] for label in figure.label_hints) == ['A', 'B', 'C', 'D']
    assert figure.bbox == (226, 63, 770, 350)       # the printed labels are part of the figure


@pytest.mark.unit
def test_the_small_pieces_of_a_cut_up_figure_are_kept():
    """A grid of zircon images: each piece is below the stand-alone size floor."""
    grid = page(
        *[div('Image', (100 + i * 100, 140, 147 + i * 100, 215)) for i in range(7)],
        div('Caption', (100, 386, 876, 420), '<p>그림 3-1-22. 저어콘의 음극발광영상</p>'),
    )
    figure = figures.assemble_page(0, grid).figures[0]

    assert figure.assembly == figures.CAPTION_GROUP
    assert len(figure.blocks) == 7
    assert figure.name_hint == '그림 3-1-22'


@pytest.mark.unit
def test_stacked_figures_each_with_a_caption_stay_apart():
    stacked = page(
        div('Image', (100, 50, 900, 400)),
        div('Caption', (100, 410, 900, 440), '<p>Fig. 1. Upper.</p>'),
        div('Image', (100, 480, 900, 850)),
        div('Caption', (100, 860, 900, 890), '<p>Fig. 2. Lower.</p>'),
    )
    result = figures.assemble_page(0, stacked)
    assert [(f.assembly, f.name_hint) for f in result.figures] == [
        (figures.SINGLE, 'Fig. 1'), (figures.SINGLE, 'Fig. 2')]


@pytest.mark.unit
def test_body_text_between_a_picture_and_a_caption_breaks_ownership():
    interrupted = page(
        div('Image', (100, 50, 900, 300)),
        div('Text', (100, 320, 900, 480), '<p>Paragraph about something else.</p>'),
        div('Image', (100, 500, 900, 800)),
        div('Caption', (100, 810, 900, 840), '<p>Fig. 7. Only the lower picture.</p>'),
    )
    result = figures.assemble_page(0, interrupted)
    assert [f.assembly for f in result.figures] == [figures.SINGLE, figures.SINGLE]


@pytest.mark.unit
def test_a_picture_with_its_own_caption_above_is_not_taken_by_the_caption_below():
    """Mixed caption placement: Fig. 3 is captioned above, Fig. 4 below."""
    mixed = page(
        div('Caption', (100, 40, 900, 70), '<p>Fig. 3. Captioned above.</p>'),
        div('Image', (100, 80, 900, 400)),
        div('Image', (100, 450, 900, 800)),
        div('Caption', (100, 810, 900, 840), '<p>Fig. 4. Captioned below.</p>'),
    )
    result = figures.assemble_page(0, mixed)
    assert [f.assembly for f in result.figures] == [figures.SINGLE, figures.SINGLE]


@pytest.mark.unit
def test_a_caption_in_the_other_column_does_not_gather_pictures():
    columns = page(
        div('Image', (60, 50, 480, 300)),
        div('Image', (60, 320, 480, 600)),
        div('Caption', (520, 610, 940, 640), '<p>Fig. 8. Right column only.</p>'),
        div('Image', (520, 50, 940, 600)),
    )
    result = figures.assemble_page(0, columns)
    assert all(f.assembly == figures.SINGLE for f in result.figures)
    assert len(result.figures) == 3


# ── compound captions (sizing estimate only) ─────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize('caption,expected', [
    ('Fig. 2. (a) Dorsal view; (b) ventral view.', True),
    ('Figs. 1-3. Cranidia of Redlichia.', True),
    ('Fig. 3A–D. Pygidia.', True),
    ('(A) Holotype. (B) Paratype.', True),
    ('Fig. 4. A. gigas, dorsal view.', False),     # genus abbreviation, not a panel label
    ('Fig. 5. (a) only one panel mentioned.', False),
    ('Fig. 6. U-Pb zircon ages (2019).', False),
    ('', False),
])
def test_compound_caption_estimate(caption, expected):
    assert figures.looks_compound(caption) is expected
