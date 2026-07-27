"""SourceNav.refresh() must not move the user off the tab they are on.

The visible case is startup: the window appears, the Zotero sync runs in the
background, and when it finishes `_on_sync_done` calls `refresh()`. Anyone who
navigated to another source tab in those seconds got yanked back to the first
tab. The same applied after applying biblio, which also refreshes.

The paper list itself was never the problem — `_apply_current_selection()`
already restores it from `_current_selection`; only the tab bar jumped, leaving
the selected tab and the listed papers disagreeing.
"""
from types import SimpleNamespace

import pytest


def _src(sid, source_type, name):
    return SimpleNamespace(id=sid, source_type=source_type, name=name)


@pytest.fixture
def nav(qapp, monkeypatch):
    """A SourceNav whose source list we control, with DB-touching bits stubbed."""
    from desktop.views import source_nav as mod

    sources = [_src(1, 'zotero', 'My Library'), _src(2, 'directory', 'Papers')]

    monkeypatch.setattr(mod.source_service, 'load_source_tree', lambda: list(sources))
    monkeypatch.setattr(mod.SourceNav, '_populate_collections',
                        lambda self, tree, src: None)
    monkeypatch.setattr(mod._StatusPanel, 'populate', lambda self: None)

    widget = mod.SourceNav()
    widget.refresh()
    return widget, sources


@pytest.mark.ui
def test_refresh_keeps_the_selected_tab(nav):
    """The startup case: user moves to the local-folder tab mid-sync."""
    widget, _ = nav
    widget.tabs.setCurrentIndex(1)

    widget.refresh()

    assert widget.tabs.currentIndex() == 1
    assert widget.tabs.tabText(1) == 'Papers'


@pytest.mark.ui
def test_refresh_follows_the_source_not_the_index(nav):
    """A sync that adds a source ahead of the selected one must not leave the
    user on whatever slid into that slot."""
    widget, sources = nav
    widget.tabs.setCurrentIndex(1)          # 'Papers'
    sources.insert(0, _src(3, 'directory', 'Inbox'))

    widget.refresh()

    assert widget.tabs.tabText(widget.tabs.currentIndex()) == 'Papers'
    assert widget.tabs.currentIndex() == 2   # shifted along, still the same source


@pytest.mark.ui
def test_refresh_falls_back_when_the_source_is_gone(nav):
    """Removing the selected local folder — nothing to return to, so the
    default first tab stands rather than an out-of-range index."""
    widget, sources = nav
    widget.tabs.setCurrentIndex(1)
    sources.pop(1)

    widget.refresh()

    assert widget.tabs.currentIndex() == 0
    assert widget.tabs.tabText(0) == 'My Library'
