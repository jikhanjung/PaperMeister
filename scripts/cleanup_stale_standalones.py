#!/usr/bin/env python3
"""Detect and merge stale standalone Papers into their new Zotero parents.

When a user promotes a standalone PDF in the Zotero GUI ("Create Parent
Item…"), the attachment gets a parentItem set in Zotero. A subsequent
PaperMeister sync creates a new local Paper for the parent — but the
existing PaperFile (already linked to an older Paper whose zotero_key
equals the attachment key) is left behind. Result: two local Papers in
the same collection, one with the PDF and one without.

This script:
  1. Finds local Papers that look like a standalone (Paper.zotero_key
     equals at least one of its PaperFile.zotero_keys).
  2. Queries Zotero to confirm the current parentItem.
  3. If Zotero says the PDF is now a child of another item that we already
     have locally, merges the old standalone Paper into the new parent.

Default is dry-run; pass --apply to actually merge.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the desktop app's SSL monkey-patch (institutional CAs trip pyzotero
# otherwise). Must run before any pyzotero call.
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
from papermeister.ingestion import _merge_stale_standalone


def find_standalone_candidates(title_contains: str = '', filename_contains: str = ''):
    """Local Papers where Paper.zotero_key matches one of its PaperFile.zotero_keys.

    Optional filters (case-insensitive substring match) cut the candidate
    set down — useful when you know which PDF to target. Both filters can
    be combined (AND).

    Returns list of (paper, paper_file) tuples — the PaperFile is the one
    that's been acting as the self-attachment.
    """
    q = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (Paper.zotero_key != '')
            & (Paper.zotero_key == PaperFile.zotero_key)
        )
    )
    if title_contains:
        q = q.where(Paper.title.contains(title_contains))
    if filename_contains:
        q = q.where(PaperFile.path.contains(filename_contains))
    return [(pf.paper, pf) for pf in q]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help='Actually merge stale standalones (default is dry-run).',
    )
    parser.add_argument(
        '--limit', type=int, default=0,
        help='Stop after this many candidates (0 = no limit).',
    )
    parser.add_argument(
        '--title-contains', default='',
        help='Only candidates whose Paper.title contains this substring.',
    )
    parser.add_argument(
        '--filename-contains', default='',
        help='Only candidates whose PaperFile.path contains this substring.',
    )
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.', file=sys.stderr)
        return 1

    client = ZoteroClient(user_id, api_key)
    zot = client._zot

    candidates = find_standalone_candidates(
        title_contains=args.title_contains,
        filename_contains=args.filename_contains,
    )
    filter_parts = []
    if args.title_contains:
        filter_parts.append(f'title~"{args.title_contains}"')
    if args.filename_contains:
        filter_parts.append(f'filename~"{args.filename_contains}"')
    suffix = f' (filtered by {", ".join(filter_parts)})' if filter_parts else ''
    print(f'Standalone-shaped Papers in DB: {len(candidates)}{suffix}')
    if args.limit > 0:
        candidates = candidates[:args.limit]
        print(f'  --limit {args.limit} → {len(candidates)}')

    if not args.apply:
        print('\n*** DRY RUN — no changes will be made ***\n')

    actually_standalone = 0
    will_merge = 0
    new_parent_missing = 0
    fetch_errors = 0
    merged = 0

    for i, (paper, pfile) in enumerate(candidates, 1):
        try:
            item = zot.item(paper.zotero_key)
            data = item['data']
        except Exception as e:
            print(f'[{i}/{len(candidates)}] pid={paper.id} key={paper.zotero_key}: '
                  f'fetch failed ({e})')
            fetch_errors += 1
            continue

        parent_key = data.get('parentItem', '')
        if not parent_key:
            # Still genuinely standalone; nothing to do.
            actually_standalone += 1
            continue

        new_parent = Paper.get_or_none(Paper.zotero_key == parent_key)
        if new_parent is None:
            print(f'[{i}/{len(candidates)}] pid={paper.id} key={paper.zotero_key}: '
                  f'parentItem={parent_key} not in local DB — re-sync first')
            new_parent_missing += 1
            continue

        if new_parent.id == paper.id:
            # Already merged (or zotero_key was patched up). Skip.
            continue

        print(f'[{i}/{len(candidates)}] '
              f'merge pid={paper.id} ("{(paper.title or "")[:50]}") '
              f'→ pid={new_parent.id} ("{(new_parent.title or "")[:50]}")')
        will_merge += 1

        if args.apply:
            try:
                _merge_stale_standalone(paper, new_parent)
                merged += 1
            except Exception as e:
                print(f'    ✗ merge failed: {e}')

    print('\n=== Summary ===')
    print(f'  candidates inspected:       {len(candidates)}')
    print(f'  still actually standalone:  {actually_standalone}')
    print(f'  would merge / merged:       {will_merge}'
          + (f' ({merged} succeeded)' if args.apply else ''))
    print(f'  new parent missing locally: {new_parent_missing}')
    print(f'  fetch errors:               {fetch_errors}')
    if not args.apply and will_merge > 0:
        print('\nRe-run with --apply to perform the merges.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
