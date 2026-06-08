#!/usr/bin/env python3
"""Backfill: reclassify `failed` link-type Zotero attachments to 'skipped'.

linked_url / linked_file attachments are URL bookmarks or external-path links —
there is no stored file to OCR, so they should never have been queued. Before
the extension gate they were created as 'pending' (filename defaulted to the
bare item key, no contentType) and then marked 'failed' when OCR found no file.

The bare-key name carries no extension, so reclassify_attachments.py can't
catch them. This script reads the local Zotero DB (zotero.sqlite) for the
authoritative linkMode and reclassifies matching failed PaperFiles → 'skipped'.

linkMode: 0=imported_file 1=imported_url 2=linked_file 3=linked_url.
Targets linked_file(2) + linked_url(3). imported_file PDFs that failed are real
OCR failures and are left untouched (reported separately).

Dry-run by default. Pass --execute to apply. Run on the machine with the
Zotero data dir (Windows native Python).
"""

import argparse
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import PaperFile

_LINKMODE = {0: 'imported_file', 1: 'imported_url', 2: 'linked_file', 3: 'linked_url'}
_LINK_TYPES = {2, 3}  # linked_file, linked_url — no stored file to OCR


def log(msg):
    print(msg, flush=True)


def load_linkmodes(zotero_db):
    """Return {item_key: linkMode_int} for all attachments in zotero.sqlite."""
    uri = f'file:{zotero_db}?mode=ro&immutable=1'
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            'SELECT i.key, ia.linkMode '
            'FROM items i JOIN itemAttachments ia ON ia.itemID = i.itemID'
        ).fetchall()
    finally:
        con.close()
    return {k: lm for k, lm in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply the reclassification. Default is dry-run.')
    parser.add_argument('--zotero-db', default=os.path.expanduser('~/Zotero/zotero.sqlite'),
                        help='Path to zotero.sqlite (default ~/Zotero/zotero.sqlite).')
    args = parser.parse_args()

    if not os.path.isfile(args.zotero_db):
        log(f'zotero.sqlite not found: {args.zotero_db}')
        log('Pass --zotero-db <path> (run on the machine that has it).')
        return 1

    init_db()
    linkmodes = load_linkmodes(args.zotero_db)

    failed = list(
        PaperFile.select().where(
            (PaperFile.status == 'failed') & (PaperFile.zotero_key != '')
        )
    )

    targets, real_failures, unknown = [], [], []
    for pf in failed:
        lm = linkmodes.get(pf.zotero_key)
        if lm in _LINK_TYPES:
            targets.append((pf, lm))
        elif lm is None:
            unknown.append(pf)
        else:
            real_failures.append((pf, lm))

    log(f'failed attachments with zotero_key: {len(failed)}')
    log(f'  link-type → skipped:    {len(targets)}')
    log(f'  real file (leave as-is): {len(real_failures)}')
    log(f'  not found in zotero.sqlite: {len(unknown)}')

    if targets:
        by_mode = Counter(_LINKMODE.get(lm, lm) for _, lm in targets)
        log(f'  link-type breakdown: {dict(by_mode)}')

    if real_failures:
        log('')
        log('--- real file failures (kept as failed) ---')
        for pf, lm in real_failures:
            log(f'  [{pf.id}] {_LINKMODE.get(lm, lm)}  {os.path.basename(pf.path)[:50]}')

    if not targets:
        log('Nothing to reclassify.')
        return 0

    log('')
    log('=== sample link-type targets (first 10) ===')
    for pf, lm in targets[:10]:
        log(f'  [{pf.id}] paper={pf.paper_id} {_LINKMODE.get(lm, lm)} key={pf.zotero_key}')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to apply.')
        return 0

    n = 0
    for pf, _ in targets:
        pf.status = 'skipped'
        pf.failure_reason = ''
        pf.save()
        n += 1
    log('')
    log(f'=== Done: reclassified {n} link-type attachments → skipped ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
