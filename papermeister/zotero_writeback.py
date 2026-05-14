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
from dataclasses import dataclass, field
from typing import Literal

from .models import Author, Paper, PaperBiblio, db
from .zotero_client import ZoteroClient


class ZoteroWriteAccessDenied(PermissionError):
    """API key is missing write access for the targeted Zotero library."""


def _update_item(client: ZoteroClient, payload: dict) -> None:
    """PATCH wrapper that translates 403 into a clearer exception type.

    Without this, pyzotero raises UserNotAuthorised with a wall-of-text
    traceback that hits the UI as a generic background-task failure.
    """
    from pyzotero import zotero_errors

    try:
        client._zot.update_item(payload)
    except zotero_errors.UserNotAuthorised as e:
        raise ZoteroWriteAccessDenied(
            'Zotero API key lacks write access. Create a new key with '
            '"Allow write access" at zotero.org/settings/keys, or turn '
            'off "Enable Zotero write-back" in Preferences.'
        ) from e


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


def _compute_patch(
    biblio: PaperBiblio, data: dict, *, force_override: bool
) -> dict:
    """Build the minimal patch dict needed on top of `data` (Zotero's fresh
    state) to reflect this biblio. Empty-slot rule unless force_override.
    """
    patch: dict = {}
    biblio_authors = _parse_biblio_authors(biblio.authors_json or '')

    # title
    if not (data.get('title') or '').strip() and (biblio.title or '').strip():
        patch['title'] = biblio.title.strip()

    # date ← biblio.year (only if Zotero's date is empty)
    if not (data.get('date') or '').strip() and biblio.year is not None:
        patch['date'] = str(biblio.year)

    # publicationTitle (journal)
    if not (data.get('publicationTitle') or '').strip() and (biblio.journal or '').strip():
        patch['publicationTitle'] = biblio.journal.strip()

    # DOI (note: Zotero's field name is uppercase)
    if not (data.get('DOI') or '').strip() and (biblio.doi or '').strip():
        patch['DOI'] = biblio.doi.strip()

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
        patch['creators'] = [
            {'creatorType': 'author', 'name': name} for name in biblio_authors
        ]

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
    item = client._zot.item(paper.zotero_key)
    data = item['data']
    meta = item.get('meta') or {}

    # 2. Compute patch against Zotero state (not local).
    patch = _compute_patch(biblio, data, force_override=force_override)

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
    fresh = client._zot.item(paper.zotero_key)
    _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)

    return WritebackResult(
        action='wrote', changed=True, patch=patch,
    )


# ── Override-driven writeback (desktop comparison UI) ────────────

def _split_name_for_zotero(display_name: str) -> dict:
    """Convert a single display name into a Zotero creator dict.

    `display_name` may be "Last, First", "First Last", or unsplit CJK.
    Uses the same heuristics as desktop biblio_service.split_author_name.
    """
    name = display_name.strip()
    if not name:
        return {}

    if ',' in name:
        last, _, first = name.partition(',')
        last, first = last.strip(), first.strip()
        if last and first:
            return {'creatorType': 'author', 'firstName': first, 'lastName': last}
        return {'creatorType': 'author', 'name': name}

    tokens = name.split()
    if len(tokens) >= 2:
        first = ' '.join(tokens[:-1])
        last = tokens[-1]
        return {'creatorType': 'author', 'firstName': first, 'lastName': last}

    # Single token — fall back to single-field name (covers unsplit CJK,
    # organisational authors, etc.).
    return {'creatorType': 'author', 'name': name}


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
        new = (overrides['journal'] or '').strip()
        if new != (data.get('publicationTitle') or '').strip():
            patch['publicationTitle'] = new

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
    for x, y in zip(a, b):
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

    item = client._zot.item(paper.zotero_key)
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

    fresh = client._zot.item(paper.zotero_key)
    _refresh_local_paper(paper, fresh['data'], fresh.get('meta'), client)

    return WritebackResult(
        action='wrote', changed=True, patch=patch,
    )
