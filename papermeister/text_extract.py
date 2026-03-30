import fitz  # PyMuPDF
from .models import db, Paper, PaperFile, Passage, Author


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


def process_paper_file(paper_file, ocr_progress_callback=None):
    """OCR a PDF via RunPod, extract metadata, store in DB and FTS index."""
    filepath = paper_file.path
    paper = paper_file.paper
    meta = extract_metadata_from_pdf(filepath)

    from .ocr import ocr_pdf
    ocr_results = ocr_pdf(filepath, progress_callback=ocr_progress_callback)
    pages = [(r['page'], r['text']) for r in ocr_results]

    with db.atomic():
        if meta['title']:
            paper.title = meta['title']
        if meta['year']:
            paper.year = meta['year']
        paper.save()

        authors_str = ''
        if meta['author']:
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
