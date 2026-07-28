#!/usr/bin/env python3
"""Rename leftover legacy OCR-cache files `{sha256}.json` to the new
`{pdf_basename}.{hash[:8]}.json` convention.

The session-42 migration (scripts/rename_ocr_json.py) renamed cache files by
pairing JSON *PaperFile rows* with PDFs. Cache files whose OCR JSON was never
registered as a PaperFile (e.g. never uploaded to Zotero) had no pair, so they
kept the old full-hash name. `biblio.load_ocr_pages` globs for `*.{hash[:8]}.json`
and so can't find them → "No OCR pages found" → biblio extraction fails for those
papers even though the OCR cache is right there.

This finds those files in ~/PaleoBytes/PaperMeister/ocr_json/, matches each hash to a PDF
PaperFile to derive the basename, and renames. Cache-only — no DB or Zotero
changes. Idempotent; dry-run by default.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import PaperFile
from papermeister.text_extract import OCR_JSON_DIR, ocr_json_filename

LEGACY_RE = re.compile(r'^([0-9a-f]{64})\.json$')


def log(msg):
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply renames. Default is dry-run.')
    args = parser.parse_args()

    init_db()

    if not os.path.isdir(OCR_JSON_DIR):
        log(f'Cache dir not found: {OCR_JSON_DIR}')
        return 1

    legacy = [f for f in os.listdir(OCR_JSON_DIR) if LEGACY_RE.match(f)]
    log(f'Legacy {{64hex}}.json cache files: {len(legacy)}')
    if not legacy:
        log('Nothing to do.')
        return 0

    renamed = no_pdf = collision = 0
    log('')
    for fname in sorted(legacy):
        file_hash = LEGACY_RE.match(fname).group(1)
        pdf = (
            PaperFile.select()
            .where((PaperFile.hash == file_hash) & (~PaperFile.path.endswith('.json')))
            .order_by(PaperFile.id)
            .first()
        )
        if pdf is None:
            no_pdf += 1
            log(f'  SKIP (no PDF for hash): {file_hash[:12]}…')
            continue
        try:
            new_name = ocr_json_filename(pdf)
        except ValueError:
            no_pdf += 1
            continue

        src = os.path.join(OCR_JSON_DIR, fname)
        dst = os.path.join(OCR_JSON_DIR, new_name)
        if os.path.exists(dst):
            collision += 1
            log(f'  SKIP (target exists): {new_name}')
            continue

        log(f'  {fname[:16]}…  →  {new_name}')
        if args.execute:
            os.replace(src, dst)
            renamed += 1

    log('')
    if args.execute:
        log(f'=== Done: renamed {renamed}, no-pdf {no_pdf}, collisions {collision} ===')
    else:
        log(f'[DRY-RUN] would rename {len(legacy) - no_pdf - collision} '
            f'(no-pdf {no_pdf}, collisions {collision}). Re-run with --execute.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
