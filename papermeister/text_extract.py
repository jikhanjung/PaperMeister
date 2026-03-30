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

    For Zotero files, downloads to a temp location. Caller must clean up if is_temp.
    """
    if paper_file.zotero_key:
        from .preferences import get_pref
        from .zotero_client import ZoteroClient
        user_id = get_pref('zotero_user_id', '')
        api_key = get_pref('zotero_api_key', '')
        if not user_id or not api_key:
            raise RuntimeError('Zotero credentials not configured')
        client = ZoteroClient(user_id, api_key)
        tmp_path = client.download_attachment(paper_file.zotero_key)
        return tmp_path, True
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

    return paper


def _cleanup_temp(filepath):
    """Remove a temp file."""
    try:
        os.unlink(filepath)
    except OSError:
        pass
