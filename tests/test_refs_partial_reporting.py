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
        {'bad_json': 2, 'refs_lost': 17}) == 'bad JSON x2, 17 refs lost'
    assert biblio.describe_skips(
        {'timeout': 1, 'refs_lost': 1}) == 'timeout x1, 1 refs lost'
    assert biblio.describe_skips(
        {'bad_json': 1, 'no_array': 1, 'timeout': 1, 'refs_lost': 4}
    ) == 'bad JSON x1, no array x1, timeout x1, 4 refs lost'


@pytest.fixture
def one_batch_at_a_time(monkeypatch):
    """Two references, a fresh batcher (starts at 1), and a stubbed server.

    `confidence` is settable because it decides whether an unparseable answer
    means "this failed" or "this document has no bibliography".
    """
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: ['ref one', 'ref two'])
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher())
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)

    def set_confidence(confidence):
        monkeypatch.setattr(biblio, 'extract_references_block',
                            lambda p: ('block', confidence))

    set_confidence('high')
    return set_confidence


@pytest.mark.unit
def test_truncated_array_is_bad_json_not_a_missing_one(one_batch_at_a_time, monkeypatch):
    """A cut-off array is a real failure — the response was lost, so retry."""
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: '[{"title": "A pap')

    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert complete is False
    assert skipped['bad_json'] == 2 and skipped['no_array'] == 0


@pytest.mark.unit
def test_prose_answer_on_a_found_section_stays_partial(one_batch_at_a_time, monkeypatch):
    """We DID find a references heading, so prose back is a failure, not proof
    that the paper has no bibliography."""
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: 'I could not find any')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == []
    assert complete is False           # stays unchecked → retried
    assert skipped['no_array'] == 2    # batcher starts at 1 → one call per reference
    assert skipped['bad_json'] == 0 and skipped['timeout'] == 0
    assert biblio.describe_skips(skipped) == 'no array x2, 2 refs lost'


@pytest.mark.unit
def test_fallback_block_with_no_array_is_checked_empty(one_batch_at_a_time, monkeypatch):
    """The letter / abstract case: no references heading was found, the fallback
    block isn't a bibliography, and the model says so. That is "checked, none" —
    marking it PARTIAL would put the paper at the head of every future batch
    forever, failing identically each time."""
    one_batch_at_a_time('low')
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: 'There are no references')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == []
    assert complete is True            # → caller stamps references_checked
    assert skipped == biblio._no_skips()


@pytest.mark.unit
def test_fallback_block_that_timed_out_is_not_called_empty(one_batch_at_a_time,
                                                           monkeypatch):
    """A fallback block we never got an answer for proves nothing about whether
    the paper has references — that must stay retryable."""
    import requests

    one_batch_at_a_time('low')
    monkeypatch.setattr(biblio, '_call_qwen',
                        lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout()))

    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert complete is False
    assert skipped['timeout'] > 0


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
