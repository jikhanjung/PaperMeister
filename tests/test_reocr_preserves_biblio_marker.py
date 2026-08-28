"""A re-OCR must not undo the paper's bibliography.

`papermeister_meta` in the OCR JSON is how the app knows a paper's biblio has
already been applied — `extract_biblio_llm` refuses to run again when it sees
one. It is written *after* OCR, by the apply step, so a fresh OCR result never
carries it. Overwriting the cache with that fresh result would therefore strip
the marker off every paper re-OCR'd, sending settled papers back through LLM
extraction and into needs_review. Re-OCR of the April batch is 2,049 papers, so
this is not a corner case.
"""
import json

import pytest

from papermeister import text_extract


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(text_extract, 'OCR_JSON_DIR', str(tmp_path))
    monkeypatch.setattr(text_extract, 'ocr_json_filename', lambda pf: 'paper.pdf.abcd1234.json')
    return tmp_path / 'paper.pdf.abcd1234.json'


APPLIED = {
    'schema_version': 1,
    'biblio_state': 'applied',
    'biblio_source': 'llm-qwen',
    'biblio_applied_at': '2026-06-10T08:29:59.561630+00:00',
}


@pytest.mark.unit
def test_the_applied_marker_survives_a_re_ocr(cache):
    cache.write_text(json.dumps({
        'pages': [{'page': 0, 'markdown': 'flat old text'}],
        'papermeister_meta': APPLIED,
    }), encoding='utf-8')

    text_extract._save_ocr_json(object(), {'pages': [{'page': 0, 'markdown': '<div>new</div>'}]})

    written = json.loads(cache.read_text(encoding='utf-8'))
    assert written['papermeister_meta'] == APPLIED     # the biblio is still applied
    assert '<div>' in written['pages'][0]['markdown']  # and the OCR is the new one


@pytest.mark.unit
def test_a_fresh_marker_wins_over_the_old_one(cache):
    cache.write_text(json.dumps({'pages': [], 'papermeister_meta': APPLIED}), encoding='utf-8')
    incoming = {'pages': [], 'papermeister_meta': {'biblio_state': 'needs_review'}}

    text_extract._save_ocr_json(object(), incoming)

    written = json.loads(cache.read_text(encoding='utf-8'))
    assert written['papermeister_meta'] == {'biblio_state': 'needs_review'}


@pytest.mark.unit
def test_nothing_is_invented_when_there_was_no_marker(cache):
    cache.write_text(json.dumps({'pages': []}), encoding='utf-8')

    text_extract._save_ocr_json(object(), {'pages': [{'page': 0, 'markdown': 'x'}]})

    assert 'papermeister_meta' not in json.loads(cache.read_text(encoding='utf-8'))


@pytest.mark.unit
def test_a_first_ocr_writes_normally(cache):
    text_extract._save_ocr_json(object(), {'pages': [{'page': 0, 'markdown': 'x'}]})
    assert cache.exists()


@pytest.mark.unit
def test_an_unreadable_old_cache_does_not_block_the_new_one(cache):
    cache.write_text('{ this is not json', encoding='utf-8')

    text_extract._save_ocr_json(object(), {'pages': [{'page': 0, 'markdown': 'x'}]})

    assert json.loads(cache.read_text(encoding='utf-8'))['pages'][0]['markdown'] == 'x'
