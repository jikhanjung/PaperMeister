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
        {'bad_json': 2, 'entries_lost': 17}) == 'bad JSON x2, 17 entries lost'
    assert biblio.describe_skips(
        {'timeout': 1, 'entries_lost': 1}) == 'timeout x1, 1 entries lost'
    assert biblio.describe_skips(
        {'bad_json': 1, 'no_array': 1, 'timeout': 1, 'entries_lost': 4}
    ) == 'bad JSON x1, no array x1, timeout x1, 4 entries lost'


@pytest.fixture
def one_batch_at_a_time(monkeypatch):
    """Two references, a fresh batcher (starts at 1), and a stubbed server.

    `confidence` is settable because it decides whether an unparseable answer
    means "this failed" or "this document has no bibliography". The block is
    realistically sized, because block length is the other half of that decision
    — a heading match over a few dozen characters is not evidence of a
    bibliography (see test_a_tiny_located_block_may_legitimately_be_empty).
    """
    block = 'Smith, J. 1999. A paper about things. Journal of Things 4: 1-20. ' * 5
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: ['ref one', 'ref two'])
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher())
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)

    def set_confidence(confidence):
        monkeypatch.setattr(biblio, 'extract_references_block',
                            lambda p: (block, confidence))

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
def test_truncation_retries_the_same_batch_at_the_token_ceiling(one_batch_at_a_time,
                                                                monkeypatch):
    """Budget too small is recoverable: the same batch, more room. Skipping
    instead would fail identically forever — batching and budget are both
    deterministic in the input."""
    seen = []

    def fake(prompt, url, max_tokens=0, **k):
        seen.append(max_tokens)
        # Truncated while the budget is an estimate; fine once at the ceiling.
        return '[{"title": "cut off' if max_tokens < biblio._MT_CEILING else '[{"t": 1}]'

    monkeypatch.setattr(biblio, '_call_qwen', fake)

    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert complete is True                      # recovered, nothing lost
    assert skipped == biblio._no_skips()
    assert biblio._MT_CEILING in seen            # escalated rather than skipping
    assert seen[0] < biblio._MT_CEILING          # first attempt used the estimate


@pytest.mark.unit
def test_truncation_at_the_ceiling_splits_the_batch(monkeypatch):
    """Still too big at the ceiling → shrink the batch. Only when that also
    fails (a lone entry that cannot fit) is the batch finally dropped."""
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: ('block', 'high'))
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: ['a', 'b', 'c', 'd'])
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher(size=4))
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)
    sizes = []

    def fake(prompt, url, max_tokens=0, **k):
        sizes.append(prompt.count('\n\n'))   # entries joined by a blank line
        return '[{"title": "cut off'          # never parses, at any size

    monkeypatch.setattr(biblio, '_call_qwen', fake)

    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert complete is False                 # genuinely unrecoverable → PARTIAL
    assert skipped['bad_json'] > 0
    # Terminates (reaching this line proves it) having consumed every entry,
    # and backed the controller off rather than re-sending the same batch.
    assert skipped['entries_lost'] == 4
    assert biblio._refs_batcher.size < 4


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
    assert biblio.describe_skips(skipped) == 'no array x2, 2 entries lost'


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


@pytest.mark.unit
def test_empty_array_for_a_located_section_is_not_accepted(one_batch_at_a_time,
                                                           monkeypatch):
    """A found references section that yields nothing is a contradiction.

    Live regression: prompting the model to emit [] for non-bibliographic text
    gave it an escape hatch it used on a Korean reference list — 47 entries, []
    back for every batch in under a second each — and the paper was stamped
    "no references section", excluding it from every future batch with zero
    references stored. Silent permanent loss; a retry costs almost nothing.
    """
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: '[]')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == []
    assert complete is False              # NOT stamped checked
    assert skipped['empty_result'] == 1
    assert 'model returned nothing' in biblio.describe_skips(skipped)


@pytest.mark.unit
def test_empty_array_on_a_fallback_block_still_means_none(one_batch_at_a_time,
                                                          monkeypatch):
    """The letter case must keep working: no heading was found, so [] really is
    the document saying it has no bibliography."""
    one_batch_at_a_time('low')
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: '[]')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == [] and complete is True
    assert skipped == biblio._no_skips()


@pytest.mark.unit
def test_a_lone_oversized_entry_is_not_retried(monkeypatch):
    """Retrying only pays when the request actually gets smaller.

    Live waste: one blob entry (capped by MAX_CHARS, so the batch is length 1)
    was re-sent byte-for-byte three times because the guard asked the controller
    about its own size rather than the batch. Each attempt burned the full read
    timeout — 9,517 tokens and ~369s, three times, six minutes apart.
    """
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: ('block', 'high'))
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: ['one huge blob'])
    # Controller well above the floor — the old guard would have kept retrying.
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher(size=8))
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)
    calls = []

    def fake(*a, **k):
        import requests
        calls.append(1)
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(biblio, '_call_qwen', fake)

    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert len(calls) == 1            # tried once, then gave up on it
    assert complete is False
    assert skipped['timeout'] == 1


@pytest.mark.unit
def test_shrink_below_forces_a_strictly_smaller_batch():
    """A batch capped by MAX_CHARS can be shorter than the controller's size, so
    backing off from the controller's own number can fail to shrink anything."""
    b = biblio._AdaptiveBatcher(size=8)
    b.shrink_below(2)                 # the batch that failed held 2 entries
    assert b.size < 2


@pytest.mark.unit
def test_read_timeout_default_and_override(one_batch_at_a_time, monkeypatch):
    """The cutoff must be generous enough not to discard work the server
    finished (369.4s answers were being thrown away at 360s), and still be
    overridable per install."""
    seen = []
    monkeypatch.setattr(biblio, '_call_qwen',
                        lambda *a, **k: seen.append(k.get('read_timeout')) or '[]')

    biblio.extract_references_llm('h')
    assert seen[0] == biblio._REFS_READ_TIMEOUT >= 480

    seen.clear()
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: {'ocr_pod_url': 'http://server',
                                           'qwen_read_timeout': 900}.get(k, d))
    biblio.extract_references_llm('h')
    assert seen[0] == 900


@pytest.mark.unit
def test_a_chars_capped_batch_shrinks_on_the_first_retry(monkeypatch):
    """The observed waste, reproduced: a batch capped by MAX_CHARS is shorter
    than the controller's size, so backing off in BACKOFF_STEP increments from
    the controller's own number rebuilds the identical batch until it finally
    drops below the batch length. Live, that walked 20 -> 17 -> 14 -> 11 -> 8 ->
    5 while the batch stayed at 4 entries — five identical 9,517-token calls,
    369s each. The retry must shorten the batch immediately instead.
    """
    monkeypatch.setattr(biblio, 'load_ocr_pages', lambda h: [{'markdown': 'x'}])
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: ('block', 'high'))
    # Five entries; the first four fill MAX_CHARS, so the batch caps at 4 no
    # matter how high the controller sits.
    big = 'x' * (biblio._AdaptiveBatcher.MAX_CHARS // 4)
    monkeypatch.setattr(biblio, 'split_reference_entries',
                        lambda b: [big] * 6)
    monkeypatch.setattr(biblio, '_refs_batcher', biblio._AdaptiveBatcher(size=20))
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: 'http://server' if k == 'ocr_pod_url' else d)

    sent = []

    def fake(prompt, url, max_tokens=0, **k):
        import requests
        n = prompt.count(big)
        sent.append(n)
        if n >= 3:                     # the chars-capped batch always times out
            raise requests.exceptions.Timeout()
        return '[{"title": "ok"}]'

    monkeypatch.setattr(biblio, '_call_qwen', fake)

    biblio.extract_references_llm('h')

    # The controller starts at 20 and the batch caps well below that, so the
    # old code retried the same size once per BACKOFF_STEP on the way down.
    assert max(sent) >= 3                      # it really did hit the cap
    assert sent.count(max(sent)) == 1          # attempted once, not repeatedly
    assert min(sent) < max(sent)               # and the retry was smaller


@pytest.mark.unit
def test_a_tiny_located_block_may_legitimately_be_empty(one_batch_at_a_time,
                                                        monkeypatch):
    """`confidence='high'` means a heading matched, not that the region has
    content. Live case: a course guidebook whose "references section" was 46
    chars of table of contents — 'Professor Biographies .....iCourse Scope.....1'.
    The model's [] was correct; treating it as a contradiction put the paper at
    the head of every batch to be re-asked the same question forever.
    """
    monkeypatch.setattr(biblio, 'extract_references_block',
                        lambda p: ('Professor Biographies .....iCourse Scope.....1', 'high'))
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: [b])
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: '[]')

    entries, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert entries == [] and complete is True     # settles as "none", not a loop
    assert skipped == biblio._no_skips()


@pytest.mark.unit
def test_a_substantial_located_block_must_not_come_back_empty(one_batch_at_a_time,
                                                              monkeypatch):
    """The guard still holds where it was meant to: a real bibliography that
    yields nothing is a contradiction, not a finding."""
    block = 'Smith, J. 1999. A paper about things. Journal of Things 4: 1-20. ' * 5
    monkeypatch.setattr(biblio, 'extract_references_block', lambda p: (block, 'high'))
    monkeypatch.setattr(biblio, 'split_reference_entries', lambda b: [b])
    monkeypatch.setattr(biblio, '_call_qwen', lambda *a, **k: '[]')

    assert len(block) >= biblio._SUBSTANTIAL_BLOCK_CHARS
    _, _, _, complete, skipped = biblio.extract_references_llm('h')

    assert complete is False
    assert skipped['empty_result'] == 1
