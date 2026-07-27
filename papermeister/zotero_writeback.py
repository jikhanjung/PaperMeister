"""PaperBiblio → Zotero write-back path (P08 §3.5).

Used by `biblio_reflect.apply()` when `paper.zotero_key` is set. Implements
the "Zotero is source of truth" policy:

  1. Fetch fresh item from Zotero (gives us current data + version).
  2. Compute an empty-slot patch **against the fresh Zotero state**, not
     against the local mirror. This protects us from local parser bugs
     and stale mirrors.
  3. If the patch is empty → no-op. Local mirror is refreshed from the
     fresh data anyway (in case local was stale).
  4. If the patch is non-empty → PATCH the item via pyzotero. On success,
     re-fetch and refresh local. On failure, raise and leave local alone.

The `force_override` flag is the escape hatch for cases like
`curated_author_shortfall`: user explicitly wants to replace Zotero data
that is technically non-empty but wrong. Without it, writeback is strictly
additive (fill-empty-slot only).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

from .models import Author, Paper, PaperBiblio, PaperFile, db
from .zotero_client import ZoteroClient


class ZoteroWriteAccessDenied(PermissionError):
    """API key is missing write access for the targeted Zotero library."""


class ZoteroPatchRejected(RuntimeError):
    """Zotero rejected the patch payload (e.g. wrong field for itemType)."""


# Zotero uses a different "journal-like" field per itemType. publicationTitle
# is the article/magazine default; bookSection/conferencePaper diverge.
# Add more rows as new doc_type → itemType mappings come up in the wild.
ITEM_TYPE_JOURNAL_FIELD: dict[str, str] = {
    'journalArticle':   'publicationTitle',
    'magazineArticle':  'publicationTitle',
    'newspaperArticle': 'publicationTitle',
    'bookSection':      'bookTitle',
    'conferencePaper':  'proceedingsTitle',
    'encyclopediaArticle': 'encyclopediaTitle',
    'dictionaryEntry':  'dictionaryTitle',
}


def _journal_field_for(item_type: str) -> str | None:
    """Return the Zotero field name that holds the "container title" for
    this itemType, or None if the type has no such field (e.g. `book`,
    `thesis`). Callers must SKIP the journal write when this is None.
    """
    return ITEM_TYPE_JOURNAL_FIELD.get(item_type or '')


# biblio.doc_type → Zotero itemType. Used to upgrade a placeholder 'document'
# (what standalone auto-promote creates) to the real type once a high-confidence
# extraction tells us what it is. journal_issue/unknown are intentionally absent
# (no upgrade). Mirrors scripts/promote_standalone.py.
DOC_TYPE_TO_ITEM_TYPE: dict[str, str] = {
    'article': 'journalArticle',
    'book':    'book',
    'chapter': 'bookSection',
    'thesis':  'thesis',
    'report':  'report',
}


def _build_type_upgrade_payload(
    client: ZoteroClient, data: dict, biblio: PaperBiblio, target_type: str
) -> dict:
    """Build a full item payload that converts `data` to `target_type`, filled
    from `biblio`. Template-based so only fields valid for the new type are
    sent (Zotero rejects unknown fields). Preserves identity + placement.

    Only valid fields appear in the template, so each assignment is guarded by
    membership — that doubles as the per-type field-validity check for
    volume/issue/pages and the journal-like container field.
    """
    template = _zotero_retry(lambda: client._zot.item_template(target_type))
    payload = dict(template)
    payload['key'] = data['key']
    payload['version'] = data['version']
    for f in ('collections', 'parentItem', 'tags', 'relations'):
        if f in data:
            payload[f] = data[f]

    new_title = (biblio.title or '').strip()
    if 'title' in payload:
        payload['title'] = new_title or (data.get('title') or '')
    if 'date' in payload:
        payload['date'] = str(biblio.year) if biblio.year else (data.get('date') or '')
    if 'DOI' in payload:
        payload['DOI'] = (biblio.doi or data.get('DOI') or '').strip()
    if 'abstractNote' in payload:
        payload['abstractNote'] = (biblio.abstract or data.get('abstractNote') or '').strip()
    if 'language' in payload:
        payload['language'] = (biblio.language or data.get('language') or '').strip()

    authors = _parse_biblio_authors(biblio.authors_json or '')
    if authors:
        payload['creators'] = _author_creators(authors)
    elif data.get('creators'):
        payload['creators'] = data['creators']

    jfield = _journal_field_for(target_type)
    if jfield and jfield in payload and (biblio.journal or '').strip():
        payload[jfield] = biblio.journal.strip()

    for f in ('volume', 'issue', 'pages'):
        bv = (getattr(biblio, f, '') or '').strip()
        if bv and f in payload:
            payload[f] = bv

    return payload


# Server-side transient HTTP codes worth retrying. 429 (Too Many Requests —
# rate/usage limit) is DELIBERATELY excluded: retrying while Zotero is throttling
# you is counterproductive. Those are logged and left for a later batch.
_RETRY_HTTP_CODES = ('500', '502', '503', '504')


def _zotero_error(*names):
    """Resolve a pyzotero error class across versions, by any of `names`.

    pyzotero 1.13 renamed every error with an `Error` suffix
    (``UserNotAuthorised`` → ``UserNotAuthorisedError``). Naming the missing one
    in an ``except`` clause raises AttributeError *while the real exception is in
    flight*, so the actual Zotero failure is replaced by a confusing one.

    Returns an empty tuple when no name matches, which is a valid `except`
    target that never fires — so a future rename degrades to "not specially
    handled" rather than breaking the call.
    """
    from pyzotero import zotero_errors
    for name in names:
        cls = getattr(zotero_errors, name, None)
        if cls is not None:
            return cls
    return ()


def _transient_network_errors() -> tuple:
    """Connection/timeout exception types to retry, across HTTP backends.

    pyzotero moved from requests to httpx in 1.13, so the same network blip
    arrives as a different exception class depending on the installed version.
    `download_file_content` still calls requests directly, so both matter.
    HTTP *status* errors are excluded on purpose — those are handled by code.
    """
    import requests
    types: list = [requests.exceptions.ConnectionError, requests.exceptions.Timeout]
    try:
        import httpx
    except ImportError:
        pass
    else:
        types.append(httpx.TransportError)   # connect/read/timeout, not status
    return tuple(types)


def _is_retryable_zotero_error(exc: Exception) -> bool:
    """True for transient server-side failures (5xx / connection / timeout), but
    NOT for 429 rate limits or 4xx client errors."""
    if isinstance(exc, _transient_network_errors()):
        return True
    msg = str(exc)
    return any(
        (f'Code: {c}' in msg) or (f'{c} Server Error' in msg)
        for c in _RETRY_HTTP_CODES
    )


def _zotero_retry(fn, *, attempts: int = 3, delays=(2.0, 5.0)):
    """Call fn(); retry on transient Zotero errors with short backoff. Bounded
    so the UI (write-back runs on the main thread) isn't frozen for long. Raises
    the last exception once attempts are exhausted or the error isn't retryable.
    """
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if i >= attempts - 1 or not _is_retryable_zotero_error(exc):
                raise
            time.sleep(delays[min(i, len(delays) - 1)])


def _fetch_item(client: ZoteroClient, key: str):
    """client._zot.item(key) with transient-error retry."""
    return _zotero_retry(lambda: client._zot.item(key))


def _update_item(client: ZoteroClient, payload: dict) -> None:
    """PATCH wrapper that translates pyzotero errors into clearer types.

    Without this, pyzotero raises UserNotAuthorised / UnsupportedParams with
    wall-of-text tracebacks that hit the UI as generic background failures.
    Transient 5xx/connection errors are retried first.
    """
    not_authorised = _zotero_error('UserNotAuthorisedError', 'UserNotAuthorised')
    unsupported = _zotero_error('UnsupportedParamsError', 'UnsupportedParams')

    try:
        _zotero_retry(lambda: client._zot.update_item(payload))
    except not_authorised as e:
        raise ZoteroWriteAccessDenied(
            'Zotero API key lacks write access. Create a new key with '
            '"Allow write access" at zotero.org/settings/keys, or turn '
            'off "Enable Zotero write-back" in Preferences.'
        ) from e
    except unsupported as e:
        # Most common cause: a field name that's not valid for this itemType
        # (e.g. publicationTitle on bookSection). Surface the original message
        # but wrapped in a tidy exception.
        raise ZoteroPatchRejected(str(e).strip() or 'Zotero rejected patch (400)') from e


Action = Literal['noop', 'wrote', 'would_write', 'would_noop']


@dataclass
class WritebackResult:
    action: Action
    changed: bool
    patch: dict = field(default_factory=dict)
    reason: str = ''     # 'zotero_already_complete' for no-op


# ── Patch computation ────────────────────────────────────────────

def _parse_biblio_authors(authors_json: str) -> list[str]:
    """Match the shape used by biblio_reflect._parse_authors."""
    if not authors_json:
        return []
    try:
        data = json.loads(authors_json)
    except Exception:
        return []
    out: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            name = entry.get('name') or entry.get('full_name') or ''
            if name.strip():
                out.append(name.strip())
        elif isinstance(entry, str):
            if entry.strip():
                out.append(entry.strip())
    return out


def title_is_filename_placeholder(paper: Paper, current_title: str) -> bool:
    """True when the item title is just the PDF filename — the placeholder that
    standalone auto-promote (session 36) sets on the new parent item.

    Such a title is technically non-empty but carries no real bibliographic
    information, so a real extracted title should replace it rather than be
    held back by the empty-slot rule.
    """
    cur = (current_title or '').strip()
    if not cur:
        return False
    pdf = (
        PaperFile.select()
        .where((PaperFile.paper == paper) & (~PaperFile.path.endswith('.json')))
        .order_by(PaperFile.id)
        .first()
    )
    if pdf is None or not pdf.path:
        return False
    base = os.path.basename(pdf.path)
    stem = os.path.splitext(base)[0]
    return cur == base or cur == stem


def _compute_patch(
    biblio: PaperBiblio, data: dict, *, force_override: bool,
    title_overridable: bool = False,
) -> dict:
    """Build the minimal patch dict needed on top of `data` (Zotero's fresh
    state) to reflect this biblio. Empty-slot rule unless force_override.

    `title_overridable` relaxes the title rule: when the current title is a
    standalone filename placeholder, a real extracted title replaces it even
    though the slot isn't strictly empty.
    """
    patch: dict = {}
    biblio_authors = _parse_biblio_authors(biblio.authors_json or '')

    # title — fill when empty, or replace a standalone filename placeholder.
    cur_title = (data.get('title') or '').strip()
    new_title = (biblio.title or '').strip()
    if new_title and new_title != cur_title and (not cur_title or title_overridable):
        patch['title'] = new_title

    # date ← biblio.year (only if Zotero's date is empty)
    if not (data.get('date') or '').strip() and biblio.year is not None:
        patch['date'] = str(biblio.year)

    # "Journal-like" container title — Zotero uses different field names per
    # itemType (publicationTitle for articles, bookTitle for bookSection, …).
    # Skip entirely if this itemType has no such field.
    journal_field = _journal_field_for(data.get('itemType', ''))
    if (
        journal_field
        and not (data.get(journal_field) or '').strip()
        and (biblio.journal or '').strip()
    ):
        patch[journal_field] = biblio.journal.strip()

    # DOI (note: Zotero's field name is uppercase)
    if not (data.get('DOI') or '').strip() and (biblio.doi or '').strip():
        patch['DOI'] = biblio.doi.strip()

    # journal-article detail fields. `f in data` doubles as the validity check:
    # Zotero returns every field valid for the itemType, so a field absent from
    # `data` isn't valid for this type and must not be sent (avoids 400).
    for f in ('volume', 'issue', 'pages'):
        bv = (getattr(biblio, f, '') or '').strip()
        if bv and f in data and not (data.get(f) or '').strip():
            patch[f] = bv

    # creators — Zotero expects a list of dicts with creatorType.
    # MVP uses single-field `name` to avoid risky first/last split.
    existing_creators = data.get('creators') or []
    existing_count = sum(1 for c in existing_creators if c.get('creatorType') == 'author')

    should_write_creators = False
    if existing_count == 0 and biblio_authors:
        should_write_creators = True
    elif force_override and biblio_authors and len(biblio_authors) > existing_count:
        # §4.2.1 escape hatch: curated_author_shortfall
        should_write_creators = True

    if should_write_creators:
        patch['creators'] = _author_creators(biblio_authors)

    return patch


# ── Local refresh ────────────────────────────────────────────────

def _refresh_local_paper(paper: Paper, data: dict, meta: dict | None, client: ZoteroClient):
    """Overwrite local Paper/Author rows from a Zotero item payload.

    Uses the same parse function as the ingestion path for consistency.
    Does NOT touch PaperBiblio rows.
    """
    parsed = client._parse_item_metadata(data, meta=meta or {})

    with db.atomic():
        paper.title = parsed['title']
        paper.date = parsed['date']
        paper.year = parsed['year']
        paper.journal = parsed.get('journal', '')
        paper.doi = parsed.get('doi', '')
        paper.save()

        Author.delete().where(Author.paper == paper).execute()
        for i, name in enumerate(parsed['authors']):
            Author.create(paper=paper, name=name, order=i)


# ── Main entry ───────────────────────────────────────────────────

def writeback_biblio(
    biblio: PaperBiblio,
    paper: Paper,
    *,
    client: ZoteroClient,
    dry_run: bool = False,
    force_override: bool = False,
) -> WritebackResult:
    """Apply `biblio` to `paper`'s Zotero item. Caller must have already
    verified `paper.zotero_key` is non-empty.

    Returns a WritebackResult. Raises on Zotero API failure; local state
    is untouched in that case.
    """
    if not paper.zotero_key:
        raise ValueError(f'paper {paper.id} has no zotero_key')

    # 1. Fresh fetch — we need current data AND version for concurrency.
    item = _fetch_item(client, paper.zotero_key)
    data = item['data']
    meta = item.get('meta') or {}

    # Guard: a standalone PDF (Paper.zotero_key IS the attachment) can't hold
    # bibliographic fields — date/creators 400 with "not a valid field for type
    # 'attachment'". Promote it to a parent first, then re-apply.
    if data.get('itemType') == 'attachment':
        raise ZoteroPatchRejected(
            f"paper {paper.id} is a standalone PDF (its Zotero item is an "
            f"attachment); promote it to a parent item first "
            f"(scripts/promote_processed_standalones.py --execute), then re-apply biblio."
        )

    # 1b. itemType upgrade — a standalone auto-promote leaves a placeholder
    #     'document'. Once a high-confidence extraction knows the real type,
    #     rebuild the item as journalArticle/book/bookSection/… so its
    #     type-specific fields (publicationTitle, volume/issue/pages) become
    #     valid. Gated on the filename-placeholder/empty title so curated
    #     'document' items the user set deliberately are left alone.
    current_type = data.get('itemType', '')
    title_placeholder = title_is_filename_placeholder(paper, data.get('title', ''))
    upgrade_to = None
    if current_type == 'document' and (title_placeholder or not (data.get('title') or '').strip()):
        cand = DOC_TYPE_TO_ITEM_TYPE.get((biblio.doc_type or '').strip())
        if cand and cand != current_type:
            upgrade_to = cand

    if upgrade_to:
        payload = _build_type_upgrade_payload(client, data, biblio, upgrade_to)
        if dry_run:
            return WritebackResult(
                action='would_write', changed=True,
                patch={'itemType': upgrade_to, **{k: payload.get(k) for k in
                       ('title', 'date', 'DOI', 'volume', 'issue', 'pages') if payload.get(k)}},
            )
        _update_item(client, payload)
        fresh = _fetch_item(client, paper.zotero_key)
        _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)
        return WritebackResult(action='wrote', changed=True, patch={'itemType': upgrade_to})

    # 2. Compute patch against Zotero state (not local). Allow the extracted
    #    title to replace a standalone filename placeholder (promote artifact).
    patch = _compute_patch(
        biblio, data, force_override=force_override,
        title_overridable=title_placeholder,
    )

    # 3a. No-op case — Zotero is already authoritative and complete for
    #     everything this biblio would contribute. Still refresh local in
    #     case the mirror was stale (common after parser fixes).
    if not patch:
        if dry_run:
            return WritebackResult(
                action='would_noop', changed=False,
                reason='zotero_already_complete',
            )
        _refresh_local_paper(paper, data, meta, client)
        return WritebackResult(
            action='noop', changed=False,
            reason='zotero_already_complete',
        )

    # 3b. Patch has content — PATCH to Zotero.
    if dry_run:
        return WritebackResult(
            action='would_write', changed=True, patch=patch,
        )

    # Merge patch onto the full data dict (pyzotero's check_items validates
    # fields — all fields here are already valid because they came from Zotero).
    payload = dict(data)
    payload.update(patch)
    # payload already has 'key' and 'version' from the fresh fetch.
    _update_item(client, payload)

    # 4. Re-fetch to get the authoritative new version + normalised fields
    #    (e.g. Zotero may rewrite 'date' → 'parsedDate' on the server).
    fresh = _fetch_item(client, paper.zotero_key)
    _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)

    return WritebackResult(
        action='wrote', changed=True, patch=patch,
    )


# ── Override-driven writeback (desktop comparison UI) ────────────

def _is_cjk_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x3400 <= cp <= 0x9FFF       # CJK Unified Ideographs
        or 0xAC00 <= cp <= 0xD7AF    # Hangul Syllables
        or 0x3040 <= cp <= 0x30FF    # Hiragana/Katakana
    )


def _split_first_last(name: str) -> tuple[str, str]:
    """(firstName, lastName) from a display name. Mirrors desktop
    biblio_service.split_author_name: "Last, First", space-separated, and
    unspaced CJK (Japanese 4→2/2, Korean 3→1/2). Empty first = unsplittable.
    """
    name = name.strip()
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        if len(parts) == 2 and parts[1]:
            return parts[1], parts[0]   # "Last, First" → (First, Last)
        return '', parts[0]

    tokens = name.split()
    if len(tokens) == 1:
        single = tokens[0]
        if single and all(_is_cjk_char(c) for c in single):
            if len(single) == 4:
                return single[2:], single[:2]
            if len(single) == 3:
                return single[1:], single[:1]
        return '', single
    return ' '.join(tokens[:-1]), tokens[-1]


def _split_name_for_zotero(display_name: str) -> dict:
    """Convert a single display name into a Zotero creator dict, splitting into
    firstName/lastName whenever possible (incl. unspaced CJK). Falls back to a
    single-field `name` for mononyms / organisations / unsplittable input.
    """
    name = display_name.strip()
    if not name:
        return {}
    first, last = _split_first_last(name)
    if first and last:
        return {'creatorType': 'author', 'firstName': first, 'lastName': last}
    return {'creatorType': 'author', 'name': name}


def _author_creators(names) -> list[dict]:
    """Zotero author creators for a list of display names, always splitting
    into firstName/lastName when the name allows it (falls back to single-field
    `name` for single-token / unsplit-CJK / organisational names)."""
    return [c for c in (_split_name_for_zotero(n) for n in names) if c]


def _compute_override_patch(overrides: dict, data: dict) -> dict:
    """Build a Zotero patch from explicit per-field overrides.

    Unlike `_compute_patch`, this does NOT apply empty-slot logic. Each
    non-None override is a deliberate user choice and replaces the Zotero
    field outright — but only when the new value actually differs from
    Zotero's current value (skip no-op writes).
    """
    patch: dict = {}

    if 'title' in overrides and overrides['title'] is not None:
        new = (overrides['title'] or '').strip()
        if new != (data.get('title') or '').strip():
            patch['title'] = new

    if 'year' in overrides and overrides['year'] is not None:
        new = (overrides['year'] or '').strip()
        if new != (data.get('date') or '').strip():
            patch['date'] = new

    if 'journal' in overrides and overrides['journal'] is not None:
        journal_field = _journal_field_for(data.get('itemType', ''))
        if journal_field:
            new = (overrides['journal'] or '').strip()
            if new != (data.get(journal_field) or '').strip():
                patch[journal_field] = new
        # itemType has no journal-like field — silently drop the override;
        # user can edit Zotero directly for these (book, thesis, etc.).

    if 'doi' in overrides and overrides['doi'] is not None:
        new = (overrides['doi'] or '').strip()
        if new != (data.get('DOI') or '').strip():
            patch['DOI'] = new

    if 'authors' in overrides and overrides['authors'] is not None:
        # overrides['authors'] is newline-joined display text from the UI.
        lines = [
            line.strip() for line in (overrides['authors'] or '').splitlines()
            if line.strip()
        ]
        new_creators = [c for c in (_split_name_for_zotero(n) for n in lines) if c]

        existing = [
            c for c in (data.get('creators') or [])
            if c.get('creatorType') == 'author'
        ]
        non_authors = [
            c for c in (data.get('creators') or [])
            if c.get('creatorType') != 'author'
        ]
        if not _creators_equal(existing, new_creators):
            patch['creators'] = non_authors + new_creators

    return patch


def _creators_equal(a: list[dict], b: list[dict]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=False):
        ax = (
            (x.get('firstName') or '').strip(),
            (x.get('lastName') or '').strip(),
            (x.get('name') or '').strip(),
        )
        ay = (
            (y.get('firstName') or '').strip(),
            (y.get('lastName') or '').strip(),
            (y.get('name') or '').strip(),
        )
        if ax != ay:
            return False
    return True


def writeback_overrides(
    paper: Paper,
    overrides: dict,
    *,
    client: ZoteroClient,
    dry_run: bool = False,
) -> WritebackResult:
    """Apply explicit user-chosen field values to `paper`'s Zotero item.

    Used by the desktop "Apply Biblio" comparison UI, where the user has
    already reviewed each field and picked a value. Writes are NOT
    empty-slot-only — overrides replace existing Zotero values where they
    differ. Caller is responsible for the user's intent.

    `overrides` maps field_key → str | None. None means "do not touch this
    field". A str is the user's chosen value (already trimmed/edited).
    Recognised keys: title, year, journal, doi, authors. Authors text is
    newline-separated with one creator per line ("Last, First" or "First
    Last").
    """
    if not paper.zotero_key:
        raise ValueError(f'paper {paper.id} has no zotero_key')

    item = _fetch_item(client, paper.zotero_key)
    data = item['data']
    meta = item.get('meta') or {}

    patch = _compute_override_patch(overrides, data)

    if not patch:
        if dry_run:
            return WritebackResult(
                action='would_noop', changed=False,
                reason='zotero_already_matches',
            )
        _refresh_local_paper(paper, data, meta, client)
        return WritebackResult(
            action='noop', changed=False,
            reason='zotero_already_matches',
        )

    if dry_run:
        return WritebackResult(
            action='would_write', changed=True, patch=patch,
        )

    payload = dict(data)
    payload.update(patch)
    _update_item(client, payload)

    fresh = _fetch_item(client, paper.zotero_key)
    _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)

    return WritebackResult(
        action='wrote', changed=True, patch=patch,
    )


def promote_standalone_with_filename(
    paper_file,
    *,
    client: ZoteroClient,
    item_type: str = 'document',
) -> str | None:
    """Promote a standalone PDF to a Zotero parent item.

    Creates a parent item with the PDF's filename (minus extension) as
    title, then re-parents the PDF attachment under it. No LLM metadata
    involved — this is the lightweight equivalent of Zotero GUI's
    "Create Parent Item…" action.

    Args:
        paper_file: PaperFile pointing at the standalone PDF.
        client:     authenticated ZoteroClient (must have write access).
        item_type:  Zotero itemType for the new parent (default 'document'
                    — most neutral, fewest required fields).

    Returns the new parent's Zotero key on success. Returns None if the
    paper isn't standalone (no-op). Raises on Zotero API failure.
    """
    import os

    paper = paper_file.paper

    # Standalone = Paper.zotero_key == PaperFile.zotero_key (the attachment
    # is acting as its own canonical record). Anything else is already
    # parented — nothing to promote.
    if not paper.zotero_key or paper.zotero_key != paper_file.zotero_key:
        return None

    # Pull the PDF attachment to read its collections (so the new parent
    # ends up in the same place) before we re-parent it.
    pdf_item = _fetch_item(client, paper_file.zotero_key)
    pdf_data = pdf_item['data']
    collections = pdf_data.get('collections', []) or []

    title = paper.title or os.path.splitext(os.path.basename(paper_file.path))[0]

    payload = {
        'itemType': item_type,
        'title': title,
        'collections': collections,
        'tags': [],
        'relations': {},
    }

    try:
        resp = client._zot.create_items([payload])
    except Exception as exc:
        msg = str(exc).lower()
        if 'forbidden' in msg or 'not authorised' in msg or '403' in msg:
            raise ZoteroWriteAccessDenied(
                'Zotero API key lacks write access — cannot create parent item. '
                'Update the key with write permission, or turn off '
                '"Auto-create parent item for standalone PDFs" in Preferences → Zotero.'
            ) from exc
        raise

    successes = resp.get('successful', {}) if isinstance(resp, dict) else {}
    if not successes:
        raise RuntimeError(f'create_items returned no success: {resp}')
    new_parent_key = list(successes.values())[0]['key']

    # Re-parent the PDF. Children inherit collections from their parent,
    # so clear the attachment's collection membership to avoid duplicates.
    pdf_data['parentItem'] = new_parent_key
    pdf_data['collections'] = []
    # Drop the server-managed read-only key Zotero rejects on write
    # ("Invalid keys present in item 1: lastRead") — some attachments carry it.
    pdf_data.pop('lastRead', None)
    _zotero_retry(lambda: client._zot.update_item(pdf_data))

    # Local DB: Paper.zotero_key now points at the new parent. PaperFile.zotero_key
    # stays the same (it's still the attachment, just parented now).
    paper.zotero_key = new_parent_key
    if not paper.title:
        paper.title = title
    paper.save()

    return new_parent_key
