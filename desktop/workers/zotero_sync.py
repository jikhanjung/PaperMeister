"""Background worker for Zotero sync with progress reporting."""
from PyQt6.QtCore import QThread, pyqtSignal


class ZoteroSyncWorker(QThread):
    """Two-phase Zotero sync: collections then items (incremental).

    Signals:
        progress(str)  — live status updates for the status bar
        done(dict)     — final result with counts
        failed(str)    — error message
    """

    progress = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, user_id: str, api_key: str, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._api_key = api_key

    def run(self):
        try:
            result = self._sync()
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')
            return
        self.done.emit(result)

    def _sync(self) -> dict:
        from papermeister.ingestion import (
            get_or_create_zotero_source, sync_zotero_collections, sync_zotero_items,
        )
        from papermeister.preferences import get_pref, set_pref
        from papermeister.zotero_client import ZoteroClient, load_cached_collections

        client = ZoteroClient(self._user_id, self._api_key)
        source = get_or_create_zotero_source(self._user_id)

        # ── Phase 1: collections ─────────────────────────────
        self.progress.emit('Syncing collections…')
        cached = load_cached_collections()
        if cached:
            sync_zotero_collections(client, source, cached)

        fresh = client.get_collections()
        sync_zotero_collections(client, source, fresh)
        col_count = len(fresh) if fresh else 0
        self.progress.emit(f'Collections synced ({col_count}). Fetching items…')

        # ── Phase 2: items ───────────────────────────────────
        needs_full = get_pref('paperfolder_needs_full_sync', False)
        last_version = get_pref('zotero_library_version', None)
        since = None if needs_full else (int(last_version) if last_version else None)

        if since is None:
            self.progress.emit('Full item fetch (first run)…')
        else:
            self.progress.emit(f'Fetching items since v{since}…')

        items, orphans = client.get_all_items(since=since)
        item_count = len(items)
        orphan_count = sum(len(v) for v in orphans.values())

        if item_count == 0 and orphan_count == 0:
            self.progress.emit('No item changes.')
        else:
            self.progress.emit(
                f'Processing {item_count} items'
                + (f' + {orphan_count} attachments' if orphan_count else '')
                + '…'
            )

        def _progress_cb(msg: str):
            self.progress.emit(msg)

        new_items, updated_items = sync_zotero_items(
            source, items,
            orphan_attachments=orphans,
            progress_callback=_progress_cb,
            zotero_client=client,
        )

        # Store new version and clear flag.
        new_version = client.get_library_version()
        set_pref('zotero_library_version', new_version)
        if needs_full:
            set_pref('paperfolder_needs_full_sync', False)

        return {
            'collections': col_count,
            'new': new_items,
            'updated': updated_items,
            'version': new_version,
        }
