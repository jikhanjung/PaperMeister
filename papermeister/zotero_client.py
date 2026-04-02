"""Zotero API client wrapper using pyzotero."""

import json
import os
import tempfile

from pyzotero import zotero

COLLECTIONS_CACHE = os.path.join(
    os.path.expanduser('~'), '.papermeister', 'zotero_collections.json'
)


def load_cached_collections():
    """Load collections from cache file. Returns list or None."""
    if os.path.exists(COLLECTIONS_CACHE):
        try:
            with open(COLLECTIONS_CACHE, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_collections_cache(collections):
    """Save collections to cache file."""
    os.makedirs(os.path.dirname(COLLECTIONS_CACHE), exist_ok=True)
    with open(COLLECTIONS_CACHE, 'w', encoding='utf-8') as f:
        json.dump(collections, f, ensure_ascii=False, indent=2)


class ZoteroClient:
    """Thin wrapper around pyzotero for PaperMeister."""

    def __init__(self, user_id, api_key):
        self.user_id = user_id
        self.api_key = api_key
        self._zot = zotero.Zotero(user_id, 'user', api_key)

    def test_connection(self):
        """Return True if credentials are valid."""
        try:
            self._zot.key_info()
            return True
        except Exception:
            return False

    def get_library_version(self):
        """Get the current library version number (int)."""
        return self._zot.last_modified_version()

    def get_collections(self, since=None):
        """Return all collections as list of dicts with key, name, parent_key.

        If since= is given, only returns collections modified after that library version.
        Results are automatically saved to cache.
        """
        if since is not None:
            changed = self._zot.collection_versions(since=since)
            if not changed:
                return None  # nothing changed
            # Fetch only changed collections
            raw = []
            for key in changed:
                try:
                    col = self._zot.collection(key)
                    raw.append(col)
                except Exception:
                    pass
        else:
            raw = self._zot.everything(self._zot.collections())

        results = []
        for col in raw:
            data = col['data']
            results.append({
                'key': data['key'],
                'name': data['name'],
                'parent_key': data.get('parentCollection') or '',
            })
        results.sort(key=lambda c: c['name'].lower())

        if since is None:
            # Full fetch — overwrite cache
            save_collections_cache(results)

        return results

    def _parse_item_metadata(self, data):
        """Extract metadata from a Zotero item data dict."""
        creators = data.get('creators', [])
        authors = []
        for c in creators:
            if c.get('creatorType') == 'author':
                name = c.get('name') or f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
                if name:
                    authors.append(name)

        year = None
        date_str = data.get('date', '')
        if date_str:
            try:
                year = int(date_str[:4])
                if not (1900 <= year <= 2100):
                    year = None
            except (ValueError, IndexError):
                pass

        return {
            'key': data['key'],
            'title': data.get('title', ''),
            'authors': authors,
            'year': year,
            'doi': data.get('DOI', ''),
            'journal': data.get('publicationTitle', ''),
        }

    def get_collection_items(self, collection_key):
        """Return all items in a collection with PDF attachment info.

        Single API call — attachments are matched by parentItem field.
        Returns list of dicts:
            {key, title, authors, year, doi, journal, attachments: [{key, filename}]}
        Items without PDF attachments have attachments=[].
        """
        all_items = self._zot.everything(
            self._zot.collection_items(collection_key)
        )

        parent_items = {}
        pdf_attachments = {}
        standalone_pdfs = []

        for it in all_items:
            data = it['data']
            item_type = data.get('itemType', '')

            if item_type == 'attachment':
                if data.get('contentType') == 'application/pdf':
                    parent_key = data.get('parentItem', '')
                    if parent_key:
                        pdf_attachments.setdefault(parent_key, []).append({
                            'key': data['key'],
                            'filename': data.get('filename', f'{data["key"]}.pdf'),
                        })
                    else:
                        standalone_pdfs.append(data)
            elif item_type != 'note':
                parent_items[data['key']] = data

        results = []
        for item_key, data in parent_items.items():
            item = self._parse_item_metadata(data)
            item['attachments'] = pdf_attachments.get(item_key, [])
            results.append(item)

        # Standalone PDFs (no parent item) — create as their own item
        for data in standalone_pdfs:
            filename = data.get('filename', f'{data["key"]}.pdf')
            title = data.get('title', '') or os.path.splitext(filename)[0]
            results.append({
                'key': data['key'],
                'title': title,
                'authors': [],
                'year': None,
                'doi': '',
                'journal': '',
                'attachments': [{
                    'key': data['key'],
                    'filename': filename,
                }],
            })

        return results

    def download_attachment(self, attachment_key):
        """Download a PDF attachment to a temp file. Returns file path.

        Caller is responsible for deleting the file.
        """
        dest_dir = os.path.join(os.path.expanduser('~'), '.papermeister', 'tmp')
        os.makedirs(dest_dir, exist_ok=True)

        # Use file() to get raw binary content instead of dump()
        content = self._zot.file(attachment_key)

        out_path = os.path.join(dest_dir, f'{attachment_key}.pdf')
        with open(out_path, 'wb') as f:
            f.write(content)

        return out_path
