"""PARTIAL results must say WHY, not just that they happened.

A references parse comes back partial for exactly two reasons — the server sent
nothing (timeout once the batch is already at the floor), or it sent a 200 whose
body won't parse as JSON. Both used to be reported to the user as the same
opaque `PARTIAL (server?)`, and the line that distinguished them was logged at
INFO on a logger the desktop app never configured, so it went nowhere.

Pins the tally that now comes back with the result.
"""
import pytest

from papermeister import biblio


@pytest.mark.unit
def test_describe_skips_is_empty_when_nothing_skipped():
    """Callers append it unconditionally, so a clean run must render to ''."""
    assert biblio.describe_skips(biblio._no_skips()) == ''


@pytest.mark.unit
def test_describe_skips_names_the_cause_and_the_cost():
    assert biblio.describe_skips(
        {'bad_json': 2, 'timeout': 0, 'refs_lost': 17}) == 'bad JSON x2, 17 refs lost'
    assert biblio.describe_skips(
        {'bad_json': 0, 'timeout': 1, 'refs_lost': 1}) == 'timeout x1, 1 refs lost'
    assert biblio.describe_skips(
        {'bad_json': 1, 'timeout': 1, 'refs_lost': 4}
    ) == 'bad JSON x1, timeout x1, 4 refs lost'


@pytest.fixture
def one_batch_at_a_time(monkeypatch):
    """Two references, a fresh batcher (starts at 1), and a stubbed server."""
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: ('block', 'high'))
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: ['ref one', 'ref two'])
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher())
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)


@pytest.mark.unit
def test_unparseable_response_is_counted_as_bad_json(one_batch_at_a_time, monkeypatch):
    """A 200 carrying prose instead of a JSON array: partial, attributed, counted."""
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: 'I could not find any')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == []
    assert complete is False           # so the paper stays unchecked and is retried
    assert skipped['bad_json'] == 2    # batcher starts at 1 → one call per reference
    assert skipped['timeout'] == 0
    assert skipped['refs_lost'] == 2
    assert biblio.describe_skips(skipped) == 'bad JSON x2, 2 refs lost'


@pytest.mark.unit
def test_clean_run_reports_no_skips(one_batch_at_a_time, monkeypatch):
    monkeypatch.setattr(biblio, '_call_qwen',
                        lambda *a, **k: '[{"title": "A paper"}]')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert len(entries) == 2
    assert complete is True
    assert skipped == biblio._no_skips()


@pytest.mark.unit
def test_missing_references_section_returns_the_same_tuple_shape(monkeypatch):
    """The no-references early return is a valid 'checked' outcome — it must not
    hand callers a short tuple to unpack."""
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: ('', 'low'))

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == [] and complete is True
    assert skipped == biblio._no_skips()
