#!/usr/bin/env python3
"""P16 review: contact sheets of assembled figures, one HTML per stratum.

Runs the assembly judgement over the chosen papers' OCR cache (the same
`papermeister.figures` the store uses), groups every page with pictures by what
the rule did to it, draws a sample of each group on the rendered page, and
writes HTML a person can scroll: `index.html` links the strata and says what
to look for in each. Works before the figures are stored (identities are then
`file:page:bbox` keys) and after (identities are `#id`, which figure_curate
takes directly). Reads the library read-only; writes only under `--out`.

    python scripts/figure_contact_sheet.py --pilot tmp/p16_pilot.json
    python scripts/figure_contact_sheet.py --paper-ids 12,345 --all
    python scripts/figure_contact_sheet.py --pilot … --per-stratum 60 --out tmp/p16_review
"""
import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _CACHE_HASH, _print_utf8, load_pages, open_database, target_files

from papermeister import figure_sheet, figures, ocr_layout
from papermeister.figure_lane import local_pdf
from papermeister.paths import DATA_DIR, OCR_JSON_DIR

_print_utf8()


def collect(files, cache_dir: str) -> tuple[list[figure_sheet.Card], Counter, Counter]:
    """Every reviewable page of every file, classified."""
    cache_by_hash = {}
    for name in os.listdir(cache_dir):
        m = _CACHE_HASH.search(name)
        if m:
            cache_by_hash.setdefault(m.group(1), name)
    cards: list[figure_sheet.Card] = []
    totals: Counter = Counter()
    skipped: Counter = Counter()
    for pf in files:
        name = cache_by_hash.get(pf.hash[:8])
        pages = load_pages(os.path.join(cache_dir, name)) if name else None
        if not pages or not any(ocr_layout.is_structured(t) for t in pages):
            skipped['no structured OCR cache'] += 1
            continue
        pdf = local_pdf(pf)
        if pdf is None:
            skipped['PDF not on this machine'] += 1
        rows = figure_sheet.row_ids_for(pf.id)
        title = pf.paper.title or ''
        for assembly in figures.assemble_document(pages):
            stratum = figure_sheet.classify_page(assembly)
            if stratum is None:
                continue
            totals[stratum] += 1
            cards.append(figure_sheet.Card(
                paper_id=pf.paper_id, paper_file_id=pf.id, title=title, pdf_path=pdf,
                page=assembly.page, page_text=pages[assembly.page], assembly=assembly,
                stratum=stratum, row_ids=rows))
    return cards, totals, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids', help='comma-separated paper ids')
    parser.add_argument('--pilot', help='the pilot list written by assemble_figures.py --pilot-out')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    parser.add_argument('--out', default=os.path.join(DATA_DIR, 'tmp', 'p16_review'))
    parser.add_argument('--per-stratum', type=int, default=40, help='pages shown per stratum (default 40)')
    parser.add_argument('--all', action='store_true', help='show every page, no sampling')
    parser.add_argument('--seed', type=int, default=16)
    parser.add_argument('--dpi', type=int, default=72, help='page render resolution (default 72)')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')

    open_database(write=False)
    files = target_files(args)
    print(f'{len(files)} PDF file(s)')
    cards, totals, skipped = collect(files, args.cache_dir)
    for why, n in skipped.items():
        print(f'  {n} file(s): {why}')
    chosen = figure_sheet.sample_cards(cards, None if args.all else args.per_stratum, args.seed)
    print(f'{len(cards)} page(s) with pictures; showing {len(chosen)}')
    for name in figure_sheet.STRATUM_NAMES:
        if totals[name]:
            shown = sum(1 for c in chosen if c.stratum == name)
            print(f'  {name:<16} {shown:>4} of {totals[name]}')

    started = time.time()
    drawn = 0
    for index, card in enumerate(chosen, 1):
        figure_sheet.render_card(card, args.out, args.dpi)
        drawn += bool(card.image)
        if index % 25 == 0:
            print(f'  rendered {index}/{len(chosen)} ({time.time() - started:.0f}s)')
    files_written = figure_sheet.write_sheets(chosen, totals, args.out)
    print(f'{drawn} page(s) rendered in {time.time() - started:.0f}s; '
          f'{len(files_written)} sheet(s) → {os.path.join(args.out, "index.html")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
