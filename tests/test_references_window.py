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
