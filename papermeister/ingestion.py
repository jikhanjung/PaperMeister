import hashlib
import os
from pathlib import Path

from .models import db, Source, Folder, Paper, PaperFile


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
