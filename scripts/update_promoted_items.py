#!/usr/bin/env python3
"""Update existing Zotero parent items in-place from a PaperBiblio extraction.

Use case: previous LLM extractions misclassified some PDFs (e.g., journal-issue
covers labeled as articles). After re-extracting with the vision pass, this
script overwrites the wrong parent items in Zotero AND updates DB Paper rows.

The PDF/JSON child relationships are preserved.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Paper, PaperBiblio, db
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient
from papermeister.models import PaperFile
from scripts.promote_standalone import (
    build_creators, build_parent_item_payload, ITEM_TYPE_MAP, collection_key_for,
)
from papermeister.ingestion import hash_file
from papermeister.biblio import OCR_JSON_DIR

# journal_issue → document (Zotero has no journalIssue type)
ITEM_TYPE_MAP_EXT = {
    **ITEM_TYPE_MAP,
    'journal_issue': 'document',
}


def build_update_payload(item_data, biblio, zot):
    """Build a payload for the new itemType using its template, preserving key/version."""
    new_type = ITEM_TYPE_MAP_EXT.get(biblio.doc_type or 'unknown', 'document')
    template = zot.item_template(new_type)

    # Start from a clean template, then preserve item identity + collections + parents
    payload = dict(template)
    payload['key'] = item_data['key']
    payload['version'] = item_data['version']
    if 'collections' in item_data:
        payload['collections'] = item_data['collections']
    if 'parentItem' in item_data:
        payload['parentItem'] = item_data['parentItem']
    if 'tags' in item_data:
        payload['tags'] = item_data['tags']
    if 'relations' in item_data:
        payload['relations'] = item_data['relations']

    payload['title'] = biblio.title or item_data.get('title', '')
    payload['date'] = str(biblio.year) if biblio.year else item_data.get('date', '')
    if 'language' in payload:
        payload['language'] = biblio.language or item_data.get('language', '')
    if 'abstractNote' in payload:
        payload['abstractNote'] = biblio.abstract or item_data.get('abstractNote', '')
    if 'DOI' in payload:
        payload['DOI'] = biblio.doi or item_data.get('DOI', '')

    authors = json.loads(biblio.authors_json or '[]')
    payload['creators'] = build_creators(authors)
    item_data = payload

    # Type-specific publication field
    if new_type == 'journalArticle':
        item_data['publicationTitle'] = biblio.journal or ''
    elif new_type == 'bookSection':
        item_data['bookTitle'] = biblio.journal or ''
    elif new_type == 'book':
        item_data['publisher'] = biblio.journal or ''
    elif new_type == 'report':
        item_data['institution'] = biblio.journal or ''
    elif new_type == 'thesis':
        item_data['university'] = biblio.journal or ''
    elif new_type == 'document':
        # 'document' has 'publisher' field; use it for the journal name
        item_data['publisher'] = biblio.journal or ''

    # Stash structured extras (issue, TOC) into 'extra' field where supported
    extras = []
    if biblio.doc_type == 'journal_issue':
        extras.append('Type: journalIssue')
    if biblio.notes:
        # extract any "issue=..." we previously stuffed there
        notes = biblio.notes
        if '|' in notes:
            extras.append(f'Notes: {notes.split("|")[0].strip()}')
        else:
            extras.append(f'Notes: {notes}')
    if extras:
        item_data['extra'] = '\n'.join(extras)

    return item_data, new_type


def update_db_paper(paper, biblio):
    with db.atomic():
        Author.delete().where(Author.paper == paper).execute()
        for i, name in enumerate(json.loads(biblio.authors_json or '[]')):
            Author.create(paper=paper, name=name, order=i)
        if biblio.title:
            paper.title = biblio.title
        if biblio.year:
            paper.year = biblio.year
        if biblio.journal:
            paper.journal = biblio.journal
        if biblio.doi:
            paper.doi = biblio.doi
        paper.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, help='PaperBiblio.source label, e.g. llm-sonnet-vision')
    parser.add_argument('--paper-ids', default='', help='Optional comma-separated paper IDs')
    parser.add_argument('--apply', action='store_true', help='Actually update Zotero (default: dry-run)')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.')
        return 1
    client = ZoteroClient(user_id, api_key)
    zot = client._zot

    # Find latest biblio per paper for the given source
    q = (PaperBiblio.select()
         .where(PaperBiblio.source == args.source)
         .order_by(PaperBiblio.paper, PaperBiblio.extracted_at.desc()))

    if args.paper_ids:
        ids = [int(x) for x in args.paper_ids.split(',')]
        q = q.where(PaperBiblio.paper.in_(ids))

    seen = set()
    targets = []
    for b in q:
        if b.paper_id in seen:
            continue
        seen.add(b.paper_id)
        targets.append(b)

    if args.limit > 0:
        targets = targets[:args.limit]

    print(f'Targets: {len(targets)}')
    if not args.apply:
        print('*** DRY RUN — no Zotero changes ***\n')

    ok = 0
    failed = 0
    skipped = 0

    for i, b in enumerate(targets, 1):
        paper = b.paper
        if not paper.zotero_key:
            print(f'[{i}] pid={paper.id} SKIP: no parent zotero_key')
            skipped += 1
            continue

        print(f'\n[{i}/{len(targets)}] pid={paper.id} parent={paper.zotero_key}')
        print(f'    new title: {b.title[:80]}')
        print(f'    new type:  {b.doc_type} → {ITEM_TYPE_MAP_EXT.get(b.doc_type, "document")}')
        print(f'    new year:  {b.year}')

        if not args.apply:
            ok += 1
            continue

        try:
            item = zot.item(paper.zotero_key)
            current_type = item['data'].get('itemType', '')

            if current_type == 'attachment':
                # Not promoted yet → create new parent and move PDF/JSON children
                pf = (PaperFile.select()
                      .where((PaperFile.paper == paper)
                             & (PaperFile.status == 'processed')
                             & (~PaperFile.path.endswith('.json')))
                      .first())
                if not pf:
                    print(f'    ✗ no PDF PaperFile to promote')
                    failed += 1
                    continue
                coll = collection_key_for(paper)
                payload = build_parent_item_payload(b, [coll] if coll else [])
                # Override itemType for journal_issue
                payload['itemType'] = ITEM_TYPE_MAP_EXT.get(b.doc_type or 'unknown', 'document')
                if payload['itemType'] == 'document':
                    payload.pop('publicationTitle', None)
                    payload['publisher'] = b.journal or ''
                resp = zot.create_items([payload])
                successes = resp.get('successful', {}) if isinstance(resp, dict) else {}
                if not successes:
                    print(f'    ✗ create_items failed: {resp}')
                    failed += 1
                    continue
                new_parent_key = list(successes.values())[0]['key']
                print(f'    ✓ created parent {new_parent_key}')

                # Move PDF child
                pdf_item = zot.item(pf.zotero_key)
                pdf_data = pdf_item['data']
                pdf_data['parentItem'] = new_parent_key
                pdf_data['collections'] = []
                zot.update_item(pdf_data)
                print(f'    ✓ moved PDF {pf.zotero_key}')

                # Upload OCR JSON
                json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
                if os.path.exists(json_path):
                    json_key = client.upload_sibling_attachment(pf.zotero_key, json_path)
                    if json_key:
                        existing_json = (PaperFile.select()
                                         .where((PaperFile.paper == paper)
                                                & (PaperFile.path.endswith('.json')))
                                         .first())
                        if not existing_json:
                            PaperFile.create(
                                paper=paper, path=os.path.basename(json_path),
                                hash=hash_file(json_path), status='processed',
                                zotero_key=json_key,
                            )
                        print(f'    ✓ uploaded OCR JSON {json_key}')

                paper.zotero_key = new_parent_key
                paper.save()
                update_db_paper(paper, b)
                ok += 1
            else:
                # Already a parent item → in-place update
                payload, new_type = build_update_payload(item['data'], b, zot)
                result = zot.update_item(payload)
                if result is True or (isinstance(result, dict) and not result.get('failed')):
                    update_db_paper(paper, b)
                    print(f'    ✓ updated in place')
                    ok += 1
                else:
                    print(f'    ✗ update returned: {result}')
                    failed += 1
        except Exception as e:
            print(f'    ✗ ERROR: {e}')
            failed += 1

    print(f'\n=== Summary ===')
    print(f'  ok:      {ok}')
    print(f'  skipped: {skipped}')
    print(f'  failed:  {failed}')
    if not args.apply:
        print('\nDry run only. Re-run with --apply to perform Zotero updates.')


if __name__ == '__main__':
    main()
