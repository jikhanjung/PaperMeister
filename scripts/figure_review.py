#!/usr/bin/env python3
"""P16: what is left to do on the figures — five counts that together mean done.

    python scripts/figure_review.py --pilot tmp/p16_pilot.json
    python scripts/figure_review.py --paper-ids 664,992

Reads the library read-only. The counts come from the same judgements the
lanes use, so this and the lanes cannot disagree.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _CACHE_HASH, _print_utf8, load_pages, open_database, target_files
from link_figures import PROMPT_VERSION as LINK_PROMPT
from split_panels import PROMPT_VERSION as PANELS_PROMPT

from papermeister import figure_review
from papermeister.paths import OCR_JSON_DIR

_print_utf8()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')
    open_database(write=False)
    cache_by_hash = {}
    for name in os.listdir(args.cache_dir):
        m = _CACHE_HASH.search(name)
        if m:
            cache_by_hash.setdefault(m.group(1), name)
    total = figure_review.Review()
    files = 0
    for pf in target_files(args):
        name = cache_by_hash.get(pf.hash[:8])
        pages = load_pages(os.path.join(args.cache_dir, name)) if name else None
        if not pages:
            continue
        total.update(figure_review.review_file(pf, pages, LINK_PROMPT, PANELS_PROMPT))
        files += 1
    print(figure_review.format_review(total, files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
