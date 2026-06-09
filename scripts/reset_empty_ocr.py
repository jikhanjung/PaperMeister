#!/usr/bin/env python3
"""Reset papers whose OCR produced an empty result so they can be re-OCR'd.

Some PDFs were marked status='processed' even though the OCR server returned
0 pages (unparseable / image-only). They have no passages and a tiny 0-page
cache JSON, so biblio extraction later fails with "No OCR pages found".

For each such paper this deletes the empty local cache file and resets the PDF
PaperFile to status='pending', so the next Process re-runs OCR. (Going forward,
text_extract marks an empty OCR as 'failed' instead of 'processed', so this is
a one-off cleanup for the existing rows.)

Dry-run by default; pass --execute to apply.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import PaperFile, Passage
from papermeister.text_extract import OCR_JSON_DIR


def log(msg):
    print(msg, flush=True)


def _cache_is_empty(file_hash: str) -> tuple[bool, str | None]:
    """Return (is_empty, path) for the cache matching this hash, if found."""
    matches = glob.glob(os.path.join(OCR_JSON_DIR, f'*.{file_hash[:8]}.json'))
    legacy = os.path.join(OCR_JSON_DIR, f'{file_hash}.json')
    if os.path.exists(legacy):
        matches.append(legacy)
    for path in matches:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        pages = data.get('pages') or []
        if not any((p.get('markdown') or p.get('text') or '').strip() for p in pages):
            return True, path
    return False, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply the reset. Default is a dry-run preview.')
    args = parser.parse_args()

    init_db()

    # processed PDFs whose paper has zero passages
    pdfs = list(
        PaperFile.select().where(
            (~PaperFile.path.endswith('.json'))
            & (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
        )
    )
    targets = []
    for pf in pdfs:
        if Passage.select().where(Passage.paper == pf.paper).exists():
            continue
        empty, cache_path = _cache_is_empty(pf.hash)
        targets.append((pf, cache_path))

    log(f'processed PDFs with empty OCR (0 passages): {len(targets)}')
    if not targets:
        log('Nothing to reset.')
        return 0

    log('')
    for pf, cache_path in targets:
        log(f'  [{pf.id}] paper={pf.paper_id} {os.path.basename(pf.path)[:55]}')
        log(f'        cache: {os.path.basename(cache_path) if cache_path else "(none/non-empty)"}')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to delete empty caches + reset to pending.')
        return 0

    reset = removed = 0
    for pf, cache_path in targets:
        if cache_path and os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                removed += 1
            except OSError as e:
                log(f'  cache remove failed [{pf.id}]: {e}')
        pf.status = 'pending'
        pf.failure_reason = ''
        pf.save()
        reset += 1
    log('')
    log(f'=== Done: reset {reset} to pending, removed {removed} empty cache files ===')
    log('Now re-run Process (folder or single) to re-OCR them.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
