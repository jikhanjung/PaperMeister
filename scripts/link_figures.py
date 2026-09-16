#!/usr/bin/env python3
"""P16 ②: the caption lane — for now, only what happens before the server.

Builds, for each chosen paper, what the caption stage would send: the
workspace (the OCR cache, page by page, keyed by its digest) and the request
(the figures due, the settled ones as context, the rule's hints). Nothing is
sent — ocrserver's side of this is not built yet (P02). `--dump` writes both
JSON bodies per paper so the request shape can be read, and the run prints
the sizes and why each figure is or is not due.

    python scripts/link_figures.py --pilot tmp/p16_pilot.json
    python scripts/link_figures.py --paper-ids 664,992 --dump tmp/p16_link
    python scripts/link_figures.py --pilot … --retry-errors

Reads the library read-only. Submitting, polling and applying arrive with the
server (client plan §6 H); `figure_link.validate_link_result` and
`apply_link` are already there for them.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assemble_figures import _CACHE_HASH, _print_utf8, load_pages, open_database, target_files

from papermeister import figure_link, figure_prompts, ocr_layout
from papermeister.paths import OCR_JSON_DIR

_print_utf8()

PROMPT = figure_prompts.load('link')
PROMPT_VERSION = PROMPT['version']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--paper-ids')
    parser.add_argument('--pilot')
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    parser.add_argument('--dump', help='write workspace_<id>.json and link_<id>.json per paper here')
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    if not args.paper_ids and not args.pilot:
        parser.error('give --paper-ids or --pilot')

    open_database(write=False)
    from papermeister.preferences import get_client_id
    client_id = get_client_id()
    cache_by_hash = {}
    for name in os.listdir(args.cache_dir):
        m = _CACHE_HASH.search(name)
        if m:
            cache_by_hash.setdefault(m.group(1), name)
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)

    totals: Counter = Counter()
    sizes: list[tuple[int, int, int]] = []
    for pf in target_files(args):
        name = cache_by_hash.get(pf.hash[:8])
        pages = load_pages(os.path.join(args.cache_dir, name)) if name else None
        if not pages or not any(ocr_layout.is_structured(t) for t in pages):
            totals['no cache'] += 1
            continue
        digest = figure_link.ocr_digest(pages)
        targets = figure_link.link_targets(pf, digest, PROMPT_VERSION, args.retry_errors)
        for _, why in targets.excluded:
            totals[f'excluded: {why}'] += 1
        totals['due'] += len(targets.due)
        totals['context'] += len(targets.context)
        if not targets.due:
            totals['papers with nothing due'] += 1
            continue
        totals['papers due'] += 1
        request = figure_link.link_payload(pf, pages, targets, digest, client_id)
        request['prompt'] = PROMPT
        workspace = figure_link.workspace_payload(pf, pages)
        req_bytes = len(json.dumps(request, ensure_ascii=False).encode('utf-8'))
        ws_bytes = len(json.dumps(workspace, ensure_ascii=False).encode('utf-8'))
        sizes.append((len(pages), req_bytes, ws_bytes))
        print(f'  paper {pf.paper_id:>6}  {len(pages):>4} pages  due {len(targets.due):>3}  context {len(targets.context):>2}  '
              f'request {req_bytes / 1024:6.1f} KB  workspace {ws_bytes / 1024:7.1f} KB  '
              f"hints plate {len(request['hints']['plate_pages'])} expl {len(request['hints']['explanation_pages'])}  "
              f'{os.path.basename(pf.path)[:60]}')
        if args.dump:
            with open(os.path.join(args.dump, f'link_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump(request, f, ensure_ascii=False, indent=1)
            with open(os.path.join(args.dump, f'workspace_{pf.id}.json'), 'w', encoding='utf-8') as f:
                json.dump(workspace, f, ensure_ascii=False)

    print()
    for key, n in sorted(totals.items()):
        print(f'  {key:<32} {n:>6}')
    if sizes:
        req = sorted(s[1] for s in sizes)
        ws = sorted(s[2] for s in sizes)
        print(f'  request KB   median {req[len(req) // 2] / 1024:.1f}  max {req[-1] / 1024:.1f}  '
              f'total {sum(req) / 1024 / 1024:.1f} MB')
        print(f'  workspace KB median {ws[len(ws) // 2] / 1024:.1f}  max {ws[-1] / 1024:.1f}  '
              f'total {sum(ws) / 1024 / 1024:.1f} MB')
    print('Nothing sent: the server side of ② is not built yet.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
