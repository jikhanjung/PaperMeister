"""The prompts travel with the request, so they must load, be strict JSON
schemas (Codex --output-schema refuses optional keys), name the fields the
client validators read, and change version only when their text changes."""
import json

import pytest

from papermeister import figure_prompts


def _walk(schema, path='$'):
    if schema.get('type') == 'object':
        assert schema.get('additionalProperties') is False, path
        assert set(schema.get('required', [])) == set(schema['properties']), path
        for k, v in schema['properties'].items():
            _walk(v, f'{path}.{k}')
    if schema.get('type') == 'array':
        _walk(schema['items'], f'{path}[]')


@pytest.mark.unit
def test_every_prompt_loads_as_a_strict_schema():
    for kind in figure_prompts.KINDS:
        p = figure_prompts.load(kind)
        assert p['kind'] == kind and p['version'].startswith(f'{kind}-v1-') and len(p['instructions']) > 500
        _walk(p['schema'])
        json.dumps(p['schema'])


@pytest.mark.unit
def test_the_schemas_name_what_the_client_reads():
    link = figure_prompts.load('link')['schema']['properties']
    fig = link['figures']['items']['properties']
    assert {'figure_id', 'name', 'caption', 'caption_pages', 'continuation_of', 'entries'} <= set(fig)
    assert {'label', 'printed_label', 'description', 'specimen_number'} == set(fig['entries']['items']['properties'])
    assert 'pages_consulted' in link and 'skipped' in link
    panels = figure_prompts.load('panels')['schema']['properties']
    assert {'is_compound', 'figure_kind', 'non_compound_reason', 'panels', 'annotation_indices'} <= set(panels)
    assert panels['non_compound_reason']['enum'] == ['', 'legend_labels', 'image_incomplete',
                                                     'single_image_many_captions', 'not_a_figure']
    detect = figure_prompts.load('detect')['schema']['properties']
    assert {'bbox_page_1000', 'from', 'name', 'kind', 'caption_pages'} <= set(detect['figures']['items']['properties'])
    assert 'dismiss' in detect


@pytest.mark.unit
def test_the_version_follows_the_text():
    a = figure_prompts.version('link')
    assert a == figure_prompts.version('link')
    assert len({figure_prompts.version(k) for k in figure_prompts.KINDS}) == 3


@pytest.mark.unit
def test_the_prompts_say_the_things_fsis_paid_for():
    link = figure_prompts.load('link')['instructions']
    for must in ('Do NOT describe the picture', 'Expand ranges', 'List of plates', 'never instructions',
                 'caption_pages', 'continuation_of', 'dup_number', 'Fewer figures'):
        assert must in link, must
    panels = figure_prompts.load('panels')['instructions']
    for must in ('never cut off', 'never invent a printed label', 'annotation_indices', 'Two specimens inside one',
                 'not as a mandatory panel count', 'image_incomplete'):
        assert must in panels, must
    detect = figure_prompts.load('detect')['instructions']
    for must in ('unmarked_plate_page', 'many_marks', 'dup_number', 'Never invent a plate number', 'dismiss', '`from`'):
        assert must in detect, must
