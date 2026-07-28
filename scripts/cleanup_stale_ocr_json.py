#!/usr/bin/env python3
"""Delete stale duplicate OCR-JSON siblings left over after a PDF was
replaced on a Zotero parent item.

Background (devlog 047): the `{hash}.json` → `{pdf}.{hash[:8]}.json` filename
migration left a tail of legacy `{64hex}.json` PaperFiles that could not be
renamed because their source PDF (the PDF whose SHA256 == the filename hash)
is no longer on the paper. The paper meanwhile already carries the current
PDF *and* a correctly-named new-form JSON for it. The legacy file is therefore
OCR of a superseded PDF — safe to remove.

A row is deleted ONLY when ALL hold (computed, not hard-coded):
  1. path matches `^[0-9a-f]{64}\\.json$`         (legacy hash-named JSON)
  2. NO PDF on the same paper has hash == path[:64] (its source PDF is gone)
  3. the paper still has >= 1 PDF (non-.json) row   (PDF preserved)
  4. the paper still has >= 1 *other* new-form JSON  (`*.pdf.*.json`)
                                                     (the paper keeps its OCR)
Rows failing 3 or 4 are SKIPPED and reported — never delete a paper's only OCR.

Three layers removed per row:
  - Zotero attachment item (data.key)  — skip with --skip-zotero
  - local cache file ~/PaleoBytes/PaperMeister/ocr_json/{hash}.json
  - DB PaperFile row

Dry-run by default. Pass --execute to apply.
"""

import argparse
import os
import re
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
from papermeister.text_extract import OCR_JSON_DIR
from papermeister.zotero_client import ZoteroClient

LEGACY_RE = re.compile(r'^([0-9a-f]{64})\.json$')


def log(msg):
    print(msg, flush=True)


def _paper_has_pdf(paper):
    return (
        PaperFile.select()
        .where((PaperFile.paper == paper) & (~PaperFile.path.endswith('.json')))
        .exists()
    )


def _paper_has_other_newform_json(paper, exclude_id):
    """A new-form JSON is `*.pdf.{8hex}.json` — contains '.pdf.' before .json."""
    return (
        PaperFile.select()
        .where(
            (PaperFile.paper == paper)
            & (PaperFile.id != exclude_id)
            & (PaperFile.path.endswith('.json'))
            & (PaperFile.path.contains('.pdf.'))
        )
        .exists()
    )


def find_stale(limit=0):
    """Return (deletable, skipped) lists of PaperFile rows + reasons."""
    deletable = []
    skipped = []

    json_pfs = list(
        PaperFile.select().where(PaperFile.path.endswith('.json'))
    )
    for jpf in json_pfs:
        m = LEGACY_RE.match(jpf.path)
        if not m:
            continue  # not a legacy hash-named JSON
        pdf_hash = m.group(1)

        # (2) source PDF for this hash must be ABSENT on the paper
        source_pdf_present = (
            PaperFile.select()
            .where(
                (PaperFile.paper == jpf.paper)
                & (PaperFile.hash == pdf_hash)
                & (~PaperFile.path.endswith('.json'))
            )
            .exists()
        )
        if source_pdf_present:
            continue  # rename migration would have handled it; not stale

        # (3)+(4) guards: paper must keep a PDF and another good JSON
        if not _paper_has_pdf(jpf.paper):
            skipped.append((jpf, 'paper has NO PDF — refuse'))
            continue
        if not _paper_has_other_newform_json(jpf.paper, jpf.id):
            skipped.append((jpf, 'paper has NO other new-form JSON — refuse (only OCR)'))
            continue

        deletable.append(jpf)

    if limit > 0:
        deletable = deletable[:limit]
    return deletable, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply deletions. Default is dry-run.')
    parser.add_argument('--skip-zotero', action='store_true',
                        help='Only remove local cache + DB row; leave Zotero attachment.')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N rows (0 = all).')
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if args.execute and not args.skip_zotero and (not user_id or not api_key):
        log('Error: Zotero credentials not configured (need them to delete '
            'attachments; or pass --skip-zotero).')
        return 1

    deletable, skipped = find_stale(limit=args.limit)

    log(f'Stale legacy OCR-JSON rows to delete: {len(deletable)}')
    log(f'Skipped (safety guard tripped):       {len(skipped)}')
    for jpf, reason in skipped:
        log(f'  SKIP [{jpf.id}] paper={jpf.paper_id}: {reason}')

    if not deletable:
        log('Nothing to delete.')
        return 0

    log('')
    log('=== Plan ===')
    for jpf in deletable:
        p = jpf.paper
        cache_path = os.path.join(OCR_JSON_DIR, jpf.path)
        cache_state = 'present' if os.path.exists(cache_path) else 'absent'
        log(f'  [{jpf.id}] paper={p.id} "{(p.title or "")[:55]}"')
        log(f'        zotero={jpf.zotero_key or "(none)"}  cache={cache_state}')
        log(f'        file={jpf.path}')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes made. Re-run with --execute to apply.')
        return 0

    client = None
    if not args.skip_zotero:
        client = ZoteroClient(user_id, api_key)

    zot_deleted = zot_gone = zot_failed = 0
    cache_removed = cache_absent = 0
    db_deleted = 0

    log('')
    log('=== Applying ===')
    for jpf in deletable:
        # 1) Zotero attachment — fetch then delete. A failed fetch with 404
        #    means the attachment is already gone; treat as clean and proceed.
        if client is not None and jpf.zotero_key:
            try:
                item = client._zot.item(jpf.zotero_key)
            except Exception as e:
                msg = str(e)
                if '404' in msg or 'Not found' in msg or 'not found' in msg:
                    zot_gone += 1
                    item = None
                else:
                    zot_failed += 1
                    log(f'  Zotero FETCH FAIL [{jpf.zotero_key}]: {e} — skip row')
                    continue
            if item is not None:
                try:
                    client._zot.delete_item(item)
                    zot_deleted += 1
                except Exception as e:
                    zot_failed += 1
                    log(f'  Zotero DELETE FAIL [{jpf.zotero_key}]: {e} — skip row')
                    continue

        # 2) local cache file
        cache_path = os.path.join(OCR_JSON_DIR, jpf.path)
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                cache_removed += 1
            except OSError as e:
                log(f'  cache remove failed [{jpf.path}]: {e}')
        else:
            cache_absent += 1

        # 3) DB row
        pid, jid, key = jpf.paper_id, jpf.id, jpf.zotero_key
        jpf.delete_instance()
        db_deleted += 1
        log(f'  deleted [{jid}] paper={pid} zot={key or "none"}')

    log('')
    log('=== Result ===')
    log(f'  Zotero deleted:   {zot_deleted}')
    log(f'  Zotero already gone: {zot_gone}')
    log(f'  Zotero failures:  {zot_failed}')
    log(f'  cache removed:    {cache_removed}')
    log(f'  cache absent:     {cache_absent}')
    log(f'  DB rows deleted:  {db_deleted}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
