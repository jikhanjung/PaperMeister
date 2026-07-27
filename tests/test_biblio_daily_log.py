"""The biblio log file must follow the calendar, not the process start.

`_DailyFlushHandler` is built once at import, but a references batch runs for
days without a restart. A filename fixed at construction would file every one of
those days under the day the run began — the exact thing dating the file is
supposed to prevent.
"""
import pytest

from papermeister.biblio import _DailyFlushHandler


def _record(msg):
    import logging
    return logging.LogRecord('biblio', logging.INFO, __file__, 1, msg, None, None)


@pytest.mark.unit
def test_writes_to_a_dated_file(tmp_path, monkeypatch):
    monkeypatch.setattr('papermeister.biblio.time.strftime', lambda f: '20260727')
    handler = _DailyFlushHandler(str(tmp_path), 'biblio')
    try:
        handler.emit(_record('first day'))
    finally:
        handler.close()

    assert (tmp_path / 'biblio_20260727.log').read_text(encoding='utf-8').strip() \
        == 'first day'


@pytest.mark.unit
def test_rolls_over_when_the_day_turns(tmp_path, monkeypatch):
    """A run spanning midnight files each day separately, without a restart."""
    day = {'v': '20260727'}
    monkeypatch.setattr('papermeister.biblio.time.strftime', lambda f: day['v'])

    handler = _DailyFlushHandler(str(tmp_path), 'biblio')
    try:
        handler.emit(_record('before midnight'))
        day['v'] = '20260728'
        handler.emit(_record('after midnight'))
    finally:
        handler.close()

    assert (tmp_path / 'biblio_20260727.log').read_text(encoding='utf-8').strip() \
        == 'before midnight'
    assert (tmp_path / 'biblio_20260728.log').read_text(encoding='utf-8').strip() \
        == 'after midnight'


@pytest.mark.unit
def test_each_record_is_flushed(tmp_path, monkeypatch):
    """The log is read while the batch is still running, so records must land on
    disk immediately rather than sitting in a buffer."""
    monkeypatch.setattr('papermeister.biblio.time.strftime', lambda f: '20260727')
    handler = _DailyFlushHandler(str(tmp_path), 'biblio')
    try:
        handler.emit(_record('visible right away'))
        # No close() yet — this is what tailing the file mid-run sees.
        assert 'visible right away' in \
            (tmp_path / 'biblio_20260727.log').read_text(encoding='utf-8')
    finally:
        handler.close()
