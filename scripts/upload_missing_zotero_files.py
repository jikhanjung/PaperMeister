#!/usr/bin/env python3
"""Re-upload PDFs that exist in the local Zotero storage dir but are missing
from Zotero web storage (server download → 404).

Root cause (session 43 diagnosis): a handful of `imported_file` attachments
have the actual PDF sitting in `<Zotero data>/storage/<KEY>/<file>` and a
local storageHash, yet the file was never pushed to web storage — so our OCR
download 404s and the PaperFile is stuck status='failed', hash=''.

This script finds failed (and optionally pending) PDF PaperFiles whose local
`storage/<zotero_key>/` holds a real file, and uploads that file to the
existing attachment item via ZoteroClient.replace_attachment_file() — the
attachment KEY is preserved (no delete+recreate). On success the PaperFile is
reset to status='pending' so the normal Process/OCR flow can pick it up.

Skips attachments whose local storage dir is empty/missing (file genuinely
unavailable) and linked_url items (no file at all).

Dry-run by default. Pass --execute to upload. Detection runs on the machine
that has the Zotero storage dir (i.e. Windows native Python).
"""

import argparse
import os
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
from papermeister.models import PaperFile
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient


def log(msg):
    print(msg, flush=True)


def _local_files_for(storage_dir, key):
    """Return list of real files under storage/<key>/ (non-hidden), or []."""
    d = os.path.join(storage_dir, key)
    if not os.path.isdir(d):
        return []
    return [
        os.path.join(d, f) for f in os.listdir(d)
        if os.path.isfile(os.path.join(d, f)) and not f.startswith('.')
    ]


def find_candidates(storage_dir, statuses):
    """Split failed/pending attachments by what's in local Zotero storage.

    Only real .pdf files are upload+OCR targets — a stuck attachment whose
    local file is a .txt/.zip/.djvu/etc. is "failed" because OCR can't read it,
    not because of an upload gap, so uploading + resetting to pending would just
    loop. Those are reported separately and never touched.
    """
    rows = list(
        PaperFile.select().where(
            (~PaperFile.path.endswith('.json'))
            & (PaperFile.zotero_key != '')
            & (PaperFile.status.in_(statuses))
            & (PaperFile.trashed_at.is_null(True))
        )
    )
    found, non_pdf_local, no_local = [], [], 0
    for pf in rows:
        files = _local_files_for(storage_dir, pf.zotero_key)
        pdfs = [p for p in files if p.lower().endswith('.pdf')]
        if pdfs:
            found.append((pf, pdfs[0]))
        elif files:
            non_pdf_local.append((pf, files[0]))
        else:
            no_local += 1
    return found, non_pdf_local, no_local


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply uploads. Default is dry-run.')
    parser.add_argument('--zotero-storage', default=os.path.expanduser('~/Zotero/storage'),
                        help='Path to Zotero storage dir (default ~/Zotero/storage).')
    parser.add_argument('--include-pending', action='store_true',
                        help='Also consider status=pending PDFs, not just failed.')
    parser.add_argument('--no-reset', action='store_true',
                        help='Do not reset PaperFile.status to pending after upload.')
    args = parser.parse_args()

    init_db()

    if not os.path.isdir(args.zotero_storage):
        log(f'Zotero storage dir not found: {args.zotero_storage}')
        log('Pass --zotero-storage <path> (run on the machine that has it).')
        return 1

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if args.execute and (not user_id or not api_key):
        log('Error: Zotero credentials not configured.')
        return 1

    statuses = ['failed', 'pending'] if args.include_pending else ['failed']
    found, non_pdf_local, no_local = find_candidates(args.zotero_storage, statuses)

    log(f'Zotero storage: {args.zotero_storage}')
    log(f'Candidate statuses: {statuses}')
    log(f'Recoverable PDFs (local .pdf present): {len(found)}')
    log(f'Non-PDF local file (skip):             {len(non_pdf_local)}')
    log(f'No local file (skip):                  {no_local}')

    if non_pdf_local:
        log('')
        log('--- skipped (local file is not a PDF; not an OCR target) ---')
        for pf, local in non_pdf_local:
            log(f'  [{pf.id}] key={pf.zotero_key}  {os.path.basename(local)}')

    if not found:
        log('Nothing to upload.')
        return 0

    log('')
    log('=== Plan ===')
    for pf, local in found:
        sz = os.path.getsize(local)
        log(f'  [{pf.id}] paper={pf.paper_id} key={pf.zotero_key} status={pf.status}')
        log(f'        local: {local} ({sz} bytes)')

    if not args.execute:
        log('')
        log('[DRY-RUN] No uploads. Re-run with --execute to apply.')
        return 0

    client = ZoteroClient(user_id, api_key)

    uploaded = unchanged = failed = reset = 0
    log('')
    log('=== Applying ===')
    for pf, local in found:
        try:
            result = client.replace_attachment_file(pf.zotero_key, local)
        except Exception as e:
            failed += 1
            log(f'  UPLOAD FAIL [{pf.zotero_key}]: {e}')
            continue
        if result == 'updated':
            uploaded += 1
        elif result == 'unchanged':
            unchanged += 1
        else:
            failed += 1
            log(f'  UPLOAD returned None [{pf.zotero_key}] — skip reset')
            continue

        if not args.no_reset and pf.status == 'failed':
            pf.status = 'pending'
            pf.failure_reason = ''
            pf.save()
            reset += 1
        log(f'  {result} [{pf.zotero_key}] paper={pf.paper_id}'
            f'{"  → status=pending" if (not args.no_reset and result != None) else ""}')

    log('')
    log('=== Result ===')
    log(f'  uploaded:        {uploaded}')
    log(f'  unchanged:       {unchanged}')
    log(f'  failed:          {failed}')
    log(f'  status reset→pending: {reset}')
    log('')
    log('Next: Process these papers (OCR). Folder Process Folder retries '
        'failed/pending, or right-click → Retry on each.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
