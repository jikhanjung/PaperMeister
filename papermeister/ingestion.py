import datetime
import hashlib
import os
import shutil
import time
from pathlib import Path

from .file_utils import attachment_status, is_derived, is_pdf
from .models import (
    db, Source, Folder, Paper, Author, PaperFile, PaperFolder,
    PaperBiblio, Passage,
)


def hash_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def ingest_pdf(filepath, folder):
    """Register a PDF under a folder. Returns (paper_file, is_new)."""
    file_hash = hash_file(filepath)

    existing = PaperFile.select().where(PaperFile.hash == file_hash).first()
    if existing:
        return existing, False

    with db.atomic():
        paper = Paper.create(title=Path(filepath).stem, folder=folder)
        paper_file = PaperFile.create(
            paper=paper,
            path=filepath,
            hash=file_hash,
            status='pending',
        )
    return paper_file, True


def import_source_directory(dir_path, progress_callback=None):
    """Import a directory tree as a Source with folder hierarchy.

    Returns (source, new_paper_files).
    """
    dir_path = os.path.abspath(dir_path)
    name = os.path.basename(dir_path)

    # Reuse existing source or create new one
    source = Source.select().where(
        Source.source_type == 'directory',
        Source.path == dir_path,
    ).first()
    if not source:
        source = Source.create(name=name, source_type='directory', path=dir_path)

    new_files = []
    _scan_dir(source, dir_path, None, new_files, progress_callback)
    return source, new_files


def _scan_dir(source, dir_path, parent_folder, new_files, progress_callback):
    """Recursively scan a directory, creating Folder + PaperFile records."""
    # Get or create folder
    folder = Folder.select().where(
        Folder.source == source,
        Folder.path == dir_path,
    ).first()
    if not folder:
        folder = Folder.create(
            source=source,
            name=os.path.basename(dir_path),
            parent=parent_folder,
            path=dir_path,
        )

    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return

    for entry in entries:
        if entry.startswith('.'):
            continue
        full_path = os.path.join(dir_path, entry)
        if os.path.isfile(full_path) and entry.lower().endswith('.pdf'):
            pf, is_new = ingest_pdf(full_path, folder)
            if is_new:
                new_files.append(pf)
            if progress_callback:
                progress_callback(f'Found: {entry}')
        elif os.path.isdir(full_path):
            _scan_dir(source, full_path, folder, new_files, progress_callback)


# ── Zotero import ───────────────────────────────────────────


def get_or_create_zotero_source(user_id):
    """Get or create a Source for a Zotero library."""
    source = Source.select().where(
        Source.source_type == 'zotero',
        Source.path == str(user_id),
    ).first()
    if not source:
        source = Source.create(
            name=f'Zotero ({user_id})',
            source_type='zotero',
            path=str(user_id),
        )
    return source


def sync_zotero_collections(zotero_client, source, collections):
    """Sync all Zotero collections to DB as Folders. No paper import.

    Args:
        zotero_client: ZoteroClient instance
        source: Source record (type='zotero')
        collections: list of dicts with key, name, parent_key
    """
    # First pass: create/update all folders
    for col in collections:
        folder = Folder.select().where(
            Folder.source == source,
            Folder.zotero_key == col['key'],
        ).first()
        if folder:
            if folder.name != col['name']:
                folder.name = col['name']
                folder.save()
        else:
            Folder.create(
                source=source,
                name=col['name'],
                parent=None,  # set in second pass
                zotero_key=col['key'],
            )

    # Second pass: set parent relationships
    for col in collections:
        if not col['parent_key']:
            continue
        folder = Folder.select().where(
            Folder.source == source,
            Folder.zotero_key == col['key'],
        ).first()
        parent = Folder.select().where(
            Folder.source == source,
            Folder.zotero_key == col['parent_key'],
        ).first()
        if folder and parent and folder.parent != parent:
            folder.parent = parent
            folder.save()

    # Save last sync timestamp and library version
    from datetime import datetime
    from .preferences import set_pref
    set_pref('zotero_last_sync', datetime.now().isoformat())
    try:
        version = zotero_client.get_library_version()
        set_pref('zotero_library_version', version)
    except Exception:
        pass


def _get_or_create_zotero_folder(source, collection):
    """Get or create a Folder for a Zotero collection."""
    folder = Folder.select().where(
        Folder.source == source,
        Folder.zotero_key == collection['key'],
    ).first()
    if not folder:
        parent_folder = None
        if collection.get('parent_key'):
            parent_folder = Folder.select().where(
                Folder.source == source,
                Folder.zotero_key == collection['parent_key'],
            ).first()
        folder = Folder.create(
            source=source,
            name=collection['name'],
            parent=parent_folder,
            zotero_key=collection['key'],
        )
    return folder


def _refresh_existing_attachment(existing_pf, att):
    """Apply attachment field updates that incremental sync otherwise skips.

    When a PaperFile with the same zotero_key already exists, the sync loops
    `continue` past it — so filename renames done on the Zotero side never
    propagate. This helper covers that gap for the fields we currently store.

    Also resets `failed` entries that never produced a hash back to `pending`,
    on the theory that the failure was likely caused by the stale path
    (Windows-illegal chars, length limits, encoding issues).
    """
    new_fname = att.get('filename', '')
    if not new_fname or existing_pf.path == new_fname:
        return
    existing_pf.path = new_fname
    ct = att.get('content_type', '') or att.get('contentType', '')
    if not is_pdf(new_fname, ct) and not is_derived(new_fname, ct):
        # Non-PDF attachment (supplementary data, book, etc.) — never an OCR
        # target. Park it as 'skipped' so it leaves the failed/pending queues.
        if existing_pf.status in ('failed', 'pending'):
            existing_pf.status = 'skipped'
            existing_pf.failure_reason = ''
    elif existing_pf.status == 'failed' and not existing_pf.hash:
        # PDF that never produced a hash — the failure was likely the stale
        # path; reset so the next Process retries it.
        existing_pf.status = 'pending'
        existing_pf.failure_reason = ''
    existing_pf.save()


def _merge_stale_standalone(old_paper, new_paper):
    """Move all records from an obsolete standalone Paper to its new parent.

    Triggered when sync sees a PDF attachment that's now a child of a real
    Zotero parent item, but the local DB still has the standalone Paper
    that was created when the PDF was synced parent-less. Common cause:
    the user ran "Create Parent Item…" in the Zotero GUI between syncs.

    Migrates: PaperFile, PaperBiblio, Passage, and FTS rows. Discards the
    old Paper's authors (always empty for standalone) and folder links
    (the new parent already has its own from the sync).
    """
    if old_paper.id == new_paper.id:
        return
    with db.atomic():
        PaperFile.update(paper=new_paper).where(PaperFile.paper == old_paper).execute()
        PaperBiblio.update(paper=new_paper).where(PaperBiblio.paper == old_paper).execute()
        Passage.update(paper=new_paper).where(Passage.paper == old_paper).execute()
        # passage_fts denormalizes paper_id, title, authors — keep them
        # consistent with the new canonical paper.
        new_authors_str = ', '.join(
            a.name for a in
            Author.select(Author.name)
            .where(Author.paper == new_paper)
            .order_by(Author.order)
        )
        db.execute_sql(
            'UPDATE passage_fts SET paper_id = ?, title = ?, authors = ? '
            'WHERE paper_id = ?',
            [new_paper.id, new_paper.title, new_authors_str, old_paper.id],
        )
        # Authors and PaperFolder cascade away with the old paper.
        old_paper.delete_instance()


def purge_local_by_keys(keys, progress_callback=None):
    """Delete local Papers/PaperFiles whose Zotero key was permanently deleted.

    Mirrors Zotero (source of truth): when an item is emptied from trash it no
    longer exists, so the local Paper + its cascade (Author/PaperFile/Passage/
    PaperBiblio/PaperFolder) and the denormalized passage_fts rows are removed.
    A deleted attachment whose parent still exists drops just that PaperFile.

    The on-disk OCR JSON cache (content-addressed) is intentionally left so the
    same PDF re-imported later can reuse it.

    Returns (deleted_papers, deleted_files).
    """
    if not keys:
        return 0, 0
    keys = [k.upper() for k in keys]
    deleted_papers = 0
    deleted_files = 0
    # Chunk to stay under SQLite's bound-variable limit (999) — the deleted
    # list scanned from version 0 can be large.
    CHUNK = 500
    chunks = [keys[i:i + CHUNK] for i in range(0, len(keys), CHUNK)]
    with db.atomic():
        papers = []
        for ch in chunks:
            papers.extend(Paper.select().where(Paper.zotero_key.in_(ch)))
        for p in papers:
            # passage_fts is an FTS5 table with no FK — clear it explicitly
            # (same reason _merge_stale_standalone updates it by hand).
            db.execute_sql('DELETE FROM passage_fts WHERE paper_id = ?', [p.id])
            p.delete_instance(recursive=True, delete_nullable=True)
            deleted_papers += 1
        # Attachment-only deletions: parent paper survives, drop the PaperFile.
        pfs = []
        for ch in chunks:
            pfs.extend(PaperFile.select().where(PaperFile.zotero_key.in_(ch)))
        for pf in pfs:
            pf.delete_instance()
            deleted_files += 1
    if progress_callback and (deleted_papers or deleted_files):
        progress_callback(
            f'Purged {deleted_papers} papers / {deleted_files} files '
            f'(permanently deleted in Zotero)'
        )
    return deleted_papers, deleted_files


def apply_permanent_deletions(zotero_client, progress_callback=None):
    """Mirror Zotero empty-trash (permanent deletions) into the local DB.

    Tracks its own `zotero_deleted_version` pref (separate from items/collections
    versions to avoid races). On the first run it only records a baseline — there
    is no bounded "since" to scan history with, so existing backlog is handled by
    scripts/purge_deleted_zotero.py. Thereafter each sync scans deletions since
    the last seen version and purges them locally.

    Returns dict: {deleted_papers, deleted_files, baseline}.
    """
    from .preferences import get_pref, set_pref

    current = zotero_client.get_library_version()
    last = get_pref('zotero_deleted_version', None)
    if last is None:
        set_pref('zotero_deleted_version', current)
        return {'deleted_papers': 0, 'deleted_files': 0, 'baseline': True}

    if progress_callback:
        progress_callback('Checking Zotero permanent deletions…')
    deleted_keys = zotero_client.get_deleted_keys(since=last)
    dp, df = purge_local_by_keys(deleted_keys, progress_callback=progress_callback)
    set_pref('zotero_deleted_version', current)
    return {'deleted_papers': dp, 'deleted_files': df, 'baseline': False}


def sync_zotero_items(source, items, orphan_attachments=None, progress_callback=None,
                      zotero_client=None, logger=None):
    """Process items from library-wide incremental fetch.

    Creates/updates Papers, PaperFiles, and PaperFolders from items returned
    by ZoteroClient.get_all_items(since=...).  Unlike the per-collection
    fetch_zotero_collection_items(), this operates across all collections
    at once and uses each item's `collections` array to build PaperFolder
    membership.

    If logger is provided, per-phase timing is emitted at INFO level so we
    can see whether time is going to the main loop or orphan processing.

    Note: previously this function also ran a per-paper `zot.children()`
    backfill at the end to catch attachments missed by earlier syncs. It's
    now in `backfill_missing_paperfiles()` and not called from any sync
    path — see that function's docstring for the rationale.

    Returns (new_count, updated_count).
    """
    def _log(msg):
        if logger is not None:
            logger.info('items: %s', msg)

    new_count = 0
    updated_count = 0
    main_t0 = time.perf_counter()

    for i, item in enumerate(items):
        if progress_callback:
            progress_callback(f'[{i + 1}/{len(items)}] {item["title"][:60]}')

        paper = Paper.select().where(Paper.zotero_key == item['key']).first()

        if paper:
            # Update metadata for existing paper.
            changed = False
            for field, val in [
                ('title', item['title']),
                ('date', item.get('date', '')),
                ('year', item['year']),
                ('journal', item.get('journal', '')),
                ('doi', item.get('doi', '')),
            ]:
                if getattr(paper, field) != val:
                    setattr(paper, field, val)
                    changed = True
            if changed:
                paper.save()
                updated_count += 1
            # Refresh authors (fixes legacy "Last First" → "Last, First").
            new_authors = item.get('authors', [])
            existing_names = [
                a.name for a in
                Author.select(Author.name)
                .where(Author.paper == paper)
                .order_by(Author.order)
            ]
            if new_authors != existing_names:
                with db.atomic():
                    Author.delete().where(Author.paper == paper).execute()
                    for order, author_name in enumerate(new_authors):
                        Author.create(paper=paper, name=author_name, order=order)
        else:
            # Determine primary folder from first collection key.
            primary_folder = None
            for col_key in item.get('collections', []):
                primary_folder = Folder.select().where(
                    Folder.source == source, Folder.zotero_key == col_key,
                ).first()
                if primary_folder:
                    break

            with db.atomic():
                paper = Paper.create(
                    title=item['title'],
                    date=item.get('date', ''),
                    year=item['year'],
                    journal=item.get('journal', ''),
                    doi=item.get('doi', ''),
                    folder=primary_folder,
                    zotero_key=item['key'],
                )
                for order, author_name in enumerate(item['authors']):
                    Author.create(paper=paper, name=author_name, order=order)
            new_count += 1

        # PaperFolder membership from collections array.
        for col_key in item.get('collections', []):
            folder = Folder.select().where(
                Folder.source == source, Folder.zotero_key == col_key,
            ).first()
            if folder:
                PaperFolder.get_or_create(paper=paper, folder=folder)

        # PaperFiles for attachments.
        attachments = item.get('attachments', [])

        # Incremental sync may omit unchanged attachments. If a paper has
        # no attachments in this batch AND no PaperFiles in DB, fetch
        # children from the Zotero API to pick them up.
        if not attachments and zotero_client is not None:
            has_files = PaperFile.select().where(PaperFile.paper == paper).exists()
            if not has_files:
                try:
                    children = zotero_client._zot.children(item['key'])
                    for child in children:
                        cdata = child.get('data', {})
                        if cdata.get('itemType') == 'attachment':
                            attachments.append({
                                'key': cdata['key'],
                                'filename': cdata.get('filename', cdata['key']),
                                'content_type': cdata.get('contentType', ''),
                            })
                except Exception:
                    pass  # network error — skip, next sync will retry

        for att in attachments:
            existing_pf = PaperFile.select().where(
                PaperFile.zotero_key == att['key'],
            ).first()
            if existing_pf:
                # Detect "stale standalone" — the attachment was previously
                # synced as parent-less, so a Paper with Paper.zotero_key ==
                # this attachment's key was created. Now Zotero has given
                # the PDF a real parent (the item we're processing) and we
                # need to fold the obsolete Paper into it.
                if (
                    existing_pf.paper_id != paper.id
                    and existing_pf.paper.zotero_key == att['key']
                ):
                    if progress_callback:
                        progress_callback(
                            f'  merging stale standalone Paper {existing_pf.paper_id} '
                            f'→ {paper.id} ({att["filename"]})'
                        )
                    _merge_stale_standalone(existing_pf.paper, paper)
                # Otherwise the PaperFile is already correctly parented
                # (idempotent re-sync). Still refresh fields the user may
                # have changed on the Zotero side (e.g. attachment rename).
                _refresh_existing_attachment(existing_pf, att)
                continue
            ct = att.get('content_type', '')
            fname = att['filename']
            PaperFile.create(
                paper=paper,
                path=fname,
                hash='',
                status=attachment_status(fname, ct),
                zotero_key=att['key'],
            )

    _log(f'main loop ({len(items)} items) took {time.perf_counter() - main_t0:.2f}s')

    # Handle orphan attachments (parent not in this incremental batch).
    orphan_t0 = time.perf_counter()
    n_orphan_atts = 0
    if orphan_attachments:
        for parent_key, atts in orphan_attachments.items():
            paper = Paper.select().where(Paper.zotero_key == parent_key).first()
            if not paper:
                continue
            n_orphan_atts += len(atts)
            for att in atts:
                existing_pf = PaperFile.select().where(
                    PaperFile.zotero_key == att['key'],
                ).first()
                if existing_pf:
                    if (
                        existing_pf.paper_id != paper.id
                        and existing_pf.paper.zotero_key == att['key']
                    ):
                        if progress_callback:
                            progress_callback(
                                f'  merging stale standalone Paper '
                                f'{existing_pf.paper_id} → {paper.id} '
                                f'({att["filename"]})'
                            )
                        _merge_stale_standalone(existing_pf.paper, paper)
                    _refresh_existing_attachment(existing_pf, att)
                    continue
                ct = att.get('content_type', '')
                fname = att['filename']
                PaperFile.create(
                    paper=paper,
                    path=fname,
                    hash='',
                    status=attachment_status(fname, ct),
                    zotero_key=att['key'],
                )

    _log(
        f'orphan_attachments ({n_orphan_atts} atts across '
        f'{len(orphan_attachments) if orphan_attachments else 0} parents) '
        f'took {time.perf_counter() - orphan_t0:.2f}s'
    )

    return new_count, updated_count


def backfill_missing_paperfiles(zotero_client, progress_callback=None, logger=None):
    """Dormant safety net — not wired into any sync path.

    For every Zotero-sourced Paper with no PaperFile in DB, fetches
    `zot.children()` and creates PaperFile rows for any attachments found.
    The previous version of `sync_zotero_items` called this at the end of
    every sync.

    Why it's now dormant (2026-06-05):
    - Introduced in commit 857a6d8 (devlog 029, 2026-04-16) to recover
      one historical case — 1 paper out of 9,877. A normal cold-start
      sync that pulls collections/items/attachments correctly reconstructs
      the parent/child relations without this, so the only way a paper
      ends up here is a bug in the main sync loop that we should fix there.
    - Each call does one API round-trip per "missing" paper. On a typical
      library most of those are reference-only items (no PDF intentionally),
      so the loop polled the same ~29 keys every sync for ~25s and added 0
      attachments. Pure overhead.

    Kept as a standalone function in case a similar one-shot recovery is
    ever needed again — call it explicitly from a script or REPL.
    """
    def _log(msg):
        if logger is not None:
            logger.info('backfill: %s', msg)

    t0 = time.perf_counter()
    n_checked = 0
    n_added = 0

    missing_file_papers = (
        Paper.select(Paper.id, Paper.zotero_key)
        .where(Paper.zotero_key != '')
        .where(~(Paper.id << PaperFile.select(PaperFile.paper).distinct()))
    )
    for mp in missing_file_papers:
        n_checked += 1
        try:
            children = zotero_client._zot.children(mp.zotero_key)
            for child in children:
                cdata = child.get('data', {})
                if cdata.get('itemType') != 'attachment':
                    continue
                existing_pf = PaperFile.select().where(
                    PaperFile.zotero_key == cdata['key'],
                ).first()
                if existing_pf:
                    if (
                        existing_pf.paper_id != mp.id
                        and existing_pf.paper.zotero_key == cdata['key']
                    ):
                        if progress_callback:
                            progress_callback(
                                f'  merging stale standalone Paper '
                                f'{existing_pf.paper_id} → {mp.id} '
                                f'({cdata.get("filename", cdata["key"])})'
                            )
                        _merge_stale_standalone(existing_pf.paper, mp)
                    _refresh_existing_attachment(existing_pf, cdata)
                    continue
                ct = cdata.get('contentType', '')
                fname = cdata.get('filename', cdata['key'])
                PaperFile.create(
                    paper=mp,
                    path=fname,
                    hash='',
                    status=attachment_status(fname, ct),
                    zotero_key=cdata['key'],
                )
                n_added += 1
                if progress_callback:
                    progress_callback(f'Backfilled attachment for "{mp.zotero_key}"')
        except Exception:
            pass  # network error — caller can re-run

    _log(
        f'{n_checked} papers checked via children API, '
        f'{n_added} new attachments, took {time.perf_counter() - t0:.2f}s'
    )
    return n_checked, n_added


def sync_trash_state(zotero_client, progress_callback=None):
    """Sync Zotero trash state to local `trashed_at` flags.

    Zotero's trash endpoint does not support `since`, so this fetches the full
    trash on each call. Trash typically stays small so the cost is acceptable.

    Two-way sync against the snapshot:
    - In Zotero trash AND locally `trashed_at IS NULL` → flag (newly trashed)
    - Locally `trashed_at IS NOT NULL` AND not in trash → clear (restored)

    Permanent deletion (empty-trash) is a separate concern, not handled here:
    a row whose Zotero key was purged from trash since the previous sync looks
    identical to a restore. Until the permanent-delete path is wired in, the
    flag will be silently cleared in that case, which is harmless (the row
    simply stays around as a dangling pointer to a no-longer-existing Zotero
    item; future operations against it will 404).

    Returns dict with counts for newly_trashed_papers, restored_papers,
    newly_trashed_files, restored_files.
    """
    if progress_callback:
        progress_callback('Fetching Zotero trash…')

    trash_keys = zotero_client.get_trash_keys()
    if progress_callback:
        progress_callback(f'Trash contains {len(trash_keys)} items')

    now = datetime.datetime.now()
    trash_list = list(trash_keys)

    with db.atomic():
        if trash_list:
            newly_trashed_p = Paper.update(trashed_at=now).where(
                (Paper.zotero_key.in_(trash_list))
                & (Paper.trashed_at.is_null())
            ).execute()
            restored_p = Paper.update(trashed_at=None).where(
                (Paper.trashed_at.is_null(False))
                & (Paper.zotero_key.not_in(trash_list))
            ).execute()
            newly_trashed_pf = PaperFile.update(trashed_at=now).where(
                (PaperFile.zotero_key.in_(trash_list))
                & (PaperFile.trashed_at.is_null())
            ).execute()
            restored_pf = PaperFile.update(trashed_at=None).where(
                (PaperFile.trashed_at.is_null(False))
                & (PaperFile.zotero_key.not_in(trash_list))
            ).execute()
        else:
            newly_trashed_p = 0
            newly_trashed_pf = 0
            restored_p = Paper.update(trashed_at=None).where(
                Paper.trashed_at.is_null(False)
            ).execute()
            restored_pf = PaperFile.update(trashed_at=None).where(
                PaperFile.trashed_at.is_null(False)
            ).execute()

    return {
        'newly_trashed_papers': newly_trashed_p,
        'restored_papers': restored_p,
        'newly_trashed_files': newly_trashed_pf,
        'restored_files': restored_pf,
    }


def fetch_zotero_collection_items(zotero_client, source, folder, progress_callback=None):
    """Fetch items from a Zotero collection. Single API call.

    Creates Paper records for all items, and PaperFile records for items with PDFs.
    Returns number of new papers created.
    """
    if progress_callback:
        progress_callback(f'Fetching items from "{folder.name}"...')

    items = zotero_client.get_collection_items(folder.zotero_key)
    new_count = 0

    for i, item in enumerate(items):
        if progress_callback:
            progress_callback(f'[{i + 1}/{len(items)}] {item["title"][:60]}')

        # Dedup: check by zotero parent item key first, then fall back to title
        # (title fallback only matches papers without a zotero_key — legacy
        # records from before Zotero sync was added.  Papers that already
        # have a different zotero_key are distinct Zotero items even if the
        # title happens to be the same.)
        existing_by_key = (
            Paper.select()
            .where(Paper.zotero_key == item['key'])
            .first()
        )
        if not existing_by_key:
            existing_by_key = (
                Paper.select()
                .where(
                    Paper.folder == folder,
                    Paper.title == item['title'],
                    Paper.zotero_key == '',
                )
                .first()
            )
            if existing_by_key:
                # Backfill zotero_key for legacy records
                existing_by_key.zotero_key = item['key']
                existing_by_key.save()

        if existing_by_key:
            paper = existing_by_key
            # Refresh authors from Zotero (fixes legacy "Last First" → "Last, First").
            new_authors = item.get('authors', [])
            existing_names = [
                a.name for a in
                Author.select(Author.name)
                .where(Author.paper == paper)
                .order_by(Author.order)
            ]
            if new_authors != existing_names:
                with db.atomic():
                    Author.delete().where(Author.paper == paper).execute()
                    for order, author_name in enumerate(new_authors):
                        Author.create(paper=paper, name=author_name, order=order)
        else:
            with db.atomic():
                paper = Paper.create(
                    title=item['title'],
                    date=item.get('date', ''),
                    year=item['year'],
                    journal=item.get('journal', ''),
                    doi=item.get('doi', ''),
                    folder=folder,
                    zotero_key=item['key'],
                )
                for order, author_name in enumerate(item['authors']):
                    Author.create(paper=paper, name=author_name, order=order)
            new_count += 1

        # Record multi-collection membership via PaperFolder.
        # Always register the current folder being synced.
        PaperFolder.get_or_create(paper=paper, folder=folder)
        # Also register any other collections the Zotero API reports.
        for col_key in item.get('collections', []):
            other_folder = Folder.select().where(
                Folder.source == source, Folder.zotero_key == col_key,
            ).first()
            if other_folder and other_folder.id != folder.id:
                PaperFolder.get_or_create(paper=paper, folder=other_folder)

        # Create PaperFile for each attachment (PDF, JSON, etc.)
        for att in item.get('attachments', []):
            existing_pf = PaperFile.select().where(
                PaperFile.zotero_key == att['key'],
            ).first()
            if not existing_pf:
                # JSON sibling → 'processed', PDF → 'pending', else → 'skipped'
                ct = att.get('content_type', '')
                fname = att['filename']
                PaperFile.create(
                    paper=paper,
                    path=fname,
                    hash='',
                    status=attachment_status(fname, ct),
                    zotero_key=att['key'],
                )

    return new_count
