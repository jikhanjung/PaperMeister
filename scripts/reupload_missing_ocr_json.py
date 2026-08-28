#!/usr/bin/env python3
"""Re-upload OCR-JSON siblings whose Zotero attachment went missing.

When a phantom promoted parent was deleted in Zotero, its child OCR-JSON
attachment was deleted with it — but the local PaperFile row survives, pointing
at a now-dead Zotero key. That dangling row makes upload_ocr_json.py (and the
folder right-click "Upload OCR JSON") skip the paper, because their
(paper_id, json_name) dedup sees the JSON as "already present".

This finds JSON PaperFiles whose zotero_key no longer exists in Zotero, whose
paper has a parented PDF, and whose local OCR cache file is present, then
re-uploads the cache as a fresh sibling under the PDF's (new) parent and points
the existing row at the new key. No OCR re-run — cache is reused.

Detection uses the local Zotero DB (zotero.sqlite) for the authoritative key set.
Dry-run by default. Pass --execute to apply. Run on the machine with Zotero
credentials + data dir (Windows native Python).
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Verify TLS against the OS trust store: the lab network re-signs with its own
# root CA, which certifi does not carry. Must run before any pyzotero call.
from papermeister.nettls import install_system_trust

install_system_trust()

from papermeister.database import init_db
from papermeister.models import PaperFile
from papermeister.preferences import get_pref
from papermeister.text_extract import OCR_JSON_DIR
from papermeister.zotero_client import ZoteroClient


def log(msg):
    print(msg, flush=True)


def load_zotero_keys(zotero_db):
    uri = f'file:{zotero_db}?mode=ro&immutable=1'
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            'SELECT key FROM items '
            'WHERE libraryID = (SELECT libraryID FROM libraries WHERE type = ?)',
            ('user',),
        ).fetchall()
    finally:
        con.close()
    return {k.upper() for (k,) in rows}


def _parented_pdf(paper, zkeys):
    """A non-JSON PaperFile whose zotero_key exists in Zotero (so it has a parent)."""
    for pf in PaperFile.select().where(
        (PaperFile.paper == paper) & (~PaperFile.path.endswith('.json'))
    ):
        if pf.zotero_key and pf.zotero_key.upper() in zkeys:
            return pf
    return None


def find_candidates(zkeys, only_paper_ids=None):
    cands = []
    jsons = list(
        PaperFile.select().where(
            (PaperFile.path.endswith('.json')) & (PaperFile.zotero_key != '')
        )
    )
    for jpf in jsons:
        if jpf.zotero_key.upper() in zkeys:
            continue  # JSON attachment still exists — fine
        if only_paper_ids and jpf.paper_id not in only_paper_ids:
            continue
        cache_path = os.path.join(OCR_JSON_DIR, jpf.path)
        if not os.path.isfile(cache_path):
            continue  # no local cache to re-upload
        pdf = _parented_pdf(jpf.paper, zkeys)
        if pdf is None:
            continue  # PDF not parented in Zotero — nothing to sibling under
        cands.append((jpf, pdf, cache_path))
    return cands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply re-upload. Default is dry-run.')
    parser.add_argument('--zotero-db', default=os.path.expanduser('~/Zotero/zotero.sqlite'),
                        help='Path to zotero.sqlite (default ~/Zotero/zotero.sqlite).')
    parser.add_argument('--paper-ids', default='',
                        help='Comma-separated Paper ids to limit to (default: all detected).')
    parser.add_argument('--sleep', type=float, default=0.2,
                        help='Seconds between uploads.')
    args = parser.parse_args()

    if not os.path.isfile(args.zotero_db):
        log(f'zotero.sqlite not found: {args.zotero_db}')
        return 1
    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        log('Error: Zotero credentials not configured.')
        return 1

    init_db()
    zkeys = load_zotero_keys(args.zotero_db)
    only = {int(x) for x in args.paper_ids.split(',') if x.strip()} or None

    cands = find_candidates(zkeys, only_paper_ids=only)
    log(f'Dangling OCR-JSON rows to re-upload: {len(cands)}')
    if not cands:
        log('Nothing to do.')
        return 0

    log('')
    log('=== Plan ===')
    for jpf, pdf, cache_path in cands:
        log(f'  paper [{jpf.paper_id}] "{(jpf.paper.title or "")[:38]}"')
        log(f'        dead JSON key {jpf.zotero_key} → re-upload {jpf.path}')
        log(f'        as sibling of PDF {pdf.zotero_key}  ({os.path.getsize(cache_path)} bytes)')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to apply.')
        return 0

    import time
    client = ZoteroClient(user_id, api_key)
    done = failed = 0

    log('')
    log('=== Applying ===')
    for jpf, pdf, cache_path in cands:
        try:
            new_key = client.upload_sibling_attachment(pdf.zotero_key, cache_path)
            if not new_key:
                failed += 1
                log(f'  [{jpf.paper_id}] upload returned no key — skipped')
                continue
            old = jpf.zotero_key
            jpf.zotero_key = new_key
            jpf.status = 'processed'
            jpf.save()
            done += 1
            log(f'  [{jpf.paper_id}] {old} → {new_key}')
            if args.sleep > 0:
                time.sleep(args.sleep)
        except Exception as e:
            failed += 1
            log(f'  [{jpf.paper_id}] FAILED: {e}')

    log('')
    log(f'=== Result: re-uploaded {done}, failed {failed} ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
