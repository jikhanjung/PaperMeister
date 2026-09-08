"""Refusing an OCR result that would replace a paper with a fragment of it.

Nine papers were reduced to between 2% and 8% of themselves in one run: the
wrapper returned `done_with_errors` after a handful of pages, and the only
guard was "did any text come back at all" — which a fragment passes. The
fragment then overwrote the cache, the passages in the DB and the copy in
Zotero, and, being valid structured output, stopped looking like anything that
needed doing again.
"""
import pytest

from papermeister import text_extract


class _File:
    hash = 'a' * 64
    path = 'paper.pdf'


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(text_extract, 'OCR_JSON_DIR', str(tmp_path))
    monkeypatch.setattr(text_extract, 'ocr_json_filename', lambda pf: 'paper.pdf.aaaaaaaa.json')
    return tmp_path / 'paper.pdf.aaaaaaaa.json'


def _result(done, total):
    return {'total_pages': total, 'done_pages': done,
            'pages': [{'page': i, 'markdown': f'page {i}'} for i in range(done)]}


@pytest.mark.unit
def test_a_fragment_of_a_book_is_refused(cache):
    with pytest.raises(text_extract.IncompleteOCR, match='18 of 694'):
        text_extract._reject_incomplete_ocr(_File(), _result(18, 694))


@pytest.mark.unit
def test_a_complete_result_passes(cache):
    text_extract._reject_incomplete_ocr(_File(), _result(694, 694))


@pytest.mark.unit
def test_a_mostly_complete_result_passes(cache):
    """Some pages genuinely fail — a torn scan, an unreadable plate. That is a
    partial success and the text is worth having."""
    text_extract._reject_incomplete_ocr(_File(), _result(198, 210))


@pytest.mark.unit
def test_a_result_the_server_cannot_size_is_not_second_guessed(cache):
    """No total_pages means no coverage to judge; the empty-result check
    downstream still catches the worthless case."""
    text_extract._reject_incomplete_ocr(_File(), {'pages': [{'page': 0, 'markdown': 'x'}]})


@pytest.mark.unit
def test_it_will_not_replace_a_fuller_cache_with_an_emptier_one(cache):
    """Even a result the server is happy with: the earlier run is the better
    one whenever it covered more of the paper."""
    import json
    cache.write_text(json.dumps(_result(210, 210)), encoding='utf-8')

    with pytest.raises(text_extract.IncompleteOCR, match='refusing to replace it with less'):
        text_extract._reject_incomplete_ocr(_File(), _result(200, 200))


@pytest.mark.unit
def test_a_fuller_result_replaces_a_thinner_cache(cache):
    """Which is the whole point of re-running the ones that came back short."""
    import json
    cache.write_text(json.dumps(_result(18, 694)), encoding='utf-8')

    text_extract._reject_incomplete_ocr(_File(), _result(694, 694))


@pytest.mark.unit
def test_the_check_runs_before_anything_is_written():
    """It has to: the cache, the passages and the Zotero copy are all replaced
    downstream, and by then the good version is gone."""
    import inspect
    source = inspect.getsource(text_extract.process_paper_file)
    assert source.index('_reject_incomplete_ocr') < source.index('_save_ocr_json')
    assert source.index('_reject_incomplete_ocr') < source.index('Passage.delete()')
