"""Background worker for Zotero sync with progress reporting."""
import logging
import os
from PyQt6.QtCore import QThread, pyqtSignal

_LOG_DIR = os.path.join(os.path.expanduser('~'), '.papermeister', 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)

logger = logging.getLogger('zotero_sync')
logger.setLevel(logging.DEBUG)
class _FlushHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.stream.flush()

if not logger.handlers:
    _fh = _FlushHandler(
        os.path.join(_LOG_DIR, 'zotero_sync.log'), encoding='utf-8',
    )
    _fh.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S',
    ))
    logger.addHandler(_fh)


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

    def _log_progress(self, msg: str):
        logger.info(msg)
        self.progress.emit(msg)

    def run(self):
        logger.info('=== Sync started ===')
        try:
            result = self._sync()
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            logger.error('Sync failed with exception:\n%s', tb)
            self.failed.emit(f'{type(exc).__name__}: {exc}')
            return
        logger.info('=== Sync finished: %s ===', result)
        self.done.emit(result)

    def _sync(self) -> dict:
        from papermeister.ingestion import (
            get_or_create_zotero_source, sync_zotero_collections, sync_zotero_items,
        )
        from papermeister.preferences import get_pref, set_pref
        from papermeister.zotero_client import ZoteroClient, load_cached_collections

        client = ZoteroClient(self._user_id, self._api_key)
        source = get_or_create_zotero_source(self._user_id)
        logger.debug('Source: id=%s, name=%s', source.id, source.name)

        # Read item sync state BEFORE collections phase (which overwrites
        # zotero_library_version as a side effect of sync_zotero_collections).
        needs_full = get_pref('paperfolder_needs_full_sync', False)
        last_version = get_pref('zotero_library_version', None)
        since = None if needs_full else (int(last_version) if last_version else None)
        logger.debug('Item sync plan: needs_full=%s, last_version=%s, since=%s', needs_full, last_version, since)

        # ── Phase 1: collections ─────────────────────────────
        self._log_progress('Syncing collections…')
        cached = load_cached_collections()
        logger.debug('Cached collections: %s', len(cached) if cached else 'none')
        if cached:
            sync_zotero_collections(client, source, cached)

        fresh = client.get_collections()
        sync_zotero_collections(client, source, fresh)
        col_count = len(fresh) if fresh else 0
        self._log_progress(f'Collections synced ({col_count}). Fetching items…')

        # ── Phase 2: items ───────────────────────────────────
        logger.debug('needs_full=%s, last_version=%s, since=%s', needs_full, last_version, since)

        if since is None:
            self._log_progress('Full item fetch (first run)…')
        else:
            self._log_progress(f'Fetching items since v{since}…')

        logger.debug('Calling client.get_all_items(since=%s)…', since)
        items, orphans = client.get_all_items(since=since)
        item_count = len(items)
        orphan_count = sum(len(v) for v in orphans.values())
        logger.info('get_all_items returned %d items, %d orphan attachments', item_count, orphan_count)

        if item_count == 0 and orphan_count == 0:
            self._log_progress('No item changes.')
        else:
            self._log_progress(
                f'Processing {item_count} items'
                + (f' + {orphan_count} attachments' if orphan_count else '')
                + '…'
            )

        def _progress_cb(msg: str):
            self._log_progress(msg)

        new_items, updated_items = sync_zotero_items(
            source, items,
            orphan_attachments=orphans,
            progress_callback=_progress_cb,
            zotero_client=client,
        )
        logger.info('sync_zotero_items: new=%d, updated=%d', new_items, updated_items)

        # Store new version and clear flag.
        new_version = client.get_library_version()
        set_pref('zotero_library_version', new_version)
        logger.debug('Stored library version: %s', new_version)
        if needs_full:
            set_pref('paperfolder_needs_full_sync', False)

        return {
            'collections': col_count,
            'new': new_items,
            'updated': updated_items,
            'version': new_version,
        }
