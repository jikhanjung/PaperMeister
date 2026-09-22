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


@pytest.fixture
def nav_with_folders(qapp, monkeypatch):
    """A Zotero source with a real collection tree (no DB), so expansion and
    selection have something to survive."""
    from desktop.views import source_nav as mod

    def folder(fid, name, children=()):
        return SimpleNamespace(id=fid, name=name, children=list(children))

    src = SimpleNamespace(id=1, source_type='zotero', name='My Library', roots=[
        folder(10, 'Trilobita', [folder(11, 'Cambrian', [folder(12, 'Öland')]), folder(13, 'Ordovician')]),
        folder(20, 'Conodonta'),
    ])
    monkeypatch.setattr(mod.source_service, 'load_source_tree', lambda: [src])
    monkeypatch.setattr(mod._StatusPanel, 'populate', lambda self: None)
    widget = mod.SourceNav()
    widget.refresh()
    return widget


@pytest.mark.ui
def test_refresh_keeps_the_folders_open_and_the_one_chosen(nav_with_folders):
    """Apply Biblio refreshes the tree (counts move). It used to fold every
    collection back to the default and drop the selection — the user lost
    where they were, every time."""
    from PyQt6.QtCore import Qt
    widget = nav_with_folders
    tree = widget._trees[0]
    root = tree.topLevelItem(0)                    # 'My Library'
    trilobita = root.child(0)
    cambrian = trilobita.child(0)
    trilobita.setExpanded(True)
    cambrian.setExpanded(True)
    tree.setCurrentItem(cambrian.child(0))          # Öland

    widget.refresh()

    tree = widget._trees[0]
    root = tree.topLevelItem(0)
    trilobita, cambrian = root.child(0), root.child(0).child(0)
    assert root.isExpanded() and trilobita.isExpanded() and cambrian.isExpanded()
    assert not trilobita.child(1).isExpanded()          # Ordovician: never opened
    assert tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == ('folder', 12)
    # a folder the user closed stays closed, even one open by default
    root.setExpanded(False)
    widget.refresh()
    assert not widget._trees[0].topLevelItem(0).isExpanded()
