#!/usr/bin/env python3
"""PaperMeister CLI — command-line interface for managing academic papers."""

import argparse
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from papermeister.database import init_db
from papermeister.models import (
    Author, Folder, Paper, PaperFile, Passage, Source,
)


def _init():
    """Initialize DB (call before any command)."""
    init_db()


# ── import ──────────────────────────────────────────────────

def cmd_import(args):
    """Import a directory of PDFs."""
    import os
    from papermeister.ingestion import import_source_directory

    dir_path = os.path.abspath(args.path)
    if not os.path.isdir(dir_path):
        print(f'Error: {dir_path} is not a directory', file=sys.stderr)
        return 1

    print(f'Scanning {dir_path} ...')
    source, new_files = import_source_directory(
        dir_path,
        progress_callback=lambda msg: print(f'  {msg}'),
    )
    print(f'Done. Source: {source.name} (id={source.id})')
    print(f'  New files: {len(new_files)}')
    if new_files:
        print(f'  Run "python cli.py process" to OCR pending files.')
    return 0


# ── process ─────────────────────────────────────────────────

def _get_pending_files(folder_id=None, collection=None):
    """Get pending PaperFiles, optionally filtered by folder or collection."""
    query = PaperFile.select(PaperFile, Paper).join(Paper).where(PaperFile.status == 'pending')

    if folder_id:
        query = query.where(Paper.folder_id == folder_id)
    elif collection:
        # Find folder by zotero_key or name
        folder = Folder.select().where(Folder.zotero_key == collection).first()
        if not folder:
            folder = Folder.select().where(Folder.name == collection).first()
        if not folder:
            print(f'Error: Collection "{collection}" not found.', file=sys.stderr)
            return None
        query = query.where(Paper.folder_id == folder.id)

    return list(query)


def _run_process(pending):
    """Process a list of pending PaperFiles with parallel OCR."""
    from papermeister.ocr import ensure_workers_ready, get_worker_status
    from papermeister.text_extract import process_paper_file

    if not pending:
        print('No pending files.')
        return 0

    print(f'{len(pending)} pending file(s).')

    # Wake RunPod workers
    print('Checking RunPod workers...')
    try:
        ensure_workers_ready()
    except RuntimeError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1

    status = get_worker_status()
    max_concurrent = max(1, min(status['idle'], 10))
    print(f'Workers: {status["idle"]} idle, {status["running"]} running → parallel: {max_concurrent}')

    counter = {'done': 0, 'failed': 0}
    counter_lock = threading.Lock()
    total = len(pending)

    def process_one(pf):
        name = os.path.basename(pf.path)
        with counter_lock:
            idx = counter['done'] + counter['failed'] + 1
        prefix = f'[{idx}/{total}]'
        print(f'{prefix} {name}')
        try:
            process_paper_file(
                pf,
                ocr_progress_callback=lambda c, t, msg: print(f'{prefix}   {msg}'),
                status_callback=lambda msg: print(f'{prefix}   {msg}'),
            )
            with counter_lock:
                counter['done'] += 1
            print(f'{prefix}   Done: {name}')
        except Exception as e:
            pf.status = 'failed'
            pf.save()
            with counter_lock:
                counter['failed'] += 1
            print(f'{prefix}   FAILED: {e}')

    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        futures = [pool.submit(process_one, pf) for pf in pending]
        for f in as_completed(futures):
            pass

    print(f'\nComplete: {counter["done"]} processed, {counter["failed"]} failed.')
    return 0


def cmd_process(args):
    """Process pending papers (OCR via RunPod)."""
    pending = _get_pending_files(
        folder_id=getattr(args, 'folder', None),
        collection=getattr(args, 'collection', None),
    )
    if pending is None:
        return 1
    return _run_process(pending)


# ── search ──────────────────────────────────────────────────

def cmd_search(args):
    """Full-text search over indexed papers."""
    from papermeister.search import search

    results = search(args.query, limit=args.limit)
    if not results:
        print('No results.')
        return 0

    for r in results:
        paper = r['paper']
        authors = Author.select().where(Author.paper == paper).order_by(Author.order)
        authors_str = ', '.join(a.name for a in authors)

        year_str = f' ({paper.year})' if paper.year else ''
        print(f'\n--- {paper.title}{year_str} [id={paper.id}]')
        if authors_str:
            print(f'    Authors: {authors_str}')

        for m in r['matches']:
            snippet = m['snippet'].replace('\n', ' ')
            print(f'    p.{m["page"]}: {snippet}')

    print(f'\n{len(results)} paper(s) matched.')
    return 0


# ── list ────────────────────────────────────────────────────

def cmd_list(args):
    """List sources, papers, or pending files."""
    what = args.what

    if what == 'sources':
        sources = Source.select()
        if not sources:
            print('No sources.')
            return 0
        for s in sources:
            paper_count = (
                Paper.select()
                .join(Folder)
                .where(Folder.source == s)
                .count()
            )
            print(f'  [{s.id}] {s.name} ({s.source_type}) — {paper_count} papers')

    elif what == 'papers':
        query = Paper.select().order_by(Paper.created_at.desc())
        if args.source:
            query = (
                query.join(Folder)
                .where(Folder.source_id == args.source)
            )
        if args.folder:
            query = query.where(Paper.folder_id == args.folder)

        papers = list(query.limit(args.limit))
        if not papers:
            print('No papers.')
            return 0
        for p in papers:
            pf = PaperFile.select().where(PaperFile.paper == p).first()
            status = pf.status if pf else 'no PDF'
            year_str = f' ({p.year})' if p.year else ''
            print(f'  [{p.id}] {p.title}{year_str} [{status}]')
        print(f'\n{len(papers)} paper(s).')

    elif what == 'pending':
        pending = list(
            PaperFile.select(PaperFile, Paper)
            .join(Paper)
            .where(PaperFile.status == 'pending')
        )
        if not pending:
            print('No pending files.')
            return 0
        for pf in pending:
            print(f'  [{pf.id}] {pf.paper.title} — {pf.path}')
        print(f'\n{len(pending)} pending file(s).')

    elif what == 'folders':
        source_id = args.source
        if source_id:
            folders = Folder.select().where(Folder.source_id == source_id).order_by(Folder.name)
        else:
            folders = Folder.select().order_by(Folder.name)
        if not folders:
            print('No folders.')
            return 0
        for f in folders:
            parent_str = f' (parent={f.parent_id})' if f.parent_id else ''
            paper_count = Paper.select().where(Paper.folder == f).count()
            print(f'  [{f.id}] {f.name}{parent_str} — {paper_count} papers')

    return 0


# ── show ────────────────────────────────────────────────────

def cmd_show(args):
    """Show details for a paper."""
    try:
        paper = Paper.get_by_id(args.paper_id)
    except Paper.DoesNotExist:
        print(f'Paper id={args.paper_id} not found.', file=sys.stderr)
        return 1

    authors = Author.select().where(Author.paper == paper).order_by(Author.order)
    authors_str = ', '.join(a.name for a in authors)

    print(f'Title:   {paper.title}')
    if authors_str:
        print(f'Authors: {authors_str}')
    if paper.year:
        print(f'Year:    {paper.year}')
    if paper.journal:
        print(f'Journal: {paper.journal}')
    if paper.doi:
        print(f'DOI:     {paper.doi}')

    pf = PaperFile.select().where(PaperFile.paper == paper).first()
    if pf:
        print(f'File:    {pf.path}')
        print(f'Status:  {pf.status}')
        print(f'Hash:    {pf.hash[:16]}...' if pf.hash else 'Hash:    (none)')

    passages = list(
        Passage.select()
        .where(Passage.paper == paper)
        .order_by(Passage.page)
    )
    print(f'Passages: {len(passages)}')

    if args.text and passages:
        print('\n--- Text ---')
        current_page = None
        for p in passages:
            if p.page != current_page:
                current_page = p.page
                print(f'\n[Page {p.page}]')
            print(p.text)

    return 0


# ── config ──────────────────────────────────────────────────

def cmd_config(args):
    """Get or set preferences."""
    from papermeister.preferences import get_pref, set_pref

    if args.action == 'get':
        if args.key:
            val = get_pref(args.key)
            if val is None:
                print(f'{args.key}: (not set)')
            else:
                print(f'{args.key}: {val}')
        else:
            # Show all
            import json
            from papermeister.preferences import _load
            data = _load()
            if not data:
                print('No preferences set.')
            else:
                for k, v in sorted(data.items()):
                    # Mask sensitive values
                    if 'key' in k.lower() or 'api' in k.lower():
                        display = v[:4] + '***' if v and len(v) > 4 else '***'
                    else:
                        display = v
                    print(f'  {k}: {display}')

    elif args.action == 'set':
        if not args.key or args.value is None:
            print('Usage: cli.py config set KEY VALUE', file=sys.stderr)
            return 1
        set_pref(args.key, args.value)
        print(f'Set {args.key}.')

    return 0


# ── status ──────────────────────────────────────────────────

def cmd_status(args):
    """Show database and system status."""
    source_count = Source.select().count()
    paper_count = Paper.select().count()
    pending_count = PaperFile.select().where(PaperFile.status == 'pending').count()
    processed_count = PaperFile.select().where(PaperFile.status == 'processed').count()
    failed_count = PaperFile.select().where(PaperFile.status == 'failed').count()
    passage_count = Passage.select().count()

    print('PaperMeister Status')
    print(f'  Sources:    {source_count}')
    print(f'  Papers:     {paper_count}')
    print(f'  Files:      {pending_count} pending, {processed_count} processed, {failed_count} failed')
    print(f'  Passages:   {passage_count}')

    if args.ocr:
        print()
        try:
            from papermeister.ocr import get_worker_status
            ws = get_worker_status()
            print(f'  RunPod:     idle={ws["idle"]}, running={ws["running"]}, throttled={ws["throttled"]}')
        except Exception as e:
            print(f'  RunPod:     Error — {e}')

    return 0


# ── zotero ──────────────────────────────────────────────────

def _find_zotero_folder(source, collection_str):
    """Find a Zotero folder by key or name. Returns folder or None."""
    folder = Folder.select().where(
        Folder.source == source,
        Folder.zotero_key == collection_str,
    ).first()
    if not folder:
        folder = Folder.select().where(
            Folder.source == source,
            Folder.name == collection_str,
        ).first()
    return folder


def _resolve_zotero_folders(source, collection_str=None):
    """Resolve collection arg to folder list. Returns (folders, error_msg)."""
    if collection_str:
        folder = _find_zotero_folder(source, collection_str)
        if not folder:
            return None, f'Collection "{collection_str}" not found. Run "python cli.py zotero sync" first.'
        return [folder], None
    else:
        folders = list(Folder.select().where(
            Folder.source == source,
            Folder.zotero_key != '',
        ))
        if not folders:
            return None, 'No Zotero collections found. Run "python cli.py zotero sync" first.'
        return folders, None


def cmd_zotero(args):
    """Zotero operations: sync collections or fetch items."""
    from papermeister.preferences import get_pref

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.', file=sys.stderr)
        print('Run: python cli.py config set zotero_user_id YOUR_ID', file=sys.stderr)
        print('Run: python cli.py config set zotero_api_key YOUR_KEY', file=sys.stderr)
        return 1

    from papermeister.ingestion import (
        fetch_zotero_collection_items,
        get_or_create_zotero_source,
        sync_zotero_collections,
    )
    from papermeister.zotero_client import ZoteroClient

    client = ZoteroClient(user_id, api_key)

    if args.zotero_action == 'sync':
        saved_version = get_pref('zotero_library_version')
        print(f'Syncing Zotero collections (version: {saved_version or "first sync"})...')
        source = get_or_create_zotero_source(user_id)
        if saved_version and not args.full:
            collections = client.get_collections(since=saved_version)
            if collections is None:
                print('No changes since last sync.')
                return 0
        else:
            collections = client.get_collections()
        sync_zotero_collections(client, source, collections)
        new_ver = get_pref('zotero_library_version')
        print(f'Synced {len(collections)} collection(s). (version: {new_ver})')
        for col in collections:
            print(f'  {col["name"]} ({col["key"]})')

    elif args.zotero_action == 'fetch':
        source = get_or_create_zotero_source(user_id)
        folders, err = _resolve_zotero_folders(source, getattr(args, 'collection', None))
        if err:
            print(f'Error: {err}', file=sys.stderr)
            return 1

        total_new = 0
        for folder in folders:
            new = fetch_zotero_collection_items(
                client, source, folder,
                progress_callback=lambda msg: print(f'  {msg}'),
            )
            total_new += new
            print(f'  {folder.name}: {new} new paper(s)')

        print(f'\nTotal new papers: {total_new}')
        if total_new:
            print('Run "python cli.py process" to OCR pending files.')

    elif args.zotero_action == 'run':
        source = get_or_create_zotero_source(user_id)
        folders, err = _resolve_zotero_folders(source, getattr(args, 'collection', None))
        if err:
            print(f'Error: {err}', file=sys.stderr)
            return 1

        # Step 1: Fetch
        total_new = 0
        for folder in folders:
            print(f'Fetching "{folder.name}"...')
            new = fetch_zotero_collection_items(
                client, source, folder,
                progress_callback=lambda msg: print(f'  {msg}'),
            )
            total_new += new
            if new:
                print(f'  {new} new paper(s)')
        print(f'Fetch complete: {total_new} new paper(s).')

        # Step 2: Process pending in these folders
        folder_ids = [f.id for f in folders]
        pending = list(
            PaperFile.select(PaperFile, Paper)
            .join(Paper)
            .where(PaperFile.status == 'pending', Paper.folder_id.in_(folder_ids))
        )
        if pending:
            print(f'\nProcessing {len(pending)} pending file(s)...')
            _run_process(pending)
        else:
            print('No pending files to process.')

    elif args.zotero_action == 'collections':
        source = get_or_create_zotero_source(user_id)
        folders = list(Folder.select().where(
            Folder.source == source,
            Folder.zotero_key != '',
        ).order_by(Folder.name))
        if not folders:
            print('No collections synced. Run "python cli.py zotero sync" first.')
            return 0

        last_sync = get_pref('zotero_last_sync', '')
        saved_version = get_pref('zotero_library_version', '')
        if last_sync:
            print(f'  Last sync: {last_sync[:19]}  (version: {saved_version})')

        _collection_table(folders, page=args.page, page_size=args.page_size)

    return 0


# ── interactive ─────────────────────────────────────────────

def _prompt(msg, default=''):
    """Simple input prompt with default value."""
    if default:
        s = input(f'{msg} [{default}]: ').strip()
        return s or default
    return input(f'{msg}: ').strip()


def _collection_table(folders, page=1, page_size=20):
    """Print a numbered table of collections with status info and pagination."""
    rows = []
    for f in folders:
        total = Paper.select().where(Paper.folder == f).count()
        pending = (
            PaperFile.select()
            .join(Paper)
            .where(Paper.folder == f, PaperFile.status == 'pending')
            .count()
        )
        processed = (
            PaperFile.select()
            .join(Paper)
            .where(Paper.folder == f, PaperFile.status == 'processed')
            .count()
        )
        failed = (
            PaperFile.select()
            .join(Paper)
            .where(Paper.folder == f, PaperFile.status == 'failed')
            .count()
        )
        rows.append((f, total, pending, processed, failed))

    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    # Header
    print()
    print(f'  {"#":>3}  {"Collection":<40} {"Papers":>6} {"Pending":>8} {"Done":>6} {"Fail":>6}')
    print(f'  {"─"*3}  {"─"*40} {"─"*6} {"─"*8} {"─"*6} {"─"*6}')
    for i, (f, total, pending, processed, failed) in enumerate(page_rows, start + 1):
        name = f.name[:40]
        print(f'  {i:>3}  {name:<40} {total:>6} {pending:>8} {processed:>6} {failed:>6}')

    if total_pages > 1:
        print(f'\n  Page {page}/{total_pages} (showing {start+1}-{start+len(page_rows)} of {len(rows)})')
    print()
    return rows, page, total_pages


def cmd_interactive(args):
    """Interactive mode: sync Zotero, browse collections, fetch & process."""
    from papermeister.preferences import get_pref

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Zotero credentials not configured.')
        user_id = _prompt('Zotero User ID')
        api_key = _prompt('Zotero API Key')
        if not user_id or not api_key:
            print('Aborted.')
            return 1
        from papermeister.preferences import set_pref
        set_pref('zotero_user_id', user_id)
        set_pref('zotero_api_key', api_key)
        print('Credentials saved.')

    from papermeister.ingestion import (
        fetch_zotero_collection_items,
        get_or_create_zotero_source,
        sync_zotero_collections,
    )
    from papermeister.zotero_client import ZoteroClient

    client = ZoteroClient(user_id, api_key)
    source = get_or_create_zotero_source(user_id)

    # Step 1: Sync collections (incremental if possible)
    saved_version = get_pref('zotero_library_version')
    print(f'Syncing Zotero collections (version: {saved_version or "first sync"})...')
    try:
        if saved_version:
            collections = client.get_collections(since=saved_version)
            if collections is None:
                print('No changes since last sync.')
            else:
                sync_zotero_collections(client, source, collections)
                new_ver = get_pref('zotero_library_version')
                print(f'Updated {len(collections)} collection(s). (version: {new_ver})')
        else:
            collections = client.get_collections()
            sync_zotero_collections(client, source, collections)
            new_ver = get_pref('zotero_library_version')
            print(f'Synced {len(collections)} collection(s). (version: {new_ver})')
    except Exception as e:
        print(f'Sync failed: {e}')
        last_sync = get_pref('zotero_last_sync', '')
        if last_sync:
            print(f'Using cached collections (last sync: {last_sync[:19]}, version: {saved_version})')
        else:
            print('Using cached collections.')

    current_page = 1
    page_size = 20

    while True:
        # Reload folders each loop
        folders = list(Folder.select().where(
            Folder.source == source,
            Folder.zotero_key != '',
        ).order_by(Folder.name))

        if not folders:
            print('No collections found.')
            return 0

        last_sync = get_pref('zotero_last_sync', '')
        if last_sync:
            print(f'  Last sync: {last_sync[:19]}')

        rows, current_page, total_pages = _collection_table(folders, page=current_page, page_size=page_size)

        total_pending = sum(r[2] for r in rows)
        total_papers = sum(r[1] for r in rows)
        print(f'  Total: {total_papers} papers, {total_pending} pending')
        print()
        print('  Commands:')
        print('    <number>    Select collection → fetch & process')
        print('    f <number>  Fetch items only (no OCR)')
        print('    p <number>  Process (OCR) pending files only')
        print('    fa          Fetch ALL collections')
        print('    pa          Process ALL pending files')
        print('    s <query>   Search')
        if total_pages > 1:
            print('    n           Next page')
            print('    b           Previous page')
        print('    q           Quit')
        print()

        try:
            cmd = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            continue

        if cmd.lower() == 'q':
            break

        # ── pagination ──
        if cmd.lower() == 'n':
            if current_page < total_pages:
                current_page += 1
            else:
                print('Already on the last page.')
            continue

        if cmd.lower() == 'b':
            if current_page > 1:
                current_page -= 1
            else:
                print('Already on the first page.')
            continue

        # ── search ──
        if cmd.lower().startswith('s '):
            query = cmd[2:].strip()
            if query:
                from papermeister.search import search
                results = search(query, limit=20)
                if not results:
                    print('No results.')
                else:
                    for r in results:
                        paper = r['paper']
                        year_str = f' ({paper.year})' if paper.year else ''
                        print(f'\n  {paper.title}{year_str}')
                        for m in r['matches']:
                            snippet = m['snippet'].replace('\n', ' ')
                            print(f'    p.{m["page"]}: {snippet}')
                    print(f'\n  {len(results)} paper(s) matched.')
            continue

        # ── fetch all ──
        if cmd.lower() == 'fa':
            print(f'\nFetching all {len(folders)} collection(s)...')
            total_new = 0
            for folder in folders:
                new = fetch_zotero_collection_items(
                    client, source, folder,
                    progress_callback=lambda msg: print(f'  {msg}'),
                )
                total_new += new
                if new:
                    print(f'  {folder.name}: {new} new')
            print(f'Fetch complete: {total_new} new paper(s).')
            continue

        # ── process all ──
        if cmd.lower() == 'pa':
            pending = _get_pending_files()
            _run_process(pending)
            continue

        # ── f <num> — fetch specific ──
        if cmd.lower().startswith('f '):
            try:
                idx = int(cmd.split()[1]) - 1
                folder = folders[idx]
            except (ValueError, IndexError):
                print('Invalid number.')
                continue
            print(f'\nFetching "{folder.name}"...')
            new = fetch_zotero_collection_items(
                client, source, folder,
                progress_callback=lambda msg: print(f'  {msg}'),
            )
            print(f'Fetch complete: {new} new paper(s).')
            continue

        # ── p <num> — process specific ──
        if cmd.lower().startswith('p '):
            try:
                idx = int(cmd.split()[1]) - 1
                folder = folders[idx]
            except (ValueError, IndexError):
                print('Invalid number.')
                continue
            pending = _get_pending_files(folder_id=folder.id)
            if not pending:
                print(f'No pending files in "{folder.name}".')
            else:
                print(f'\nProcessing "{folder.name}" ({len(pending)} pending)...')
                _run_process(pending)
            continue

        # ── <num> — fetch + process ──
        try:
            idx = int(cmd) - 1
            folder = folders[idx]
        except (ValueError, IndexError):
            print('Unknown command. Type q to quit.')
            continue

        print(f'\n=== {folder.name} ===')

        # Fetch
        print('Fetching items...')
        new = fetch_zotero_collection_items(
            client, source, folder,
            progress_callback=lambda msg: print(f'  {msg}'),
        )
        print(f'Fetched: {new} new paper(s).')

        # Process
        pending = _get_pending_files(folder_id=folder.id)
        if pending:
            answer = _prompt(f'Process {len(pending)} pending file(s)? (y/n)', 'y')
            if answer.lower() in ('y', 'yes', ''):
                _run_process(pending)
        else:
            print('No pending files to process.')

    return 0


# ── main parser ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog='papermeister',
        description='PaperMeister CLI — manage academic papers from the command line',
    )
    sub = parser.add_subparsers(dest='command')

    # interactive (default when no subcommand)
    sub.add_parser('interactive', help='Interactive mode (default)')

    # import
    p = sub.add_parser('import', help='Import a directory of PDFs')
    p.add_argument('path', help='Directory path to import')

    # process
    p = sub.add_parser('process', help='OCR pending papers via RunPod')
    p.add_argument('-f', '--folder', type=int, help='Filter by folder ID')
    p.add_argument('-c', '--collection', help='Filter by collection name or key')

    # search
    p = sub.add_parser('search', help='Full-text search')
    p.add_argument('query', help='Search query')
    p.add_argument('-n', '--limit', type=int, default=20, help='Max results (default: 20)')

    # list
    p = sub.add_parser('list', help='List sources, papers, pending, or folders')
    p.add_argument('what', choices=['sources', 'papers', 'pending', 'folders'],
                   help='What to list')
    p.add_argument('-s', '--source', type=int, help='Filter by source ID')
    p.add_argument('-f', '--folder', type=int, help='Filter by folder ID')
    p.add_argument('-n', '--limit', type=int, default=50, help='Max results (default: 50)')

    # show
    p = sub.add_parser('show', help='Show paper details')
    p.add_argument('paper_id', type=int, help='Paper ID')
    p.add_argument('-t', '--text', action='store_true', help='Show full text')

    # config
    p = sub.add_parser('config', help='Get or set preferences')
    p.add_argument('action', choices=['get', 'set'], help='get or set')
    p.add_argument('key', nargs='?', help='Preference key')
    p.add_argument('value', nargs='?', help='Value to set')

    # status
    p = sub.add_parser('status', help='Show database status')
    p.add_argument('--ocr', action='store_true', help='Also check RunPod worker status')

    # zotero
    p = sub.add_parser('zotero', help='Zotero operations')
    zsub = p.add_subparsers(dest='zotero_action', required=True)
    zs = zsub.add_parser('sync', help='Sync Zotero collections')
    zs.add_argument('--full', action='store_true', help='Force full sync (ignore version)')
    zf = zsub.add_parser('fetch', help='Fetch items from Zotero collection(s)')
    zf.add_argument('-c', '--collection', help='Collection key or name (default: all)')
    zr = zsub.add_parser('run', help='Fetch + OCR in one step')
    zr.add_argument('-c', '--collection', help='Collection key or name (default: all)')
    zc = zsub.add_parser('collections', help='List synced Zotero collections')
    zc.add_argument('--page', type=int, default=1, help='Page number (default: 1)')
    zc.add_argument('--page-size', type=int, default=20, help='Items per page (default: 20)')

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    _init()

    # Default to interactive mode
    if not args.command or args.command == 'interactive':
        return cmd_interactive(args)

    cmd_map = {
        'import': cmd_import,
        'process': cmd_process,
        'search': cmd_search,
        'list': cmd_list,
        'show': cmd_show,
        'config': cmd_config,
        'status': cmd_status,
        'zotero': cmd_zotero,
    }

    return cmd_map[args.command](args)


if __name__ == '__main__':
    sys.exit(main() or 0)
