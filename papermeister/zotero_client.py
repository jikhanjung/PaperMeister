"""Zotero API client wrapper using pyzotero."""

import json
import os
import re
import tempfile

from pyzotero import zotero


# Fallback year extractor for the rare item where meta.parsedDate is missing.
# Zotero's `data.date` is free-form: observed '2017', '2017-08-15', '08/2017',
# '8/2006', '1865', 'September 2018'. Zotero's server-side parser normally
# normalises all of these into meta.parsedDate, but we keep this as a safety
# net and for offline contexts.
# Range 1500–2099 covers everything from Linnaeus (1758) forward, sufficient
# for paleontology literature.
_YEAR_RE = re.compile(r'\b(1[5-9]\d{2}|20\d{2})\b')


def extract_year_from_date(date_str: str) -> int | None:
    """Best-effort extraction of a year from a free-form date string."""
    if not date_str:
        return None
    m = _YEAR_RE.search(date_str)
    return int(m.group(0)) if m else None

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

    def _parse_item_metadata(self, data, meta=None):
        """Extract metadata from a Zotero item.

        Accepts either the flat `data` dict (legacy) or `data` + `meta` (preferred).
        When `meta.parsedDate` is available (Zotero server normalises free-form
        `data.date` into YYYY or YYYY-MM-DD), it's used as the source for `year`.
        The raw `data.date` is always returned as `date` for lossless round-trip.
        """
        creators = data.get('creators', [])
        authors = []
        for c in creators:
            if c.get('creatorType') == 'author':
                # Single-field 'name' (e.g. institutional authors) is used as-is.
                # When firstName/lastName are separate, store as "Last, First"
                # so split_author_name() can parse unambiguously.
                name = c.get('name', '').strip()
                if not name:
                    last = c.get('lastName', '').strip()
                    first = c.get('firstName', '').strip()
                    name = f'{last}, {first}' if first and last else (last or first)
                if name:
                    authors.append(name)

        raw_date = data.get('date', '') or ''
        year = None
        if meta and meta.get('parsedDate'):
            year = extract_year_from_date(meta['parsedDate'])
        if year is None:
            year = extract_year_from_date(raw_date)

        return {
            'key': data['key'],
            'title': data.get('title', ''),
            'authors': authors,
            'date': raw_date,
            'year': year,
            'doi': data.get('DOI', ''),
            'journal': data.get('publicationTitle', ''),
            'collections': data.get('collections', []),
        }

    def get_collection_items(self, collection_key):
        """Return all items in a collection with attachment info.

        Single API call — attachments are matched by parentItem field.
        Picks up ALL attachment types (PDF, JSON, etc.) so re-sync can recreate
        every PaperFile relationship, including derived files like OCR JSONs.

        Returns list of dicts:
            {key, title, authors, date, year, doi, journal, collections,
             attachments: [{key, filename, content_type}]}
        Items without attachments have attachments=[].
        """
        raw = self._zot.everything(
            self._zot.collection_items(collection_key)
        )
        parent_items, atts_by_parent, standalone, _ = \
            self._classify_raw_items(raw)
        return self._build_results(parent_items, atts_by_parent, standalone)

    def _classify_raw_items(self, raw_items):
        """Separate raw Zotero API items into parent items, attachments, and standalone PDFs.

        Shared by get_collection_items() and get_all_items().
        Returns (parent_items_dict, attachments_by_parent, standalone_pdfs, orphan_parent_keys).
        orphan_parent_keys: attachment parent keys not present in this batch (incremental).
        """
        parent_items = {}
        attachments_by_parent = {}
        standalone_pdfs = []

        for it in raw_items:
            data = it['data']
            item_type = data.get('itemType', '')

            if item_type == 'attachment':
                content_type = data.get('contentType', '')
                parent_key = data.get('parentItem', '')
                if parent_key:
                    attachments_by_parent.setdefault(parent_key, []).append({
                        'key': data['key'],
                        'filename': data.get('filename', data['key']),
                        'content_type': content_type,
                    })
                else:
                    standalone_pdfs.append(data)
            elif item_type not in ('note', 'annotation'):
                parent_items[data['key']] = it

        orphan_parent_keys = set(attachments_by_parent) - set(parent_items)
        return parent_items, attachments_by_parent, standalone_pdfs, orphan_parent_keys

    def _build_results(self, parent_items, attachments_by_parent, standalone_pdfs):
        """Build result dicts from classified items."""
        results = []
        for item_key, full_item in parent_items.items():
            item = self._parse_item_metadata(
                full_item['data'], meta=full_item.get('meta', {}),
            )
            item['attachments'] = attachments_by_parent.get(item_key, [])
            results.append(item)

        for data in standalone_pdfs:
            filename = data.get('filename', f'{data["key"]}.pdf')
            content_type = data.get('contentType', '')
            title = data.get('title', '') or os.path.splitext(filename)[0]
            results.append({
                'key': data['key'],
                'title': title,
                'authors': [],
                'date': '',
                'year': None,
                'doi': '',
                'journal': '',
                'collections': data.get('collections', []),
                'attachments': [{
                    'key': data['key'],
                    'filename': filename,
                    'content_type': content_type,
                }],
            })
        return results

    def get_all_items(self, since=None):
        """Library-wide incremental item fetch.

        Args:
            since: library version (int). Pass None for full fetch.

        Returns:
            (items, orphan_attachments)
            - items: list of dicts, same format as get_collection_items()
            - orphan_attachments: dict {parent_zotero_key: [att_dicts]}
              for attachments whose parent item wasn't in this batch
              (common in incremental syncs)

        After calling this, use get_library_version() to store the new version.
        """
        kwargs = {}
        if since is not None:
            kwargs['since'] = since
        raw = self._zot.everything(self._zot.items(**kwargs))

        parent_items, atts_by_parent, standalone, orphan_keys = \
            self._classify_raw_items(raw)
        results = self._build_results(parent_items, atts_by_parent, standalone)

        orphan_atts = {k: atts_by_parent[k] for k in orphan_keys}
        return results, orphan_atts

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

    def upload_sibling_attachment(self, pdf_attachment_key, file_path):
        """Upload a file as a sibling attachment to the parent of an existing PDF attachment.

        Returns the new attachment's Zotero key, or None on failure.
        Raises if the PDF attachment is standalone (no parent item).
        """
        pdf_item = self._zot.item(pdf_attachment_key)
        parent_key = pdf_item['data'].get('parentItem', '')
        if not parent_key:
            raise RuntimeError(f'PDF attachment {pdf_attachment_key} is standalone (no parent item)')

        result = self._zot.attachment_simple([file_path], parentid=parent_key)
        if not isinstance(result, dict):
            return None
        successes = result.get('success', [])
        if successes:
            return successes[0].get('key', '')
        # Already uploaded (same md5) — pyzotero returns it in 'unchanged'
        unchanged = result.get('unchanged', [])
        if unchanged:
            return unchanged[0].get('key', '')
        return None
