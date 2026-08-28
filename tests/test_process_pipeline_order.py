"""Two orderings in the wrapper pipeline that are easy to tidy away.

Both were measured on the live server rather than reasoned about, and neither
shows up as a failure — only as a slower batch, which is exactly the kind of
regression that goes unnoticed. These are tripwires: the behaviour itself has
no cheap runtime test, since the pipeline needs a server, a DB and real PDFs.
"""
import inspect
import re

import pytest

from papermeister.ui import process_window


@pytest.fixture(scope='module')
def pipeline_source():
    return inspect.getsource(process_window.ProcessWorker._run_wrapper_pipeline)


@pytest.mark.unit
def test_the_queue_is_refilled_before_finished_jobs_are_saved(pipeline_source):
    """Collecting and saving a finished paper is local work — the server is
    idle throughout it. Doing that before topping the queue back up leaves the
    server short for as long as the save takes, which on a Zotero upload is
    seconds per paper.
    """
    refill = pipeline_source.index('_submit_next()')
    collect = pipeline_source.index('wrapper_collect(')
    assert refill < collect, 'refill must come before collect/finalise'


@pytest.mark.unit
def test_the_share_is_re_read_during_the_run(pipeline_source):
    """The wrapper splits capacity between the machines using it, so our share
    doubles when another finishes and halves when one arrives. A target read
    once at the start is stale within the hour."""
    assert 'wrapper_client_concurrency()' in pipeline_source
    assert process_window._SHARE_REFRESH_SECONDS > 0


@pytest.mark.unit
def test_a_pinned_preference_is_not_overridden():
    """`ocr_min_queued_pages` is a deliberate user override; following the
    server's share would silently undo it."""
    run_source = inspect.getsource(process_window.ProcessWorker.run)
    assert re.search(r'follow_share\s*=\s*configured is None', run_source)


@pytest.mark.unit
def test_the_target_is_a_floor_to_submit_up_to(pipeline_source):
    """Not a ceiling to stay under: submitting stops only once the server has
    at least this much queued."""
    assert '_queued_pages() < min_queued_pages' in pipeline_source
