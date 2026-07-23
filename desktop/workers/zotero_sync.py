"""Background worker for Zotero sync with progress reporting."""
import logging
import os
import time

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
            apply_permanent_deletions,
            get_or_create_zotero_source,
            sync_trash_state,
            sync_zotero_collections,
            sync_zotero_items,
        )
        from papermeister.preferences import get_pref, set_pref
        from papermeister.zotero_client import ZoteroClient

        client = ZoteroClient(self._user_id, self._api_key)
        source = get_or_create_zotero_source(self._user_id)
        logger.debug('Source: id=%s, name=%s', source.id, source.name)

        # Read both sync states BEFORE collections phase. sync_zotero_collections
        # overwrites zotero_library_version as a side effect (used by items),
        # while collections itself tracks a separate zotero_collections_version
        # so an items-only change doesn't force a full collections refetch.
        needs_full = get_pref('paperfolder_needs_full_sync', False)
        last_version = get_pref('zotero_library_version', None)
        last_col_ver = get_pref('zotero_collections_version', None)
        since = None if needs_full else (int(last_version) if last_version else None)
        col_since = None if needs_full else (int(last_col_ver) if last_col_ver else None)
        logger.debug(
            'Sync plan: needs_full=%s, item_since=%s, col_since=%s',
            needs_full, since, col_since,
        )

        # ── Phase 1: collections ─────────────────────────────
        # The Folder table is persistent, so SourceNav already shows the
        # last-known collection tree before sync starts. We no longer pre-warm
        # from the JSON cache (load_cached_collections + sync(cached)) because
        # that path duplicated the work fresh sync does and added 2s of pure
        # overhead on every sync (see devlog 044).
        phase1_start = time.perf_counter()
        self._log_progress('Syncing collections…')

        t0 = time.perf_counter()
        fresh = client.get_collections(since=col_since)
        logger.info(
            'collections: get_collections(since=%s) took %.2fs (%d entries)',
            col_since, time.perf_counter() - t0,
            len(fresh) if fresh else 0,
        )

        if fresh is None:
            # Incremental fetch returned None → no collection changes since
            # last_col_ver. Folder table already reflects the truth; nothing
            # to apply.
            self._log_progress('No collection changes.')
            # Show the cached count for the status message; an empty trail
            # would look like the library is empty.
            from papermeister.models import Folder
            col_count = (
                Folder.select().where(Folder.source == source).count()
            )
        else:
            t0 = time.perf_counter()
            sync_zotero_collections(client, source, fresh)
            logger.info(
                'collections: sync(fresh) took %.2fs',
                time.perf_counter() - t0,
            )
            col_count = len(fresh)

        # Stamp the collections-specific version regardless of whether anything
        # changed — sync_zotero_collections only overwrites zotero_library_version
        # (used by items), so without this our col_since would never advance.
        try:
            new_col_ver = client.get_library_version()
            set_pref('zotero_collections_version', new_col_ver)
        except Exception:
            pass

        logger.info(
            'collections: phase 1 total %.2fs',
            time.perf_counter() - phase1_start,
        )
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
            logger=logger,
        )
        logger.info('sync_zotero_items: new=%d, updated=%d', new_items, updated_items)

        # ── Phase 3a: permanent deletions (empty-trash) ──────
        # Must run BEFORE trash sync: a purged item is absent from the trash
        # snapshot, so the trash step would otherwise read it as "restored" and
        # clear its flag. Deleting it here removes it from that ambiguity.
        try:
            del_result = apply_permanent_deletions(client, progress_callback=_progress_cb)
            logger.info('apply_permanent_deletions: %s', del_result)
            if del_result.get('deleted_papers') or del_result.get('deleted_files'):
                self._log_progress(
                    f"Purged {del_result['deleted_papers']} papers / "
                    f"{del_result['deleted_files']} files (deleted in Zotero)"
                )
        except Exception:
            import traceback
            logger.warning('Permanent-deletion sync failed:\n%s', traceback.format_exc())
            del_result = None

        # ── Phase 3: trash ───────────────────────────────────
        # Full snapshot (Zotero trash endpoint has no incremental form).
        # Cheap in practice because trash stays small.
        try:
            trash_result = sync_trash_state(client, progress_callback=_progress_cb)
            logger.info('sync_trash_state: %s', trash_result)
            nt_p = trash_result['newly_trashed_papers']
            r_p = trash_result['restored_papers']
            nt_f = trash_result['newly_trashed_files']
            r_f = trash_result['restored_files']
            if any((nt_p, r_p, nt_f, r_f)):
                self._log_progress(
                    f'Trash sync: trashed {nt_p} papers / {nt_f} files, '
                    f'restored {r_p} papers / {r_f} files'
                )
            else:
                self._log_progress('Trash sync: no changes.')
        except Exception:
            # Trash sync is best-effort; don't fail the whole sync over it.
            import traceback
            logger.warning('Trash sync failed:\n%s', traceback.format_exc())
            trash_result = None

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
            'trash': trash_result,
        }
