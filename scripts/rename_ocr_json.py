#!/usr/bin/env python3
"""Migrate OCR JSON files + Zotero sibling attachments from `{hash}.json`
to `{pdf_basename}.{hash[:8]}.json`.

Three layers updated per JSON PaperFile:
1. Local cache file under ~/PaleoBytes/PaperMeister/ocr_json/ — renamed
2. DB `PaperFile.path` — updated to new name
3. Zotero attachment metadata (`data.filename`) — PATCHed via pyzotero
   so the sibling shows the pretty name in the Zotero GUI

For PDF hashes that have multiple PaperFile rows (same PDF imported into
several Zotero parents), the local cache file is copied per JSON sibling
so each PaperFile.path resolves 1:1 — content is identical, so duplicate
storage is harmless. The original `{hash}.json` cache file is removed
after the last copy.

Dry-run by default (preview); pass --execute to apply. Use --limit N to
test on a small batch. The script is idempotent: rows already in the new form are skipped.
"""

import argparse
import os
import re
import shutil
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Verify TLS against the OS trust store: the lab network re-signs with its own
# root CA, which certifi does not carry. Must run before any pyzotero call.
from papermeister.nettls import install_system_trust

install_system_trust()

from papermeister.database import init_db
from papermeister.models import PaperFile, PaperFolder
from papermeister.preferences import get_pref
from papermeister.text_extract import OCR_JSON_DIR, ocr_json_filename
from papermeister.zotero_client import ZoteroClient

# Legacy filename pattern: 64-hex hash + ".json"
LEGACY_RE = re.compile(r'^([0-9a-f]{64})\.json$')

# New filename pattern: anything ending with .{8-hex}.json
NEW_RE = re.compile(r'^.+\.([0-9a-f]{8})\.json$')


def log(msg):
    print(msg, flush=True)


def _collection_path(folder):
    """Walk Folder.parent up to root, return 'A › B › C' string."""
    parts = []
    cur = folder
    while cur is not None:
        parts.append(cur.name)
        cur = cur.parent
    parts.reverse()
    return ' › '.join(parts) if parts else '(no collection)'


def _parent_label(paper):
    """Short label: 'title' in [Collection › Path]. First collection only."""
    title = (paper.title or '(untitled)')[:60]
    pf_row = (
        PaperFolder.select(PaperFolder.folder)
        .where(PaperFolder.paper == paper)
        .first()
    )
    if pf_row is None:
        # Fallback: legacy Paper.folder
        if paper.folder_id is not None and paper.folder is not None:
            coll = _collection_path(paper.folder)
        else:
            coll = '(no collection)'
    else:
        coll = _collection_path(pf_row.folder)
    return f'"{title}" in [{coll}]'


def find_pairs(include_already_renamed=False):
    """Pair each JSON PaperFile with its source PDF PaperFile.

    Returns list of dicts: {
        json_pf:  the JSON PaperFile row,
        pdf_pf:   the corresponding PDF PaperFile (same paper, same hash),
        old_name: current JSON filename,
        new_name: target filename via ocr_json_filename(pdf_pf),
        phase:    'rename' (legacy → new, full processing) or
                  'retitle' (already in new form, Zotero PATCH only),
    }

    Skips:
        - JSON PaperFile not matching either pattern (skipped_unknown)
        - JSON whose source PDF can't be found on the same paper
        - PaperFile with empty hash (can't compute new name)

    When `include_already_renamed=False` (default), 'retitle' rows are
    skipped — only legacy hash-named JSONs are processed.
    """
    pairs = []
    skipped_unknown = 0
    skipped_no_pdf = 0
    skipped_retitle_disabled = 0

    json_pfs = list(
        PaperFile.select()
        .where(PaperFile.path.endswith('.json'))
    )

    for jpf in json_pfs:
        m_legacy = LEGACY_RE.match(jpf.path)
        if m_legacy:
            pdf_hash = m_legacy.group(1)
            pdf_pf = (
                PaperFile.select()
                .where(
                    (PaperFile.paper == jpf.paper)
                    & (PaperFile.hash == pdf_hash)
                    & (~PaperFile.path.endswith('.json'))
                )
                .first()
            )
            if pdf_pf is None:
                skipped_no_pdf += 1
                continue
            try:
                new_name = ocr_json_filename(pdf_pf)
            except ValueError:
                skipped_no_pdf += 1
                continue
            pairs.append({
                'json_pf': jpf,
                'pdf_pf': pdf_pf,
                'old_name': jpf.path,
                'new_name': new_name,
                'phase': 'rename',
            })
            continue

        # Not legacy — see if it matches our new pattern (was renamed before
        # we started writing data.title). Only included when caller asked.
        m_new = NEW_RE.match(jpf.path)
        if not m_new:
            skipped_unknown += 1
            continue

        if not include_already_renamed:
            skipped_retitle_disabled += 1
            continue

        # Find PDF whose hash[:8] matches this prefix on the same paper.
        short_hash = m_new.group(1)
        pdf_pf = (
            PaperFile.select()
            .where(
                (PaperFile.paper == jpf.paper)
                & (PaperFile.hash.startswith(short_hash))
                & (~PaperFile.path.endswith('.json'))
            )
            .first()
        )
        if pdf_pf is None:
            skipped_no_pdf += 1
            continue
        try:
            new_name = ocr_json_filename(pdf_pf)
        except ValueError:
            skipped_no_pdf += 1
            continue
        if new_name != jpf.path:
            # User manually picked a different name — don't second-guess.
            skipped_unknown += 1
            continue
        pairs.append({
            'json_pf': jpf,
            'pdf_pf': pdf_pf,
            'old_name': jpf.path,
            'new_name': new_name,
            'phase': 'retitle',
        })

    return pairs, skipped_unknown, skipped_no_pdf, skipped_retitle_disabled


def group_by_hash(pairs):
    """Group pairs by source PDF hash to identify 1:N cache cases."""
    by_hash = defaultdict(list)
    for p in pairs:
        by_hash[p['pdf_pf'].hash].append(p)
    return by_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply changes. Default is a dry-run preview.')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N JSON PaperFiles (0 = all).')
    parser.add_argument('--skip-zotero', action='store_true',
                        help='Only rename local cache + DB; skip Zotero PATCH.')
    parser.add_argument('--include-already-renamed', action='store_true',
                        help='Also re-PATCH JSON attachments whose filename is already '
                             'in new form (catches attachments migrated before we started '
                             'writing data.title). Zotero PATCH only; cache/DB unchanged.')
    parser.add_argument('--sleep', type=float, default=0.1,
                        help='Seconds to sleep between Zotero PATCH calls.')
    args = parser.parse_args()
    args.dry_run = not args.execute

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    # Credentials only needed for actual Zotero PATCH calls.
    if not args.dry_run and not args.skip_zotero and (not user_id or not api_key):
        log('Error: Zotero credentials not configured.')
        return 1

    log('Scanning DB for JSON PaperFiles…')
    pairs, skipped_unknown, skipped_no_pdf, skipped_retitle = find_pairs(
        include_already_renamed=args.include_already_renamed,
    )
    rename_count = sum(1 for p in pairs if p.get('phase') == 'rename')
    retitle_count = sum(1 for p in pairs if p.get('phase') == 'retitle')
    log(f'  legacy → rename:           {rename_count}')
    if args.include_already_renamed:
        log(f'  already-renamed retitle:   {retitle_count}')
    else:
        log(f'  already in new form:       {skipped_retitle} '
            f'(use --include-already-renamed to PATCH their title)')
    log(f'  no matching PDF sibling:   {skipped_no_pdf}')
    log(f'  unrecognized filenames:    {skipped_unknown}')

    if not pairs:
        log('Nothing to do.')
        return 0

    by_hash = group_by_hash(pairs)
    multi = sum(1 for ps in by_hash.values() if len(ps) > 1)
    log(f'  unique PDF hashes:         {len(by_hash)}')
    log(f'  hashes with 1:N cache:     {multi}')

    if args.limit > 0:
        pairs = pairs[:args.limit]
        log(f'  --limit {args.limit} → processing {len(pairs)}')
        by_hash = group_by_hash(pairs)

    # Pre-scan local cache directory
    if not os.path.isdir(OCR_JSON_DIR):
        log(f'Cache dir missing: {OCR_JSON_DIR}')
        return 1
    cache_files = set(os.listdir(OCR_JSON_DIR))

    cache_renames = 0
    cache_copies = 0
    cache_missing = 0
    db_updates = 0
    zotero_patches = 0
    zotero_unchanged = 0
    zotero_failures = 0
    name_collisions = 0

    client = None
    if not args.dry_run and not args.skip_zotero:
        client = ZoteroClient(user_id, api_key)

    log('')
    log('=== Plan preview (first 5 hashes) ===')
    for i, (h, plist) in enumerate(by_hash.items()):
        if i >= 5:
            break
        old_cache = f'{h}.json'
        cache_present = old_cache in cache_files
        log(f'  {h[:12]}… cache={"present" if cache_present else "MISSING"}, '
            f'{len(plist)} sibling(s):')
        for p in plist:
            log(f'    [{p["json_pf"].id}] {_parent_label(p["json_pf"].paper)}')
            log(f'         old: {p["old_name"]}')
            log(f'         new: {p["new_name"]}')
            log(f'         zot: {p["json_pf"].zotero_key or "(none)"}')

    if args.dry_run:
        log('')
        log('[DRY-RUN] No changes made.')
        return 0

    log('')
    log('=== Applying ===')
    total_pairs = len(pairs)
    done_pair = 0

    for h, plist in by_hash.items():
        # Split: 'rename' rows need cache work, 'retitle' rows don't.
        rename_rows = [p for p in plist if p.get('phase') == 'rename']
        old_cache_name = f'{h}.json'
        old_cache_path = os.path.join(OCR_JSON_DIR, old_cache_name)
        old_present = os.path.exists(old_cache_path) if rename_rows else False

        if rename_rows and not old_present:
            cache_missing += len(rename_rows)
            # Still update DB + Zotero so they don't keep referencing
            # the legacy name. Skip cache rename only.

        # Detect collisions before any write (target file already exists
        # but doesn't belong to this old cache).
        if rename_rows and old_present:
            for p in rename_rows:
                new_path = os.path.join(OCR_JSON_DIR, p['new_name'])
                if (
                    os.path.exists(new_path)
                    and os.path.abspath(new_path) != os.path.abspath(old_cache_path)
                ):
                    log(f'  COLLISION (skip): {p["new_name"]} already exists')
                    name_collisions += 1
                    p['_skip'] = True

        if rename_rows and old_present:
            # 1:1 → rename. 1:N → copy then remove original.
            active = [p for p in rename_rows if not p.get('_skip')]
            if not active:
                pass
            elif len(active) == 1:
                p = active[0]
                new_path = os.path.join(OCR_JSON_DIR, p['new_name'])
                if os.path.abspath(new_path) == os.path.abspath(old_cache_path):
                    pass
                else:
                    os.replace(old_cache_path, new_path)
                    cache_renames += 1
            else:
                for p in active:
                    new_path = os.path.join(OCR_JSON_DIR, p['new_name'])
                    if os.path.exists(new_path):
                        continue
                    shutil.copy2(old_cache_path, new_path)
                    cache_copies += 1
                try:
                    os.remove(old_cache_path)
                except OSError:
                    pass

        # DB + Zotero per sibling
        for p in plist:
            if p.get('_skip'):
                continue
            jpf = p['json_pf']
            new_name = p['new_name']
            phase = p.get('phase', 'rename')

            # Zotero PATCH (data.filename + data.title) — do this BEFORE the
            # DB update so an API failure leaves DB pointing at the old
            # (still valid in Zotero) filename. Re-running the script
            # will retry. pyzotero.update_item wants the full fetched item
            # dict back, not a hand-rolled PATCH body — wrong shape returns
            # "Invalid keys present in item 1: data".
            # We set both filename and title because Zotero shows `title`
            # in its GUI list view; keeping it in sync with filename matches
            # what manual attachment creation does.
            # If both already match new_name, skip the PATCH (fetch alone is
            # cheap; saves the round-trip + sleep on re-runs).
            if client is not None and jpf.zotero_key:
                try:
                    item = client._zot.item(jpf.zotero_key)
                    d = item.get('data') or {}
                    if d.get('filename') == new_name and d.get('title') == new_name:
                        zotero_unchanged += 1
                    else:
                        item['data']['filename'] = new_name
                        item['data']['title'] = new_name
                        # Zotero rejects the server-managed read-only key
                        # `lastRead` on write ("Invalid keys present in item 1:
                        # lastRead"). Some attachments carry it (last-opened
                        # timestamp); strip it before echoing the dict back.
                        # Leave other fields (e.g. numPages) intact.
                        item['data'].pop('lastRead', None)
                        client._zot.update_item(item)
                        zotero_patches += 1
                        if args.sleep > 0:
                            time.sleep(args.sleep)
                except Exception as e:
                    zotero_failures += 1
                    log(f'  Zotero PATCH FAIL [{jpf.zotero_key}]: {e}')
                    # Don't update DB if Zotero failed — keep them in sync
                    continue

            # DB update (only for 'rename' phase — retitle rows already match)
            if phase == 'rename':
                jpf.path = new_name
                jpf.save()
                db_updates += 1

            done_pair += 1
            if done_pair % 100 == 0 or done_pair <= 10:
                tag = '' if phase == 'rename' else ' (retitle)'
                log(f'  [{done_pair}/{total_pairs}]{tag} {_parent_label(jpf.paper)}')
                log(f'         → {new_name}  [{jpf.zotero_key or "no zot"}]')

    log('')
    log('=== Result ===')
    log(f'  cache renames:    {cache_renames}')
    log(f'  cache copies:     {cache_copies}')
    log(f'  cache missing:    {cache_missing}')
    log(f'  collisions:       {name_collisions}')
    log(f'  DB updates:       {db_updates}')
    log(f'  Zotero PATCHes:   {zotero_patches}')
    log(f'  Zotero unchanged: {zotero_unchanged}')
    log(f'  Zotero failures:  {zotero_failures}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
