#!/usr/bin/env python3
"""Purge local Papers/PaperFiles that were permanently deleted (empty-trash) in
Zotero but linger locally — and establish the `zotero_deleted_version` baseline.

Background (session 43): `sync_trash_state` could not tell a permanent deletion
from a restore (both leave the trash snapshot), so emptied-trash items had their
`trashed_at` silently cleared and reappeared in normal lists. The sync now calls
`apply_permanent_deletions` (via `/deleted?since=N`), but its first run only
records a baseline — it can't bound a scan over past history. This one-off does
the historical scan to clear the existing backlog.

Default `--since 0` scans the full deletion history. Matches against local
Zotero keys and deletes (cascade) the corresponding Paper / PaperFile. The
on-disk OCR JSON cache is left intact (content-addressed, reusable).

Dry-run by default. Pass --execute to delete + stamp the baseline version.
Run on the machine with Zotero credentials (Windows native Python).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Verify TLS against the OS trust store: the lab network re-signs with its own
# root CA, which certifi does not carry. Must run before any pyzotero call.
from papermeister.nettls import install_system_trust

install_system_trust()

from papermeister.database import init_db
from papermeister.ingestion import purge_local_by_keys
from papermeister.models import Paper, PaperFile
from papermeister.preferences import get_pref, set_pref
from papermeister.zotero_client import ZoteroClient


def log(msg):
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply the purge + stamp baseline. Default is dry-run.')
    parser.add_argument('--since', type=int, default=0,
                        help='Library version to scan deletions from (default 0 = full history).')
    args = parser.parse_args()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        log('Error: Zotero credentials not configured.')
        return 1

    init_db()
    client = ZoteroClient(user_id, api_key)

    log(f'Fetching Zotero deletions since version {args.since}…')
    deleted_keys = client.get_deleted_keys(since=args.since)
    log(f'  permanently-deleted item keys in Zotero: {len(deleted_keys)}')

    # Which of those exist locally? Chunk to stay under SQLite's 999-var limit.
    klist = list(deleted_keys)
    chunks = [klist[i:i + 500] for i in range(0, len(klist), 500)]
    papers, pfs = [], []
    for ch in chunks:
        papers.extend(Paper.select().where(Paper.zotero_key.in_(ch)))
        pfs.extend(PaperFile.select().where(PaperFile.zotero_key.in_(ch)))
    # PaperFiles that belong to a paper already in the purge list cascade away;
    # only count the standalone-attachment leftovers separately.
    paper_ids = {p.id for p in papers}
    standalone_pfs = [pf for pf in pfs if pf.paper_id not in paper_ids]

    log(f'  local Papers to delete:        {len(papers)}')
    log(f'  local PaperFiles (attachment-only) to delete: {len(standalone_pfs)}')

    if not papers and not standalone_pfs:
        log('Nothing to purge.')
        if args.execute:
            current = client.get_library_version()
            set_pref('zotero_deleted_version', current)
            log(f'Baseline set: zotero_deleted_version = {current}')
        return 0

    log('')
    log('=== local Papers matched (first 30) ===')
    for p in papers[:30]:
        log(f'  paper [{p.id}] key={p.zotero_key} trashed={p.trashed_at is not None}  '
            f'{(p.title or "")[:55]}')
    if standalone_pfs:
        log('--- attachment-only PaperFiles (first 30) ---')
        for pf in standalone_pfs[:30]:
            log(f'  pf [{pf.id}] paper={pf.paper_id} key={pf.zotero_key}  '
                f'{os.path.basename(pf.path)[:50]}')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to delete + set baseline.')
        return 0

    dp, df = purge_local_by_keys(deleted_keys, progress_callback=log)
    current = client.get_library_version()
    set_pref('zotero_deleted_version', current)
    log('')
    log(f'=== Done: deleted {dp} papers / {df} files ===')
    log(f'Baseline set: zotero_deleted_version = {current} '
        f'(sync now handles future deletions incrementally)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
