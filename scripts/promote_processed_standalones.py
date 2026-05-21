#!/usr/bin/env python3
"""Retroactively promote OCR'd standalone PDFs to Zotero parent items.

Targets the gap left by `auto_promote_standalone` only running on fresh
OCR completions: PDFs that were OCR'd before the auto-promote feature
existed stay standalone in Zotero. This script walks the local DB and
calls `promote_standalone_with_filename` for each surviving processed
standalone PaperFile.

For each candidate:
  1. Create a Zotero parent item (itemType=document, title=filename
     without extension) in the same collection(s).
  2. Re-parent the PDF attachment under the new item.
  3. Update local Paper.zotero_key to the new parent's key.

Default is dry-run; pass --apply to actually write to Zotero.
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
from papermeister.models import Folder, Paper, PaperFile, PaperFolder
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient
from papermeister.zotero_writeback import (
    promote_standalone_with_filename,
    ZoteroWriteAccessDenied,
)


def find_candidates(folder_name_contains: str = '', filename_contains: str = ''):
    """Processed standalone PDFs ready to be promoted.

    A candidate is a PaperFile that:
      - Is the PDF (not its OCR JSON sibling).
      - Has status='processed' (OCR completed).
      - Its Paper.zotero_key equals the PaperFile.zotero_key, i.e. the
        Paper was synced as standalone and never re-parented.

    Optional filters reduce the set:
      folder_name_contains: case-insensitive Folder.name substring (joined
        through PaperFolder).
      filename_contains: case-insensitive PaperFile.path substring.

    Returns a list of PaperFile rows (with .paper preloaded).
    """
    q = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (Paper.zotero_key != '')
            & (Paper.zotero_key == PaperFile.zotero_key)
            & (~PaperFile.path.endswith('.json'))
        )
    )
    if folder_name_contains:
        # Join via PaperFolder → Folder so we can filter by folder name.
        # DISTINCT keeps the row count honest if a Paper sits in multiple
        # collections matching the filter.
        q = (
            q.switch(Paper)
            .join(PaperFolder, on=(PaperFolder.paper == Paper.id))
            .join(Folder, on=(PaperFolder.folder == Folder.id))
            .where(Folder.name.contains(folder_name_contains))
            .distinct()
        )
    if filename_contains:
        q = q.where(PaperFile.path.contains(filename_contains))
    return list(q)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help='Actually create Zotero parent items (default is dry-run).',
    )
    parser.add_argument(
        '--limit', type=int, default=0,
        help='Stop after this many candidates (0 = no limit).',
    )
    parser.add_argument(
        '--folder-name-contains', default='',
        help='Only candidates in a Folder whose name contains this substring.',
    )
    parser.add_argument(
        '--filename-contains', default='',
        help='Only candidates whose PaperFile.path contains this substring.',
    )
    parser.add_argument(
        '--item-type', default='document',
        help='Zotero itemType for the new parent (default: document).',
    )
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.', file=sys.stderr)
        return 1

    client = ZoteroClient(user_id, api_key)

    candidates = find_candidates(
        folder_name_contains=args.folder_name_contains,
        filename_contains=args.filename_contains,
    )

    filter_bits = []
    if args.folder_name_contains:
        filter_bits.append(f'folder~"{args.folder_name_contains}"')
    if args.filename_contains:
        filter_bits.append(f'filename~"{args.filename_contains}"')
    suffix = f' (filtered by {", ".join(filter_bits)})' if filter_bits else ''
    print(f'Processed standalone PDFs: {len(candidates)}{suffix}')

    if args.limit > 0:
        candidates = candidates[:args.limit]
        print(f'  --limit {args.limit} → {len(candidates)}')

    if not args.apply:
        print('\n*** DRY RUN — no Zotero changes ***\n')

    promoted = 0
    skipped = 0
    failed = 0

    for i, pf in enumerate(candidates, 1):
        paper = pf.paper
        title_preview = (paper.title or '')[:60]
        print(f'[{i}/{len(candidates)}] pid={paper.id} att={paper.zotero_key} '
              f'"{title_preview}"')

        if not args.apply:
            promoted += 1  # would-promote count, reused for tally
            continue

        try:
            new_key = promote_standalone_with_filename(
                pf, client=client, item_type=args.item_type,
            )
        except ZoteroWriteAccessDenied as e:
            print(f'    ✗ write access denied: {e}')
            print('    Stopping — fix the API key first.')
            failed += 1
            break
        except Exception as e:
            print(f'    ✗ FAILED: {e}')
            failed += 1
            continue

        if new_key is None:
            print('    · no-op (not actually standalone anymore)')
            skipped += 1
        else:
            print(f'    ✓ parent created: {new_key}')
            promoted += 1

    print('\n=== Summary ===')
    if args.apply:
        print(f'  promoted: {promoted}')
        print(f'  skipped:  {skipped}')
        print(f'  failed:   {failed}')
    else:
        print(f'  would promote: {promoted}')
        print('\nRe-run with --apply to perform the promotions.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
