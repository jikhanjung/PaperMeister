import json
import os
import tempfile

import fitz  # PyMuPDF

from .models import db, Paper, PaperFile, Passage, Author

OCR_JSON_DIR = os.path.join(os.path.expanduser('~'), '.papermeister', 'ocr_json')


def extract_metadata_from_pdf(filepath):
    """Extract title, author, year from PDF metadata."""
    doc = fitz.open(filepath)
    meta = doc.metadata or {}
    doc.close()

    title = meta.get('title', '').strip()
    author = meta.get('author', '').strip()

    year = None
    for key in ('creationDate', 'modDate'):
        date_str = meta.get(key, '')
        if date_str and len(date_str) >= 6:
            try:
                year_str = date_str.replace('D:', '')[:4]
                y = int(year_str)
                if 1900 <= y <= 2100:
                    year = y
                    break
            except (ValueError, IndexError):
                pass

    return {'title': title, 'author': author, 'year': year}


def split_into_passages(text, min_length=50):
    """Split page text into paragraph-level passages."""
    paragraphs = text.split('\n\n')
    passages = []
    current = []

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        current.append(p)
        joined = '\n'.join(current)
        if len(joined) >= min_length:
            passages.append(joined)
            current = []

    if current:
        joined = '\n'.join(current)
        if len(joined.strip()) > 10:
            passages.append(joined)

    if not passages and len(text.strip()) > 10:
        passages = [text.strip()]

    return passages


def _save_ocr_json(paper_file, raw_result):
    """Save raw OCR JSON to ~/.papermeister/ocr_json/{hash}.json (atomic write)."""
    os.makedirs(OCR_JSON_DIR, exist_ok=True)
    out_path = os.path.join(OCR_JSON_DIR, f'{paper_file.hash}.json')
    tmp = tempfile.NamedTemporaryFile(
        mode='w', dir=OCR_JSON_DIR, suffix='.tmp', delete=False, encoding='utf-8',
    )
    try:
        json.dump(raw_result, tmp, ensure_ascii=False, indent=2)
        tmp.close()
        os.replace(tmp.name, out_path)
    except Exception:
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise
    return out_path


def _load_ocr_json(paper_file):
    """Load cached raw OCR JSON if it exists. Returns raw_result dict or None."""
    path = os.path.join(OCR_JSON_DIR, f'{paper_file.hash}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


PAPERMEISTER_META_SCHEMA = 1


def record_biblio_applied(biblio):
    """Update papermeister_meta in the OCR JSON after a PaperBiblio reaches a
    terminal apply state ('applied' or 'auto_committed').

    Writes locally + (if a sibling JSON is enrolled in Zotero AND
    zotero_upload_ocr_json pref is on) pushes the new content back in-place
    via Zotero's "replace attachment file" flow (key preserved).

    Best-effort: any failure is swallowed. Caller should not need to handle.
    """
    import datetime
    try:
        _record_biblio_applied_impl(biblio)
    except Exception:
        # Diagnostic-only path; never let metadata sync break apply()
        pass


def _record_biblio_applied_impl(biblio):
    pdf_hash = (biblio.file_hash or '').strip()
    if not pdf_hash:
        return

    json_path = os.path.join(OCR_JSON_DIR, f'{pdf_hash}.json')
    if not os.path.exists(json_path):
        return

    import datetime
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    meta = data.get('papermeister_meta') or {}
    meta['schema_version'] = PAPERMEISTER_META_SCHEMA
    meta['biblio_state'] = biblio.status
    meta['biblio_source'] = biblio.source or ''
    meta['biblio_applied_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data['papermeister_meta'] = meta

    tmp = tempfile.NamedTemporaryFile(
        mode='w', dir=OCR_JSON_DIR, suffix='.tmp', delete=False, encoding='utf-8',
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.close()
        os.replace(tmp.name, json_path)
    except Exception:
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise

    # Push to Zotero if user opted in and a sibling JSON attachment exists
    from .preferences import get_pref
    if not get_pref('zotero_upload_ocr_json', False):
        return

    sibling = (
        PaperFile.select()
        .where(
            (PaperFile.paper == biblio.paper)
            & (PaperFile.path == f'{pdf_hash}.json')
            & (PaperFile.zotero_key.is_null(False))
        )
        .first()
    )
    if sibling is None:
        return

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        return

    from .zotero_client import ZoteroClient
    from .ingestion import hash_file
    client = ZoteroClient(user_id, api_key)
    outcome = client.replace_attachment_file(sibling.zotero_key, json_path)

    # Keep the local PaperFile row's hash consistent with the new content so
    # later diagnostics / dedupe don't see a stale (or empty) value.
    if outcome in ('updated', 'unchanged'):
        new_hash = hash_file(json_path)
        if new_hash and new_hash != (sibling.hash or ''):
            sibling.hash = new_hash
            sibling.save()


def _try_fetch_sibling_json(paper_file, status_callback=None):
    """If a sibling Zotero attachment named `{paper_file.hash}.json` exists,
    download it, write to the local OCR cache, and return the parsed dict.

    Returns None if no sibling found or if any step fails. Caller should
    fall through to OCR on None.
    """
    if not paper_file.zotero_key or not paper_file.hash:
        return None

    expected_name = f'{paper_file.hash}.json'
    sibling = (
        PaperFile
        .select()
        .where(
            (PaperFile.paper == paper_file.paper)
            & (PaperFile.path == expected_name)
            & (PaperFile.zotero_key.is_null(False))
        )
        .first()
    )
    if sibling is None or not sibling.zotero_key:
        return None

    from .preferences import get_pref
    from .zotero_client import ZoteroClient
    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        return None

    try:
        if status_callback:
            status_callback('Loading OCR JSON from Zotero...')
        client = ZoteroClient(user_id, api_key)
        content = client._zot.file(sibling.zotero_key)
        # pyzotero sniffs content-type: returns a dict for JSON attachments,
        # bytes for binary, str for plain text. Normalise.
        if isinstance(content, dict):
            raw_result = content
        elif isinstance(content, bytes):
            raw_result = json.loads(content.decode('utf-8'))
        else:
            raw_result = json.loads(content)
    except Exception as e:
        if status_callback:
            status_callback(f'Sibling JSON fetch failed: {e}')
        return None

    # Persist to local cache so subsequent runs hit fast and the OCR tab works.
    try:
        os.makedirs(OCR_JSON_DIR, exist_ok=True)
        out_path = os.path.join(OCR_JSON_DIR, expected_name)
        tmp = tempfile.NamedTemporaryFile(
            mode='w', dir=OCR_JSON_DIR, suffix='.tmp', delete=False, encoding='utf-8',
        )
        try:
            json.dump(raw_result, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            os.replace(tmp.name, out_path)
        except Exception:
            tmp.close()
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            raise
    except Exception:
        # Failed to persist — still return the in-memory result so this run succeeds.
        pass

    return raw_result


def _pages_from_raw(raw_result):
    """Extract (page_num, text) list from raw OCR result."""
    pages = []
    for page_data in raw_result.get('pages', []):
        text = (
            page_data.get('markdown')
            or page_data.get('text')
            or ''
        ).strip()
        page_num = page_data.get('page', 0) + 1  # 0-based → 1-based
        if text:
            pages.append((page_num, text))
    return pages


def _resolve_filepath(paper_file):
    """Return (filepath, is_temp) for a PaperFile.

    For Zotero files, downloads to pdf_cache so the PDF tab can reuse it.
    """
    if paper_file.zotero_key:
        # Check pdf_cache first
        filename = paper_file.path or f'{paper_file.zotero_key}.pdf'
        cache_dir = os.path.join(
            os.path.expanduser('~'), '.papermeister', 'pdf_cache',
            paper_file.zotero_key,
        )
        cached_path = os.path.join(cache_dir, filename)
        if os.path.isfile(cached_path):
            return cached_path, False

        # Download to pdf_cache
        from .preferences import get_pref
        from .zotero_client import ZoteroClient
        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')
        if not user_id or not api_key:
            raise RuntimeError('Zotero credentials not configured')
        client = ZoteroClient(user_id, api_key)
        content = client._zot.file(paper_file.zotero_key)
        os.makedirs(cache_dir, exist_ok=True)
        with open(cached_path, 'wb') as f:
            f.write(content)
        return cached_path, False
    return paper_file.path, False


def process_paper_file(paper_file, ocr_progress_callback=None, status_callback=None):
    """OCR a PDF via RunPod (or use cached JSON), store text in DB and FTS index.

    status_callback(msg): called with human-readable status at each stage.
    """
    paper = paper_file.paper
    is_zotero = bool(paper_file.zotero_key)

    filepath = None
    is_temp = False

    # Zotero files: download first to fill hash, then check cache
    if is_zotero and not paper_file.hash:
        if status_callback:
            status_callback('Downloading PDF from Zotero...')
        filepath, is_temp = _resolve_filepath(paper_file)
        from .ingestion import hash_file
        paper_file.hash = hash_file(filepath)
        paper_file.save()

    raw_result = _load_ocr_json(paper_file)

    if raw_result is None and is_zotero:
        # Cross-machine / post-cache-wipe shortcut: a previous run may have
        # uploaded `{hash}.json` as a Zotero sibling attachment. Pull it down
        # instead of paying for OCR again.
        raw_result = _try_fetch_sibling_json(paper_file, status_callback=status_callback)

    if raw_result:
        if status_callback:
            status_callback('Loading from OCR cache...')
        pages = _pages_from_raw(raw_result)
    else:
        # Need the actual file for OCR
        if filepath is None:
            if is_zotero:
                if status_callback:
                    status_callback('Downloading PDF from Zotero...')
            filepath, is_temp = _resolve_filepath(paper_file)
        try:
            if status_callback:
                status_callback('Running OCR...')
            from .ocr import ocr_pdf
            ocr_results, raw_result = ocr_pdf(filepath, progress_callback=ocr_progress_callback)
            _save_ocr_json(paper_file, raw_result)
            pages = [(r['page'], r['text']) for r in ocr_results]
        except Exception:
            if is_temp and filepath:
                _cleanup_temp(filepath)
            raise

    # Extract metadata from PDF if we have the file and it's not a Zotero item
    # (Zotero items already have metadata from the API)
    meta = None
    if not is_zotero:
        if filepath is None:
            filepath = paper_file.path
        meta = extract_metadata_from_pdf(filepath)

    # Clean up temp file now that OCR is done
    if is_temp and filepath:
        _cleanup_temp(filepath)

    with db.atomic():
        # Clear existing passages and FTS data for reprocessing
        db.execute_sql('DELETE FROM passage_fts WHERE paper_id = ?', [paper.id])
        Passage.delete().where(Passage.paper == paper).execute()

        if is_zotero:
            # Zotero metadata was set during import; build authors_str from existing records
            authors = Author.select().where(Author.paper == paper).order_by(Author.order)
            authors_str = ', '.join(a.name for a in authors)
        else:
            # Directory import: use PDF metadata
            Author.delete().where(Author.paper == paper).execute()
            if meta and meta['title']:
                paper.title = meta['title']
            if meta and meta['year']:
                paper.year = meta['year']
            paper.save()

            authors_str = ''
            if meta and meta['author']:
                names = [n.strip() for n in meta['author'].split(';') if n.strip()]
                for i, name in enumerate(names):
                    Author.create(paper=paper, name=name, order=i)
                authors_str = ', '.join(names)

        for page_num, text in pages:
            for passage_text in split_into_passages(text):
                passage = Passage.create(
                    paper=paper,
                    page=page_num,
                    text=passage_text,
                )
                db.execute_sql(
                    'INSERT INTO passage_fts(paper_id, page, passage_id, title, authors, text) '
                    'VALUES(?, ?, ?, ?, ?, ?)',
                    [paper.id, page_num, passage.id, paper.title, authors_str, passage_text],
                )

        paper_file.status = 'processed'
        paper_file.save()

    # Promote standalone PDFs to parent items so subsequent JSON upload
    # has a real parent to attach under. Skips no-op for already-parented
    # PDFs. Opt-out via `auto_promote_standalone` pref.
    from .preferences import get_pref
    if (
        is_zotero
        and paper.zotero_key
        and paper.zotero_key == paper_file.zotero_key
        and get_pref('auto_promote_standalone', True)
    ):
        try:
            from .zotero_client import ZoteroClient
            from .zotero_writeback import promote_standalone_with_filename
            user_id = get_pref('zotero_user_id', '')
            api_key = get_pref('zotero_api_key', '')
            if user_id and api_key:
                if status_callback:
                    status_callback('Creating Zotero parent item (filename as title)...')
                client = ZoteroClient(user_id, api_key)
                new_parent_key = promote_standalone_with_filename(
                    paper_file, client=client,
                )
                if new_parent_key and status_callback:
                    status_callback(f'  → parent created: {new_parent_key}')
        except Exception as e:
            if status_callback:
                status_callback(f'Parent item creation failed: {e}')

    # Upload OCR JSON as Zotero sibling attachment (opt-in, best-effort).
    # Match per PDF (by hash-based filename), not "any JSON on this paper" —
    # a parent item with multiple PDF children needs one JSON per PDF.
    if is_zotero and get_pref('zotero_upload_ocr_json', False) and paper_file.hash:
        json_filename = f'{paper_file.hash}.json'
        existing_json = (
            PaperFile.select()
            .where(
                (PaperFile.paper == paper)
                & (PaperFile.path == json_filename)
            )
            .first()
        )
        if not existing_json:
            try:
                if status_callback:
                    status_callback('Uploading OCR JSON to Zotero...')
                _upload_ocr_json_to_zotero(paper_file)
            except Exception as e:
                if status_callback:
                    status_callback(f'OCR JSON upload failed: {e}')

    return paper


def _upload_ocr_json_to_zotero(paper_file):
    """Upload cached OCR JSON as a sibling Zotero attachment.

    On success, creates a new PaperFile row for the JSON attachment.
    """
    json_path = os.path.join(OCR_JSON_DIR, f'{paper_file.hash}.json')
    if not os.path.exists(json_path):
        return

    from .preferences import get_pref
    from .zotero_client import ZoteroClient
    from .ingestion import hash_file
    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        return

    client = ZoteroClient(user_id, api_key)
    new_key = client.upload_sibling_attachment(paper_file.zotero_key, json_path)
    if not new_key:
        return

    PaperFile.create(
        paper=paper_file.paper,
        path=os.path.basename(json_path),
        hash=hash_file(json_path),
        status='processed',
        zotero_key=new_key,
    )


def _cleanup_temp(filepath):
    """Remove a temp file."""
    try:
        os.unlink(filepath)
    except OSError:
        pass
