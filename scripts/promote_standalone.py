#!/usr/bin/env python3
"""Promote standalone PDFs to proper Zotero items using LLM-extracted biblio.

For each standalone PDF with a high-confidence PaperBiblio extraction:
  1. Create a Zotero parent item (in the same collection) using the LLM data
  2. Move the existing PDF attachment to be a child of the new parent
  3. Upload the OCR JSON as another child attachment
  4. Update DB: Paper.zotero_key/title/year/journal/doi + Authors

Default is dry-run. Use --apply to actually perform Zotero writes.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Folder, Paper, PaperFile, PaperBiblio, db
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient
from papermeister.ingestion import hash_file
from papermeister.biblio import OCR_JSON_DIR

ITEM_TYPE_MAP = {
    'article': 'journalArticle',
    'book': 'book',
    'chapter': 'bookSection',
    'thesis': 'thesis',
    'report': 'report',
    'unknown': 'document',
}


def _is_cjk_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x3400 <= cp <= 0x9FFF       # CJK Unified Ideographs
        or 0xAC00 <= cp <= 0xD7AF    # Hangul Syllables
        or 0x3040 <= cp <= 0x30FF    # Hiragana/Katakana
    )


def split_author_name(name: str):
    """Split 'First Middle Last' or 'Last, First' into Zotero firstName/lastName.

    CJK heuristics for unspaced names:
      - 4 CJK chars: 2 surname + 2 given (typical Japanese/Chinese)
      - 3 CJK chars: 1 surname + 2 given (typical Korean/Chinese)
    """
    name = name.strip()
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        if len(parts) == 2 and parts[1]:
            return parts[1], parts[0]
        return '', parts[0]

    tokens = name.split()
    if len(tokens) == 1:
        single = tokens[0]
        # CJK unspaced name
        if all(_is_cjk_char(c) for c in single):
            if len(single) == 4:
                return single[2:], single[:2]
            if len(single) == 3:
                return single[1:], single[:1]
        return '', single
    return ' '.join(tokens[:-1]), tokens[-1]


def build_creators(authors):
    out = []
    for a in authors or []:
        first, last = split_author_name(a)
        out.append({'creatorType': 'author', 'firstName': first, 'lastName': last})
    return out


def build_parent_item_payload(biblio, collection_keys):
    item_type = ITEM_TYPE_MAP.get(biblio.doc_type or 'unknown', 'document')
    payload = {
        'itemType': item_type,
        'title': biblio.title or '',
        'creators': build_creators(json.loads(biblio.authors_json or '[]')),
        'date': str(biblio.year) if biblio.year else '',
        'DOI': biblio.doi or '',
        'abstractNote': biblio.abstract or '',
        'language': biblio.language or '',
        'collections': collection_keys,
        'tags': [],
        'relations': {},
    }
    # Type-specific journal/publisher field
    if item_type == 'journalArticle':
        payload['publicationTitle'] = biblio.journal or ''
    elif item_type == 'bookSection':
        payload['bookTitle'] = biblio.journal or ''
    elif item_type == 'book':
        payload['publisher'] = biblio.journal or ''
    elif item_type == 'report':
        payload['institution'] = biblio.journal or ''
    elif item_type == 'thesis':
        payload['university'] = biblio.journal or ''
    return payload


def fetch_candidates():
    """Standalone PDFs (Paper.zotero_key == PaperFile.zotero_key) with high-confidence biblio."""
    rows = []
    q = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
            & (Paper.zotero_key == PaperFile.zotero_key)
        )
    )
    for pf in q:
        p = pf.paper
        b = (
            PaperBiblio.select()
            .where((PaperBiblio.paper == p) & (PaperBiblio.file_hash == pf.hash))
            .order_by(PaperBiblio.extracted_at.desc())
            .first()
        )
        if not b or b.confidence != 'high':
            continue
        if not b.title:
            continue  # nothing to promote with
        rows.append((p, pf, b))
    return rows


def collection_key_for(paper):
    folder = paper.folder
    if folder and folder.zotero_key:
        return folder.zotero_key
    return ''


def update_db_after_promote(paper, biblio, new_parent_key):
    with db.atomic():
        # Replace authors with LLM authors
        Author.delete().where(Author.paper == paper).execute()
        authors = json.loads(biblio.authors_json or '[]')
        for i, name in enumerate(authors):
            Author.create(paper=paper, name=name, order=i)
        # Update paper fields
        paper.title = biblio.title or paper.title
        paper.year = biblio.year if biblio.year else paper.year
        paper.journal = biblio.journal or paper.journal
        paper.doi = biblio.doi or paper.doi
        paper.zotero_key = new_parent_key
        paper.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Actually perform Zotero writes (default is dry-run)')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.')
        return 1

    client = ZoteroClient(user_id, api_key)
    zot = client._zot  # raw pyzotero handle

    candidates = fetch_candidates()
    print(f'Candidates (high-confidence standalone): {len(candidates)}')
    if args.limit > 0:
        candidates = candidates[:args.limit]
        print(f'  --limit {args.limit} → {len(candidates)}')

    if not args.apply:
        print('\n*** DRY RUN — no Zotero changes ***\n')

    ok = 0
    skipped = 0
    failed = 0

    for i, (p, pf, b) in enumerate(candidates, 1):
        coll = collection_key_for(p)
        if not coll:
            print(f'[{i}] SKIP pid={p.id}: no collection')
            skipped += 1
            continue

        payload = build_parent_item_payload(b, [coll])
        print(f'\n[{i}/{len(candidates)}] pid={p.id}')
        print(f'    collection={coll}')
        print(f'    title={payload["title"][:80]}')
        print(f'    type={payload["itemType"]}  date={payload["date"]}  doi={payload.get("DOI") or "—"}')
        print(f'    creators={[(c["firstName"], c["lastName"]) for c in payload["creators"][:5]]}')

        if not args.apply:
            ok += 1
            continue

        try:
            # 1. Create parent item
            resp = zot.create_items([payload])
            successes = resp.get('successful', {}) if isinstance(resp, dict) else {}
            if not successes:
                print(f'    ✗ create_items failed: {resp}')
                failed += 1
                continue
            new_parent_key = list(successes.values())[0]['key']
            print(f'    ✓ created parent {new_parent_key}')

            # 2. Move PDF attachment under new parent
            pdf_item = zot.item(pf.zotero_key)
            pdf_data = pdf_item['data']
            pdf_data['parentItem'] = new_parent_key
            # Remove from collections (children inherit from parent)
            pdf_data['collections'] = []
            zot.update_item(pdf_data)
            print(f'    ✓ moved PDF {pf.zotero_key} → child of {new_parent_key}')

            # 3. Upload OCR JSON as additional child (if not already)
            json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
            if os.path.exists(json_path):
                json_key = client.upload_sibling_attachment(pf.zotero_key, json_path)
                if json_key:
                    print(f'    ✓ uploaded OCR JSON → {json_key}')
                    # Track JSON as PaperFile too (idempotent)
                    existing = (PaperFile.select()
                                .where((PaperFile.paper == p)
                                       & (PaperFile.path.endswith('.json'))).first())
                    if not existing:
                        PaperFile.create(
                            paper=p, path=os.path.basename(json_path),
                            hash=hash_file(json_path), status='processed',
                            zotero_key=json_key,
                        )

            # 4. DB update
            update_db_after_promote(p, b, new_parent_key)
            print(f'    ✓ DB updated')
            ok += 1

        except Exception as e:
            print(f'    ✗ ERROR: {e}')
            failed += 1

    print(f'\n=== Summary ===')
    print(f'  ok:      {ok}')
    print(f'  skipped: {skipped}')
    print(f'  failed:  {failed}')
    if not args.apply:
        print('\nThis was a DRY RUN. Re-run with --apply to perform Zotero writes.')


if __name__ == '__main__':
    main()
