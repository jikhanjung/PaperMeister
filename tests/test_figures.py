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
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
        div('Text', (100, 450, 900, 490), '<p>The holotype is figured on Plate 7.</p>'),
    )
    assert figures.assemble_page(0, cited).verdict == figures.NO_MARK


@pytest.mark.unit
def test_a_running_line_the_ocr_called_body_text_still_marks_the_plate():
    """fsis ref 2407: the plate's running line came back labelled `Text`."""
    running = page(
        div('Text', (100, 20, 800, 40), '<p>D.K. Choi, P.Y. Bong, and B.K. Kim, Plate I, Jour. Geol. Soc. Korea</p>'),
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
    )
    result = figures.assemble_page(4, running)
    assert (result.verdict, result.figures[0].plate) == (figures.PLATE, 1)


@pytest.mark.unit
def test_a_citation_at_the_page_edge_is_not_a_running_line():
    citing = page(
        div('Text', (100, 20, 800, 40), '<p>see Pl. 8, Fig. 1 for the holotype</p>'),
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
    )
    assert figures.assemble_page(0, citing).verdict == figures.NO_MARK


@pytest.mark.unit
def test_an_abbreviation_starting_with_pl_is_not_a_plate():
    """fsis ref 2648: "PLM" read as Plate M."""
    microscopy = page(
        div('Page-Header', (100, 20, 700, 40), '<p>Polarized Light Microscopy (PLM) and PLC data</p>'),
        div('Image', (100, 100, 450, 400)),
        div('Image', (500, 100, 900, 400)),
    )
    assert figures.assemble_page(0, microscopy).verdict == figures.NO_MARK


@pytest.mark.unit
def test_a_one_photograph_plate_page_is_named_for_its_plate():
    one = page(
        div('Page-Header', (300, 20, 700, 40), '<p>PLATE 2</p>'),
        div('Image', (100, 100, 900, 850)),
    )
    (figure,) = figures.assemble_page(5, one).figures
    assert (figure.assembly, figure.plate, figure.name_hint, figure.page_kind) == (
        figures.SINGLE, 2, 'Plate 2', figures.PLATE_KIND)


@pytest.mark.unit
def test_a_photograph_whose_caption_cites_a_plate_is_not_a_plate():
    """Šnajdr 1981 p.5: a small pygidium on a text page, its caption citing `Pl. II, fig. 2`."""
    cited = page(
        div('Text', (100, 100, 900, 500), '<p>' + 'Description of the pathological pygidium. ' * 20 + '</p>'),
        div('Image', (300, 550, 600, 800)),
        div('Caption', (300, 810, 600, 840), '<p>2. Part of right lateral lobe of pygidium (Pl. II, fig. 2).</p>'),
    )
    result = figures.assemble_page(4, cited)
    assert result.verdict == figures.FEW_PICTURES
    assert result.figures[0].page_kind == figures.BODY


@pytest.mark.unit
def test_an_ornament_is_not_a_one_photograph_plate():
    ornament = page(
        div('Page-Header', (300, 20, 700, 40), '<p>PLATE 2</p>'),
        div('Image', (450, 500, 480, 530)),
    )
    assert figures.assemble_page(0, ornament).figures == []


@pytest.mark.unit
def test_photographs_with_their_own_captions_under_a_plate_header_are_named_within_the_plate():
    """fsis ref 2360: each photo captioned `Fig. N` under `PLATE 2`. Without the plate
    number every plate repeats `Fig. 1`; a caption citing another plate does not count."""
    captioned = page(
        div('Page-Header', (300, 20, 700, 40), '<p>PLATE 2</p>'),
        div('Image', (100, 60, 900, 420)),
        div('Caption', (100, 430, 900, 460), '<p>Fig. 1. Ball and pillow, arrow B in Figure 1 of Plate 1.</p>'),
        div('Image', (100, 500, 900, 860)),
        div('Caption', (100, 870, 900, 900), '<p>Fig. 2. Mudcracks.</p>'),
    )
    result = figures.assemble_page(11, captioned)
    assert [(f.name_hint, f.plate, f.page_kind) for f in result.figures] == [
        ('Plate 2, Fig. 1', 2, figures.CAPTIONED_PLATE), ('Plate 2, Fig. 2', 2, figures.CAPTIONED_PLATE)]
    assert result.figures[1].caption_hint == 'Fig. 2. Mudcracks.'


@pytest.mark.unit
def test_captioned_figures_without_a_plate_header_keep_their_own_names():
    body = page(
        div('Image', (100, 60, 900, 420)),
        div('Caption', (100, 430, 900, 460), '<p>Fig. 1. Upper.</p>'),
        div('Image', (100, 500, 900, 860)),
        div('Caption', (100, 870, 900, 900), '<p>Fig. 2. Lower.</p>'),
    )
    assert [(f.name_hint, f.page_kind) for f in figures.assemble_page(0, body).figures] == [
        ('Fig. 1', figures.BODY), ('Fig. 2', figures.BODY)]


# ── plate numbers that are not printed on the page ───────────────────

TWO_PHOTOS = (div('Image', (100, 60, 480, 480)), div('Image', (520, 60, 900, 480)))


@pytest.mark.unit
def test_the_explanation_at_the_foot_of_the_previous_page_numbers_the_plate():
    """fsis ref 3359: photographs and photo numbers only; "Explanation of Plate 3" ends the page before."""
    explanation = page(
        div('Text', (100, 100, 900, 600), '<p>Systematic descriptions continue here.</p>'),
        div('Section-Header', (100, 650, 600, 670), '<h3>Explanation of Plate 3</h3>'),
        div('Text', (100, 680, 900, 900), '<p>Figs. 1-2. Redlichia nobilis.</p>'),
    )
    photos = page(*TWO_PHOTOS, div('Text', (100, 500, 140, 515), '<p>1</p>'),
                  div('Text', (520, 500, 560, 515), '<p>2</p>'))

    plate = figures.assemble_document([explanation, photos])[1].figures[0]
    assert (plate.assembly, plate.plate, plate.name_hint, plate.plate_inferred) == (
        figures.PLATE_UNION, 3, 'Plate 3', True)


@pytest.mark.unit
def test_no_number_is_inferred_for_a_page_with_real_text():
    explanation = page(div('Section-Header', (100, 650, 600, 670), '<h3>Explanation of Plate 3</h3>'))
    text_page = page(*TWO_PHOTOS, div('Text', (100, 500, 900, 900), '<p>' + 'Body text. ' * 20 + '</p>'))
    assert figures.assemble_document([explanation, text_page])[1].verdict == figures.NO_MARK


@pytest.mark.unit
def test_the_page_before_plate_two_is_plate_one_when_nothing_else_claims_it():
    """fsis ref 2100: the first plate has no header; the next page starts at PLATE II."""
    first = page(*TWO_PHOTOS)
    second = page(div('Page-Header', (300, 20, 700, 40), '<p>PLATE II</p>'), *TWO_PHOTOS)

    plate = figures.assemble_document([first, second])[0].figures[0]
    assert (plate.plate, plate.name_hint, plate.plate_inferred) == (1, 'Plate I', True)


@pytest.mark.unit
def test_no_plate_one_is_inferred_when_a_page_with_pictures_already_prints_it():
    """fsis ref 3075 p.102: Pl. XVII printed on a page judged a body figure page still owns the number."""
    printed = page(
        div('Page-Header', (300, 20, 700, 40), '<p>PLATE 1</p>'),
        div('Image', (100, 60, 900, 420)), div('Caption', (100, 430, 900, 460), '<p>Fig. 1. A.</p>'),
        div('Image', (100, 500, 900, 860)), div('Caption', (100, 870, 900, 900), '<p>Fig. 2. B.</p>'),
    )
    unmarked = page(*TWO_PHOTOS)
    second = page(div('Page-Header', (300, 20, 700, 40), '<p>PLATE 2</p>'), *TWO_PHOTOS)
    assert figures.assemble_document([printed, unmarked, second])[1].verdict == figures.NO_MARK


@pytest.mark.unit
def test_a_bare_plate_header_names_the_only_plate_of_a_paper():
    """fsis ref 2097: a one-plate paper prints `PLATE` and `Explanation of Plate` without numbers."""
    intro = page(div('Text', (100, 100, 900, 800), '<p>Introduction.</p>'))
    bare = page(div('Page-Header', (400, 20, 600, 40), '<p>PLATE</p>'), *TWO_PHOTOS)

    plate = figures.assemble_document([intro, bare])[1].figures[0]
    assert (plate.name_hint, plate.plate_inferred) == ('Plate', True)


@pytest.mark.unit
def test_two_bare_plate_headers_name_neither():
    bare = page(div('Page-Header', (400, 20, 600, 40), '<p>PLATE</p>'), *TWO_PHOTOS)
    result = figures.assemble_document([bare, bare])
    assert [r.verdict for r in result] == [figures.NO_MARK, figures.NO_MARK]


@pytest.mark.unit
def test_a_one_photograph_page_does_not_take_a_number_another_plate_has():
    """fsis ref 3011: `Pl. XLI` misread as `Pl. XII`, the number of a plate many pages earlier."""
    plate = page(div('Page-Header', (300, 20, 700, 40), '<p>Pl. XII</p>'), *TWO_PHOTOS)
    between = page(div('Text', (100, 100, 900, 900), '<p>Systematic descriptions.</p>'))
    misread = page(div('Page-Header', (300, 20, 700, 40), '<p>Pl. XII</p>'), div('Image', (100, 100, 300, 250)))

    result = figures.assemble_document([plate, between, misread])
    assert result[0].figures[0].plate == 12
    assert result[2].verdict == figures.DUP_NUMBER
    assert (result[2].figures[0].plate, result[2].figures[0].page_kind) == (None, figures.BODY)


@pytest.mark.unit
def test_one_plate_over_facing_pages_keeps_its_number_on_both():
    """Henningsmoen et al.: `Tafel 16: 1` and `Tafel 16: 2`, a drawing on each facing page."""
    left = page(div('Page-Header', (700, 20, 950, 40), '<p>Tafel 16: 1</p>'), div('Image', (60, 150, 920, 830)))
    right = page(div('Page-Header', (700, 20, 950, 40), '<p>Tafel 16: 2</p>'), div('Image', (60, 150, 920, 830)))

    result = figures.assemble_document([left, right])
    assert [(r.verdict, r.figures[0].plate) for r in result] == [(figures.PLATE, 16), (figures.PLATE, 16)]


@pytest.mark.unit
def test_an_explanation_page_beside_its_plate_does_not_share_the_number():
    """이하영 thesis: `Plate 27.` heads the explanation page, the plate is the next page."""
    explanation = page(
        div('Caption', (100, 100, 900, 120), '<p>Plate 27. Conodonts from the Mungog Formation.</p>'),
        div('Image', (100, 60, 150, 90)),
        div('Text', (100, 130, 900, 900), '<p>' + '1. Drepanodus concavus, lateral view. ' * 10 + '</p>'),
    )
    plate = page(div('Page-Header', (300, 20, 700, 40), '<p>Plate 27</p>'), div('Image', (60, 100, 940, 900)))

    result = figures.assemble_document([explanation, plate])
    assert [r.verdict for r in result] == [figures.DUP_NUMBER, figures.PLATE]


@pytest.mark.unit
def test_a_one_photograph_plate_much_larger_than_its_twin_keeps_the_number():
    """fsis ref 4051: the explanation page's thumbnail and the plate share a header."""
    thumbnail = page(div('Page-Header', (300, 20, 700, 40), '<p>PLATE 4</p>'), div('Image', (100, 100, 300, 250)),
                     div('Text', (100, 300, 900, 900), '<p>' + 'Figs. 1-3. Explanation of the specimens. ' * 6 + '</p>'))
    plate = page(div('Page-Header', (300, 20, 700, 40), '<p>PLATE 4</p>'), div('Image', (100, 60, 900, 900)))

    result = figures.assemble_document([thumbnail, plate])
    assert [r.verdict for r in result] == [figures.DUP_NUMBER, figures.PLATE]


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
    """A grid of zircon images with an age under each: every piece is below the
    stand-alone size floor, and the ages are labels, not captions."""
    grid = page(
        *[div('Image', (100 + i * 100, 140, 147 + i * 100, 215)) for i in range(7)],
        *[div('Caption', (95 + i * 100, 226, 160 + i * 100, 255), f'<p>{i + 1}.1 24{i} Ma</p>') for i in range(7)],
        *[div('Image', (100 + i * 100, 274, 147 + i * 100, 349)) for i in range(7)],
        *[div('Caption', (95 + i * 100, 350, 160 + i * 100, 380), f'<p>{i + 8}.1 25{i} Ma</p>') for i in range(7)],
        div('Caption', (100, 386, 876, 420), '<p>그림 3-1-22. 저어콘의 음극발광영상</p>'),
    )
    (figure,) = figures.assemble_page(0, grid).figures

    assert figure.assembly == figures.CAPTION_GROUP
    assert len(figure.blocks) == 14
    assert len(figure.label_hints) == 14
    assert figure.name_hint == '그림 3-1-22'


@pytest.mark.unit
def test_a_photo_caption_owns_its_pieces_too():
    """fsis ref 2162: two photographs over one `Photo 1.`"""
    photos = page(
        div('Image', (100, 60, 900, 400)),
        div('Image', (100, 430, 900, 780)),
        div('Caption', (100, 790, 900, 820), '<p>Photo 1. Outcrop of the Sesong Formation.</p>'),
    )
    (figure,) = figures.assemble_page(0, photos).figures
    assert (figure.assembly, figure.name_hint) == (figures.CAPTION_GROUP, 'Photo 1')


@pytest.mark.unit
def test_pieces_too_far_apart_are_two_figures():
    apart = page(
        div('Image', (100, 60, 900, 300)),
        div('Image', (100, 500, 900, 780)),
        div('Caption', (100, 790, 900, 820), '<p>Fig. 3. Only the lower one.</p>'),
    )
    assert [f.assembly for f in figures.assemble_page(0, apart).figures] == [figures.SINGLE, figures.SINGLE]


@pytest.mark.unit
def test_a_piece_two_captions_reach_is_merged_into_neither():
    """fsis ref 2117 p.8 · 3281 p.2: two merges would fold each other's rows."""
    ambiguous = page(
        div('Image', (100, 100, 480, 380)),                                   # reaches both
        div('Image', (100, 400, 480, 590)),
        div('Caption', (100, 600, 480, 620), '<p>Fig. 8. Left.</p>'),
        div('Image', (520, 100, 900, 840)),
        div('Caption', (100, 850, 900, 870), '<p>Fig. 9. Right.</p>'),
    )
    result = figures.assemble_page(0, ambiguous)
    assert [f.assembly for f in result.figures] == [figures.SINGLE] * 3


@pytest.mark.unit
def test_a_caption_that_a_figure_directly_above_owns_is_not_taken_by_its_neighbour():
    """fsis ref 2100 p.10: the right-hand figure took the left column's `Fig. 5`."""
    columns = page(
        div('Image', (60, 100, 480, 400)),
        div('Image', (520, 100, 940, 400)),
        div('Caption', (60, 410, 600, 440), '<p>Fig. 5. Left.</p>'),
        div('Caption', (520, 470, 940, 500), '<p>Fig. 6. Right.</p>'),
    )
    assert [f.name_hint for f in figures.assemble_page(0, columns).figures] == ['Fig. 5', 'Fig. 6']


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


# ── small figures with their own caption (098) ───────────────────────

def _small_page(box, caption='Fig. 10. Protaspis of Paradoxides sp. indet.', cap_box=None):
    x0, y0, x1, y1 = box
    cap_box = cap_box or (x0 - 180, y1 + 8, x1 + 180, y1 + 50)
    return (div('Image', box) + div('Caption', cap_box, caption)
            + div('Text', (100, 600, 900, 900), 'body ' * 200))


@pytest.mark.unit
def test_a_small_picture_with_its_own_numbered_caption_is_a_figure():
    # Westergård 1936 Fig. 10: 37 x 56 permille, under TINY_AREA, a 1 mm protaspis
    page = figures.assemble_page(26, _small_page((711, 396, 748, 452)))
    assert [f.name_hint for f in page.figures] == ['Fig. 10']
    assert page.dropped == {}


@pytest.mark.unit
def test_a_speck_under_a_caption_is_still_dropped():
    # a 22 x 12 scale bar at the foot of a plate, right above the plate's caption
    page = figures.assemble_page(6, _small_page((891, 784, 913, 796), caption='FIGURE 3—1–25. Borealarges'))
    assert page.figures == [] and page.dropped == {'tiny': 1}


@pytest.mark.unit
def test_a_small_picture_without_a_numbered_caption_is_still_dropped():
    page = figures.assemble_page(3, _small_page((711, 396, 748, 452), caption='a short label'))
    assert page.figures == [] and page.dropped == {'tiny': 1}


@pytest.mark.unit
def test_a_numbered_caption_may_overlap_the_picture_a_little():
    # the OCR's caption box starts 7 permille above the picture's bottom edge
    page = figures.assemble_page(26, _small_page((711, 396, 748, 452), cap_box=(527, 445, 927, 493)))
    assert [f.name_hint for f in page.figures] == ['Fig. 10']
    big = figures.assemble_page(1, div('Image', (100, 100, 900, 600))
                        + div('Caption', (100, 590, 900, 640), 'FIG. 594. Morphological features')
                        + div('Text', (100, 700, 900, 900), 'body ' * 100))
    assert big.figures[0].caption_hint.startswith('FIG. 594')


@pytest.mark.unit
def test_the_plate_verdict_stays_strict_about_overlapping_captions():
    """Hughes et al. 1975 p.32: photograph labels overlap the photographs. Read
    leniently, one of them looks like a body-figure caption and the plate page
    becomes 23 unnamed figures."""
    photos = ''.join(div('Image', (x, y, x + 200, y + 110))
                     for y in (70, 200, 330) for x in (48, 294, 548))
    labels = div('Caption', (48, 168, 248, 195), 'Fig. 1')   # overlaps the first photo by 12
    page = figures.assemble_page(32, div('Page-Header', (300, 20, 700, 45), 'Plate 4') + photos + labels)
    assert len(page.figures) == 1 and page.figures[0].assembly == figures.PLATE_UNION


# ── lettered plate numbers (098) ─────────────────────────────────────

@pytest.mark.unit
def test_lettered_plates_are_different_plates():
    """Barrande 1852: "Pl. 2 A" and "Pl. 2.B." are two plates, not one number
    two pages claim."""
    def plate_page(mark):
        return page(div('Page-Header', (760, 30, 830, 50), mark), div('Image', (160, 100, 820, 900)))
    pages = ['' for _ in range(10)]
    pages[6], pages[8] = plate_page('Pl. 2 A'), plate_page('Pl. 2.B.')
    figs = {a.page: a.figures for a in figures.assemble_document(pages)}
    assert figs[6][0].name_hint == 'Plate 2A' and figs[8][0].name_hint == 'Plate 2B'
    assert figs[6][0].plate == 2 and figs[6][0].page_kind == figures.PLATE_KIND


@pytest.mark.unit
def test_an_authors_initial_after_the_plate_number_is_not_a_suffix():
    assert figures._plate_hits([figures.Region('Page-Header', (100, 20, 900, 45), 'PLATE 17 R. FEIST')],
                               figures.MARK_LABELS) == [(17, '17', 'plate')]
    assert figures._plate_hits([figures.Region('Caption', (100, 20, 900, 45), 'Plate 3. A, dorsal view')],
                               figures.MARK_LABELS) == [(3, '3', 'plate')]
    # a misread "II" with a stray period is plate 2's problem, not plate 1-I
    assert figures.plate_suffix('II') == '' and figures.plate_suffix('2A') == 'A'


# ── what the rule doubts (099: the detect stage's input) ─────────────

def _img(label, bbox):
    return div(label, bbox, '<img alt="x">')


def _photos(n, cols=3, top=70, size=110):
    return page(*(_img('Image', (48 + 250 * (i % cols), top + 130 * (i // cols),
                                 248 + 250 * (i % cols), top + size + 130 * (i // cols))) for i in range(n)))


@pytest.mark.unit
def test_a_figure_the_rule_is_sure_of_carries_no_reason():
    body = page(_img('Image', (100, 100, 900, 600)),
                div('Caption', (100, 610, 900, 650), 'Fig. 3. A trilobite.'),
                div('Text', (100, 700, 900, 900), 'body ' * 100))
    assert figures.assemble_page(1, body).figures[0].reasons == ()
    plate = page(div('Page-Header', (300, 20, 700, 45), 'PLATE 4'), _photos(6))
    assert figures.assemble_page(1, plate).figures[0].reasons == ()


@pytest.mark.unit
def test_many_uncaptioned_photographs_without_a_number_are_one_doubt_about_the_page():
    """Zhou & Zhang 1978 p.28: 26 photographs, no caption, the mark on the
    explanation page before. The rule cannot name it; a model shown the paper can."""
    a = figures.assemble_page(28, _photos(9))
    assert len(a.figures) == 9
    assert all(f.reasons == (figures.UNMARKED_PLATE_PAGE,) for f in a.figures)
    # two photographs are not a plate
    two = figures.assemble_page(3, _photos(2))
    assert all(figures.UNMARKED_PLATE_PAGE not in f.reasons for f in two.figures)


@pytest.mark.unit
def test_a_body_figure_with_no_caption_anywhere_is_doubted():
    lone = page(_img('Image', (100, 100, 900, 600)), div('Text', (100, 700, 900, 900), 'body ' * 100))
    assert figures.assemble_page(1, lone).figures[0].reasons == (figures.NO_CAPTION,)
    # a numbered caption right above it (caption-on-top layouts) is its caption
    above = page(div('Caption', (100, 60, 900, 95), 'Fig. 2. Above.'), _img('Image', (100, 100, 900, 600)),
                 div('Text', (100, 700, 900, 900), 'body ' * 100))
    assert figures.assemble_page(1, above).figures[0].reasons == ()


@pytest.mark.unit
def test_a_plate_nearby_excuses_a_missing_caption():
    pages = ['' for _ in range(4)]
    pages[1] = page(div('Section-Header', (100, 100, 900, 130), 'Explanation of Plate 3'),
                    div('Text', (100, 150, 900, 900), 'text ' * 300))
    pages[2] = page(_img('Image', (100, 100, 900, 800)), div('Text', (100, 850, 900, 900), 'some text ' * 30))
    a = figures.assemble_document(pages)[2]
    assert a.figures and figures.NO_CAPTION not in a.figures[0].reasons


@pytest.mark.unit
def test_a_picture_block_without_an_image_is_text_the_ocr_mislabelled():
    table = page(div('Figure', (100, 100, 900, 600), '<table><tr><td>圖版 12</td></tr></table>'),
                 div('Caption', (100, 610, 900, 650), 'Fig. 1. x'))
    assert figures.TEXT_AS_FIGURE in figures.assemble_page(1, table).figures[0].reasons


@pytest.mark.unit
def test_pages_with_a_number_but_nothing_to_assemble_are_doubted():
    # Barrande 1852 Pl. 50: a header and one 35 x 80 diagram; the OCR did not box the chart
    chart = page(div('Page-Header', (814, 30, 881, 49), 'Pl. 50.'),
                 div('Section-Header', (253, 62, 776, 85), 'Distribution verticale des Trilobites'),
                 _img('Diagram', (540, 525, 575, 605)))
    a = figures.assemble_page(221, chart)
    assert a.figures == [] and a.suspicions == [figures.PLATE_WITHOUT_PICTURES]
    # a figure caption on a page with no picture: the figure is text, or elsewhere
    orphan = page(div('Caption', (100, 800, 900, 850), 'Fig. 7. Continued from the page before.'),
                  div('Text', (100, 100, 900, 700), 'text ' * 200))
    assert figures.assemble_page(5, orphan).suspicions == [figures.CAPTION_WITHOUT_FIGURE]
    # an explanation page is not doubted: lots of text, no picture
    explanation = page(div('Section-Header', (100, 100, 900, 130), 'Erklärung der Tafel IV.'),
                       div('Text', (100, 150, 900, 900), 'text ' * 300))
    assert figures.assemble_page(39, explanation).suspicions == []


@pytest.mark.unit
def test_duplicate_and_double_numbers_are_doubts_not_decisions():
    def plate_page(mark):
        return page(div('Page-Header', (760, 30, 830, 50), mark), _img('Image', (160, 100, 820, 900)))
    pages = ['' for _ in range(10)]
    pages[3], pages[7] = plate_page('Pl. 4'), plate_page('Pl. 4')
    figs = {a.page: a.figures for a in figures.assemble_document(pages)}
    assert figs[3][0].reasons == (figures.DUP_NUMBER_REASON,) and figs[7][0].reasons == (figures.DUP_NUMBER_REASON,)
    spread = page(div('Page-Header', (100, 30, 300, 50), 'ТАБЛИЦА ХХV'), div('Page-Header', (600, 30, 900, 50), 'ТАБЛИЦА ХХVI'),
                  _img('Image', (40, 100, 480, 900)), _img('Image', (520, 100, 960, 900)))
    a = figures.assemble_page(96, spread)
    assert a.verdict == figures.MANY_MARKS and all(f.reasons == (figures.MANY_MARKS_REASON,) for f in a.figures)


@pytest.mark.unit
def test_plate_marks_in_other_scripts_and_spacings():
    hits = figures._plate_hits([figures.Region('Page-Header', (100, 20, 900, 45), t) for t in
                                ('ТАБЛИЦА ХХV', 'Tabl. I', '图 版 IV', 'Plate Ⅻ')], figures.MARK_LABELS)
    assert [(n, tok) for n, tok, _ in hits] == [(25, 'XXV'), (1, 'I'), (4, 'IV'), (12, 'XII')]
