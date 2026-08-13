"""A 502 mid-paper has to be visible in the References window.

The model container restarting takes minutes, during which the extraction
worker deliberately waits (devlog 083) so the batches already parsed for the
paper aren't thrown away. Nothing about that wait reaches the window on its
own: the paper hasn't finished, so `record()` doesn't fire, and the batch isn't
paused, so `mark_paused()` doesn't either — the window just sits on
"Parsing: <title>" and looks hung.
"""
import pytest


@pytest.fixture
def win(qapp):
    from desktop.windows.references_window import ReferencesWindow

    w = ReferencesWindow()
    w.begin(3)
    w.set_current('Parsing: Smith 1998')
    return w


@pytest.mark.ui
def test_server_wait_is_shown_and_the_label_is_restored(win):
    win.mark_server_wait('HTTP 502 from the LLM server — the model container '
                         'is restarting; waiting up to 900s')

    assert 'waiting' in win.current_label.text().lower()
    assert '502' in win.log.toPlainText()

    win.mark_server_back('LLM server came back after 120s — resuming the same batch')

    # Back to the paper we were on: the wait was inside it, so the label must
    # not stay on a stale outage banner for the rest of the paper.
    assert win.current_label.text() == 'Parsing: Smith 1998'
    assert 'came back' in win.log.toPlainText()


@pytest.mark.ui
def test_server_wait_does_not_advance_the_batch(win):
    """The paper is still in flight — counting it here would put the progress
    bar ahead of reality and double-count when it actually finishes."""
    win.mark_server_wait('HTTP 502 …')
    win.mark_server_back('gave up', recovered=False)

    assert win.progress_bar.value() == 0
    assert win.progress_count.text() == '0 / 3'


# ── Per-paper progress rows ──────────────────────────────────────
#
# The batch parses several papers at once, so a single shared bar would jump
# between unrelated papers' entry counts. Each in-flight paper gets a row.


@pytest.mark.ui
def test_each_in_flight_paper_gets_its_own_row(win):
    win.start_item(1, 'Smith 1998')
    win.start_item(2, 'Jones 2001')
    win.start_item(3, 'Brown 2010')

    assert len(win._item_rows) == 3
    assert win.items_box.isVisible()

    win.set_item_progress(2, 15, 60)
    _row, bar, count = win._item_rows[2]
    assert (bar.value(), bar.maximum()) == (15, 60)
    assert '15 / 60 refs' in count.text()
    # The others are untouched — that is the whole point of separate rows.
    # Still busy (Qt reports a 0..0 range as value -1), not showing 2's count.
    assert (win._item_rows[1][1].minimum(), win._item_rows[1][1].maximum()) == (0, 0)
    assert '60' not in win._item_rows[1][2].text()


@pytest.mark.ui
def test_rows_come_and_go_with_their_papers(win):
    win.start_item(1, 'Smith 1998')
    win.start_item(2, 'Jones 2001')

    win.end_item(1)
    assert set(win._item_rows) == {2}
    assert win.items_box.isVisible()

    win.end_item(2)
    assert win._item_rows == {}
    assert not win.items_box.isVisible()   # nothing in flight → no empty gap


@pytest.mark.ui
def test_progress_for_an_unknown_paper_is_ignored(win):
    """A late progress signal from a paper whose row is already gone must not
    resurrect it — the queued cross-thread emit can land after the row went."""
    win.set_item_progress(999, 3, 10)

    assert win._item_rows == {}
    assert not win.items_box.isVisible()


@pytest.mark.ui
def test_a_server_notice_does_not_wipe_the_live_bars(win):
    """set_current() used to clear the single item bar. With per-paper rows it
    must not, or a mid-paper 502 (which relabels the headline) would blank the
    progress of every paper still parsing."""
    win.start_item(1, 'Smith 1998')
    win.set_item_progress(1, 20, 40)

    win.mark_server_wait('HTTP 502 …')
    win.mark_server_back('back after 90s')

    assert set(win._item_rows) == {1}
    assert win._item_rows[1][1].value() == 20


@pytest.mark.ui
def test_finish_clears_every_row(win):
    win.start_item(1, 'Smith 1998')
    win.start_item(2, 'Jones 2001')

    win.finish()

    assert win._item_rows == {}
    assert not win.items_box.isVisible()


@pytest.mark.ui
def test_unknown_entry_count_shows_a_busy_bar(win):
    """A paper still locating its references section has no total yet; a bar
    sitting at 0/0 reads as stalled, so it runs busy instead."""
    win.start_item(1, 'Smith 1998')
    _row, bar, count = win._item_rows[1]
    assert (bar.minimum(), bar.maximum()) == (0, 0)   # Qt's busy indicator

    win.set_item_progress(1, 0, 0)
    assert (bar.minimum(), bar.maximum()) == (0, 0)
    assert 'scanning' in count.text()
