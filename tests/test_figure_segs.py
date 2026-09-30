"""The compact link answer ("caption segments") back into captions and entries.
The examples are the format description's own (ocrserver P03 v3)."""
import pytest

from papermeister import figure_segs

PLATE = '\n'.join([
    'x :: Explanation of Plate 3',
    'h1 :: Oistodus aff. breviconus Branson & Mehl, lateral views, x40.',
    'e 1,2 | L=Figs. 1-2. | s=YSUG 00287; YSUG 00288 :: Hunghuayuan Formation.',
    'h1 :: Drepanodus arcuatus Pander.',
    'e 3 | L=Fig. 3. :: Posterior view, YSUG 00290.',
    'e 4 | L=Fig. 4. | d=Drepanodus arcuatus Pander. Posterior view, YSUG 00291. :: Same, YSUG 00291.',
    't 3,4 :: Scale bar 100 μm.',
    't :: All specimens from bed 12.',
])


def figure(segs, **extra):
    return {'figure_id': '7', 'name': 'Plate 3', 'caption_source': 'explanation_page', 'caption_pages': [4],
            'continuation_of': None, 'segs': segs, **extra}


@pytest.mark.unit
def test_the_caption_is_the_pieces_in_order_with_their_printed_labels():
    full, warnings = figure_segs.expand_figure(figure(PLATE))
    assert warnings == []
    lines = full['caption'].split('\n')
    assert lines[0] == 'Explanation of Plate 3'
    assert lines[2] == 'Figs. 1-2. Hunghuayuan Formation.'
    assert lines[4] == 'Fig. 3. Posterior view, YSUG 00290.'
    assert list(full) == list(figure_segs.FIGURE_FIELDS) and 'segs' not in full


@pytest.mark.unit
def test_entries_are_headings_plus_their_own_text_plus_remarks():
    full, _ = figure_segs.expand_figure(figure(PLATE))
    by = {e['label']: e for e in full['entries']}
    assert list(by) == ['1', '2', '3', '4']
    assert by['1']['description'] == ('Oistodus aff. breviconus Branson & Mehl, lateral views, x40. '
                                      'Hunghuayuan Formation.')
    # a range shares its piece; each label keeps its own specimen, the printed range is not theirs
    assert (by['1']['specimen_number'], by['2']['specimen_number']) == ('YSUG 00287', 'YSUG 00288')
    assert by['1']['printed_label'] == '1' and by['3']['printed_label'] == 'Fig. 3.'
    # labelled and bare remarks attach; the label never enters a description
    assert by['3']['description'] == ('Drepanodus arcuatus Pander. Posterior view, YSUG 00290. '
                                      'Scale bar 100 μm. All specimens from bed 12.')
    # a ditto resolved by `d` is taken whole, remarks and all left out
    assert by['4']['description'] == 'Drepanodus arcuatus Pander. Posterior view, YSUG 00291.'


@pytest.mark.unit
def test_a_heading_runs_on_into_its_entries_and_takes_a_group_label():
    segs = '\n'.join([
        'h1 | L=Fig. 5. :: Pojetaia runnegari Jell, 1980 from the Shackleton Limestone.',
        'h2 | L=(1–4) :: Specimen SMNH Mo185039 in',
        'e 1 | L=(1) :: lateral view,',
        'e 2 | L=(2) :: dorsal view.',
        't 1,2 :: Scale bars = 200 μm.',
    ])
    full, _ = figure_segs.expand_figure(figure(segs))
    assert full['caption'].startswith('Fig. 5. Pojetaia') and '(1–4) Specimen' in full['caption']
    assert full['entries'][0]['description'] == ('Pojetaia runnegari Jell, 1980 from the Shackleton Limestone. '
                                                 'Specimen SMNH Mo185039 in lateral view. Scale bars = 200 μm.')


@pytest.mark.unit
def test_a_figure_without_printed_labels_has_no_entries():
    full, warnings = figure_segs.expand_figure(figure('x :: Fig. 14. Palaeogeography in the Early Devonian.'))
    assert full['entries'] == [] and full['caption'] == 'Fig. 14. Palaeogeography in the Early Devonian.'
    assert warnings == []


@pytest.mark.unit
def test_what_does_not_parse_stays_in_the_caption_and_is_reported():
    full, warnings = figure_segs.expand_figure(figure('x :: Plate 1\nthis line has no kind\ne 1 :: a\nt 9 :: b'))
    assert 'this line has no kind' in full['caption']
    assert any(w.startswith('unparsed') for w in warnings) and any('not found' in w for w in warnings)


@pytest.mark.unit
def test_a_reply_in_the_full_shape_passes_through():
    reply = {'figures': [{'figure_id': '1', 'caption': 'c', 'entries': []}, figure('x :: y')], 'skipped': []}
    out, warnings = figure_segs.expand(reply)
    assert out['figures'][0] == reply['figures'][0] and out['figures'][1]['caption'] == 'y'
    assert figure_segs.is_compact(reply) and not figure_segs.is_compact(out) and warnings == {}


@pytest.mark.unit
def test_the_segment_prompt_keeps_the_rules_and_swaps_the_answer_fields():
    from papermeister import figure_prompts
    full, segs = figure_prompts.load('link', 'full'), figure_prompts.load('link', 'segs')
    assert full['version'] != segs['version']
    assert segs['instructions'].startswith(full['instructions'].rstrip().removesuffix(
        'Return only JSON conforming to the schema.').rstrip())
    assert segs['instructions'].rstrip().endswith('Return only JSON conforming to the schema.')
    fig = segs['schema']['properties']['figures']['items']
    assert 'segs' in fig['required'] and 'caption' not in fig['properties'] and 'entries' not in fig['properties']
    assert 'caption' in full['schema']['properties']['figures']['items']['properties']
