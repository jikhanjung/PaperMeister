"""Give a PDF PaperFile the hash of the file it actually is.

The library's hash names the OCR cache (`<pdf>.<hash8>.json`), the Zotero
sibling JSON, the figure rows and their keys. When it is not the hash of the
PDF Zotero serves — paper 2388's row said 05ab917c, the file is 89140ce6
(2026-10-04) — the figure server refuses the upload as another edition and
the paper is skipped on every pass.

This rewrites the identity only when the OCR was read off the file as it is
now (its text is checked against the PDF's own text layer), so nothing has
to be OCR'd again:

- the PaperFile's hash, its figure rows' `file_hash` and the keys that embed it
- the OCR cache file's name
- the sibling JSON row's path, and the Zotero sibling's file (renamed by
  re-uploading the cache under the new name, key kept) when it exists

    python scripts/rehash_file.py --paper-file-ids 3179            # what would change
    python scripts/rehash_file.py --paper-file-ids 3179 --execute
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister import figure_lane, pdfdoc  # noqa: E402
from papermeister.database import init_db  # noqa: E402
from papermeister.models import Figure, PaperFile, db  # noqa: E402
from papermeister.nettls import install_system_trust  # noqa: E402
from papermeister.paths import OCR_JSON_DIR  # noqa: E402
from papermeister.text_extract import ocr_json_filename  # noqa: E402

install_system_trust()
sys.stdout.reconfigure(encoding='utf-8')

#: Share of the OCR's words a page's text layer must hold for the OCR to be of this file.
MIN_OVERLAP = 0.85
_WORD = re.compile(r'[^\W\d_]{5,}', re.UNICODE)
_TAG = re.compile(r'<[^>]+>')


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ocr_matches(pdf: str, pages: list[str]) -> tuple[bool, str]:
    """Is the cached OCR a reading of this PDF? Compared page by page against
    the text layer; a scan without one cannot be checked and is refused."""
    doc = pdfdoc.open_document(pdf)
    if len(doc) != len(pages):
        return False, f'{len(doc)} PDF pages, {len(pages)} OCR pages'
    shares = []
    for i, text in enumerate(pages):
        ocr = {w.lower() for w in _WORD.findall(_TAG.sub(' ', text or ''))}
        layer = {w.lower() for w in _WORD.findall(doc[i].get_textpage().get_text_range() or '')}
        if not ocr or not layer:
            continue
        shares.append(len(ocr & layer) / len(ocr))
    if not shares:
        return False, 'no text layer to check the OCR against'
    worst = min(shares)
    return worst >= MIN_OVERLAP, f'worst page overlap {worst:.2f} over {len(shares)} page(s)'


def rehash(pf: PaperFile, execute: bool) -> None:
    import json
    pdf = figure_lane.fetch_pdf(pf)
    if not pdf or not os.path.isfile(pdf):
        print(f'  file {pf.id}: no PDF on this machine')
        return
    new = sha256(pdf)
    old = pf.hash or ''
    if new == old:
        print(f'  file {pf.id}: hash already right ({new[:12]})')
        return
    other = PaperFile.get_or_none((PaperFile.hash == new) & (PaperFile.id != pf.id))
    if other is not None:
        print(f'  file {pf.id}: file {other.id} already has {new[:12]} — a duplicate; not changed')
        return
    old_cache = os.path.join(OCR_JSON_DIR, ocr_json_filename(pf))
    if not os.path.isfile(old_cache):
        print(f'  file {pf.id}: no OCR cache {os.path.basename(old_cache)}; nothing to keep — not changed')
        return
    with open(old_cache, encoding='utf-8') as f:
        data = json.load(f)
    pages = [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]
    ok, why = ocr_matches(pdf, pages)
    print(f'  file {pf.id}: {old[:12]} → {new[:12]}  ({why})')
    if not ok:
        print('    the OCR is not a reading of this file — re-OCR it instead; not changed')
        return
    old_name = os.path.basename(old_cache)
    new_name = old_name.replace(f'.{old[:8]}.json', f'.{new[:8]}.json')
    sibling = PaperFile.get_or_none((PaperFile.paper == pf.paper_id) & (PaperFile.path == old_name))
    rows = list(Figure.select().where(Figure.paper_file == pf.id))
    print(f'    cache {old_name} → {new_name}; {len(rows)} figure row(s); '
          f'sibling JSON {"row " + str(sibling.id) if sibling else "none"}')
    if not execute:
        return
    new_cache = os.path.join(OCR_JSON_DIR, new_name)
    with db.atomic():
        pf.hash = new
        pf.save()
        for row in rows:
            row.file_hash = new
            for name in ('link_key', 'panel_key', 'detect_key'):
                value = getattr(row, name) or ''
                setattr(row, name, value.replace(old, new).replace(old[:12], new[:12]))
            row.save()
        if sibling is not None:
            sibling.path = new_name
            sibling.save()
    os.replace(old_cache, new_cache)
    if sibling is not None and sibling.zotero_key:
        from papermeister.text_extract import push_sibling_json
        outcome = push_sibling_json(pf.paper_id, new_name, new_cache)
        print(f'    Zotero sibling: {outcome or "not pushed (upload of OCR JSON is off)"}')
        if outcome:
            # The upload renames the file; the title Zotero shows stays the old name.
            from papermeister.preferences import get_pref
            from papermeister.zotero_client import ZoteroClient
            zot = ZoteroClient(get_pref('zotero_user_id', ''), get_pref('zotero_api_key', ''))._zot
            item = zot.item(sibling.zotero_key)
            if item['data'].get('title') != new_name:
                item['data']['title'] = new_name
                zot.update_item(item)
    print('    done')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--paper-file-ids', required=True, help='comma-separated PaperFile ids (the PDFs)')
    ap.add_argument('--execute', action='store_true', help='write (default: show what would change)')
    args = ap.parse_args()
    init_db()
    for pid in [int(x) for x in args.paper_file_ids.split(',') if x.strip()]:
        pf = PaperFile.get_or_none(PaperFile.id == pid)
        if pf is None:
            print(f'  file {pid}: no such PaperFile')
            continue
        rehash(pf, args.execute)
    if not args.execute:
        print('\ndry run — add --execute to write')


if __name__ == '__main__':
    main()
