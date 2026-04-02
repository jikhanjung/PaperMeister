import hashlib
import os
import shutil
from pathlib import Path

from .models import db, Source, Folder, Paper, Author, PaperFile


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
        existing_by_key = (
            Paper.select()
            .where(Paper.zotero_key == item['key'])
            .first()
        )
        if not existing_by_key:
            existing_by_key = (
                Paper.select()
                .where(Paper.folder == folder, Paper.title == item['title'])
                .first()
            )
            if existing_by_key and not existing_by_key.zotero_key:
                # Backfill zotero_key for legacy records
                existing_by_key.zotero_key = item['key']
                existing_by_key.save()

        if existing_by_key:
            paper = existing_by_key
        else:
            with db.atomic():
                paper = Paper.create(
                    title=item['title'],
                    year=item['year'],
                    journal=item.get('journal', ''),
                    doi=item.get('doi', ''),
                    folder=folder,
                    zotero_key=item['key'],
                )
                for order, author_name in enumerate(item['authors']):
                    Author.create(paper=paper, name=author_name, order=order)
            new_count += 1

        # Create PaperFile for each PDF attachment
        for att in item.get('attachments', []):
            existing_pf = PaperFile.select().where(
                PaperFile.zotero_key == att['key'],
            ).first()
            if not existing_pf:
                PaperFile.create(
                    paper=paper,
                    path=att['filename'],
                    hash='',
                    status='pending',
                    zotero_key=att['key'],
                )

    return new_count
