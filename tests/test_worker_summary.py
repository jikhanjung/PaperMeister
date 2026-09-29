"""The server's worker block, one worker or several (2026-09-30: ocrserver
is going to two workers; the client read `worker` as one dict)."""
import pytest

from papermeister.figure_client import worker_summary


@pytest.mark.unit
def test_one_worker_as_wrapper_0_3_reports_it():
    w = worker_summary({'worker': {'state': 'sleeping', 'paused_reason': None}})
    assert w == {'state': 'sleeping', 'paused_reason': None, 'count': 1}
    assert worker_summary({'worker': {'state': 'paused', 'paused_reason': 'usage limit'}})['paused_reason'] == 'usage limit'


@pytest.mark.unit
def test_several_workers_are_paused_only_when_all_are():
    both = {'workers': [{'state': 'processing', 'paused_reason': None},
                        {'state': 'sleeping', 'paused_reason': None}]}
    w = worker_summary(both)
    assert w['paused_reason'] is None and w['count'] == 2 and w['state'].startswith('processing (1/2 busy)')
    one_paused = {'worker': [{'state': 'paused', 'paused_reason': 'login'},
                             {'state': 'processing', 'paused_reason': None}]}
    assert worker_summary(one_paused)['paused_reason'] is None           # the queue still moves
    all_paused = {'workers': [{'state': 'paused', 'paused_reason': 'usage limit'},
                              {'state': 'paused', 'paused_reason': 'usage limit'}]}
    assert worker_summary(all_paused)['paused_reason'] == 'usage limit'


@pytest.mark.unit
def test_no_worker_block_is_not_an_error():
    assert worker_summary({}) == {'state': '?', 'paused_reason': None, 'count': 0}
    assert worker_summary({'worker': None})['count'] == 0
