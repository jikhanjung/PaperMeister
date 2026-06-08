#!/usr/bin/env python3
"""Backfill: reclassify existing non-PDF attachment PaperFiles to 'skipped'.

The extension gate (papermeister/file_utils.attachment_status) now assigns
non-PDF, non-JSON attachments status='skipped' at ingestion. This one-off
fixes rows created before the gate: supplementary data (.txt/.xls/.zip/.doc),
books (.djvu), etc. that got stuck as 'failed' or 'pending' because OCR can't
read them.

Targets: PaperFile where the file is neither a PDF nor a derived JSON sibling
and status in ('failed','pending') → 'skipped' (+ clear failure_reason).
JSON siblings (already 'processed') and PDFs are left untouched.

Dry-run by default. Pass --execute to apply.
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.file_utils import has_non_pdf_extension
from papermeister.models import PaperFile


def log(msg):
    print(msg, flush=True)


def find_targets():
    """failed/pending rows whose path has a concrete non-PDF extension.

    Uses has_non_pdf_extension so a not-yet-downloaded PDF whose path is still
    the bare Zotero key (no extension) is NOT reclassified — only files we can
    positively identify as non-PDF from the name.
    """
    rows = list(
        PaperFile.select().where(PaperFile.status.in_(['failed', 'pending']))
    )
    return [pf for pf in rows if has_non_pdf_extension(pf.path)]


def _ext(path):
    base = os.path.basename(path)
    return os.path.splitext(base)[1].lower() or '(none)'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true',
                        help='Apply the reclassification. Default is dry-run.')
    args = parser.parse_args()

    init_db()
    targets = find_targets()

    log(f'Non-PDF failed/pending attachments → skipped: {len(targets)}')
    if not targets:
        log('Nothing to reclassify.')
        return 0

    by_ext = Counter(_ext(pf.path) for pf in targets)
    log('  by extension:')
    for ext, n in by_ext.most_common():
        log(f'    {ext:8} {n}')
    by_status = Counter(pf.status for pf in targets)
    log(f'  by current status: {dict(by_status)}')

    log('')
    log('=== sample (first 15) ===')
    for pf in targets[:15]:
        log(f'  [{pf.id}] {pf.status:8} {os.path.basename(pf.path)[:60]}')

    if not args.execute:
        log('')
        log('[DRY-RUN] No changes. Re-run with --execute to apply.')
        return 0

    n = 0
    for pf in targets:
        pf.status = 'skipped'
        pf.failure_reason = ''
        pf.save()
        n += 1
    log('')
    log(f'=== Done: reclassified {n} → skipped ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
