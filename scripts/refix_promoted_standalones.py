#!/usr/bin/env python3
"""Repair "phantom parent" papers: a standalone PDF that PaperMeister
auto-promoted (session 36) by creating a Zotero parent item, where that parent
item was later deleted in Zotero (and is too old to appear in the /deleted log).

Symptom: `Paper.zotero_key` points at a parent item that no longer exists in
Zotero, while the PDF attachment (`PaperFile.zotero_key`) is back to a standalone
top-level item. The diff between PaperMeister papers and Zotero top-level items
shows these as mismatched keys.

Fix per paper:
  1. demote  — set Paper.zotero_key back to the PDF attachment key (matches the
               standalone reality in Zotero), so it's a valid promote target.
  2. promote — promote_standalone_with_filename() creates a FRESH Zotero parent
               item and re-parents the PDF under it.
  3. reparent — move any OCR-JSON sibling under the same new parent too.

Detection uses the local Zotero DB (zotero.sqlite) for the authoritative set of
existing item keys — checking thousands of papers via the API would be slow.

Dry-run by default. Pass --execute to apply. Run on the machine with Zotero
credentials + data dir (Windows native Python).
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the desktop app's SSL monkey-patch (institutional CAs trip pyzotero).
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_original_request = requests.api.request
def _no_verify_request(method, url, **kwargs):
    kwargs.setdefault('verify', False)
    return _original_request(method, url, **kwargs)
requests.api.request = _no_verify_request

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient
from papermeister.zotero_writeback import promote_standalone_with_filename


def log(msg):
    print(msg, flush=True)


def load_zotero_keys(zotero_db):
    """All item keys in the personal (user) Zotero library."""
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


def _pdf_file(paper):
    return (
        PaperFile.select()
        .where((PaperFile.paper == paper) & (~PaperFile.path.endswith('.json')))
        .order_by(PaperFile.id)
        .first()
    )


def find_candidates(zkeys, only_keys=None):
    """Papers whose zotero_key is absent from Zotero but whose PDF child exists."""
    cands = []
    papers = list(
        Paper.select().where(
            (Paper.zotero_key != '') & (Paper.trashed_at.is_null())
        )
    )
    for p in papers:
        if p.zotero_key.upper() in zkeys:
            continue  # parent still exists — fine
        if only_keys and p.zotero_key not in only_keys:
            continue
        pdf = _pdf_file(p)
        if pdf is None or not pdf.zotero_key:
            continue
        if pdf.zotero_key.upper() not in zkeys:
            continue  # PDF also gone — different problem, skip
        cands.append((p, pdf))
    return cands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply demote + re-promote. Default is dry-run.')
    parser.add_argument('--zotero-db', default=os.path.expanduser('~/Zotero/zotero.sqlite'),
                        help='Path to zotero.sqlite (default ~/Zotero/zotero.sqlite).')
    parser.add_argument('--keys', default='',
                        help='Comma-separated parent keys to limit to (default: all detected).')
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
    log(f'Zotero personal-library item keys: {len(zkeys)}')

    only_keys = {k.strip() for k in args.keys.split(',') if k.strip()} or None
    cands = find_candidates(zkeys, only_keys=only_keys)
    log(f'Phantom-parent papers to refix: {len(cands)}')
    if not cands:
        log('Nothing to do.')
        return 0

    log('')
    log('=== Plan ===')
    for p, pdf in cands:
        log(f'  paper [{p.id}] "{(p.title or "")[:40]}"')
        log(f'        phantom parent: {p.zotero_key} (gone)  →  demote to PDF {pdf.zotero_key}')
        log('        then create fresh parent + reparent PDF (+ JSON siblings)')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to apply.')
        return 0

    client = ZoteroClient(user_id, api_key)
    fixed = failed = 0

    log('')
    log('=== Applying ===')
    for p, pdf in cands:
        try:
            # 1) demote — Paper.zotero_key back to the standalone PDF attachment.
            p.zotero_key = pdf.zotero_key
            p.save()
            # Re-fetch so promote sees the updated paper via paper_file.paper.
            pdf = PaperFile.get_by_id(pdf.id)

            # 2) promote — create a fresh Zotero parent + reparent the PDF.
            new_key = promote_standalone_with_filename(pdf, client=client)
            if not new_key:
                failed += 1
                log(f'  [{p.id}] promote returned None (not standalone?) — skipped')
                continue

            # 3) reparent OCR-JSON siblings under the same new parent.
            jsons = list(
                PaperFile.select().where(
                    (PaperFile.paper == p)
                    & (PaperFile.path.endswith('.json'))
                    & (PaperFile.zotero_key != '')
                )
            )
            reparented = 0
            for j in jsons:
                if j.zotero_key.upper() not in zkeys:
                    continue
                try:
                    jitem = client._zot.item(j.zotero_key)
                    jdata = jitem['data']
                    jdata['parentItem'] = new_key
                    jdata['collections'] = []
                    client._zot.update_item(jdata)
                    reparented += 1
                except Exception as e:
                    log(f'    JSON sibling {j.zotero_key} reparent failed: {e}')

            fixed += 1
            log(f'  [{p.id}] → new parent {new_key}  (PDF {pdf.zotero_key}, '
                f'{reparented} JSON sibling(s) reparented)')
        except Exception as e:
            failed += 1
            log(f'  [{p.id}] FAILED: {e}')

    log('')
    log('=== Result ===')
    log(f'  refixed: {fixed}')
    log(f'  failed:  {failed}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
