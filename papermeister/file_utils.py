"""Attachment file-type classification — decides whether a Zotero attachment
(or local file) is an OCR target, a derived sibling, or neither.

Single source of truth for the extension/contentType gate so the four
ingestion sites, the OCR entry point, and the backfill script all agree.

Status assigned at PaperFile creation:
- derived JSON (OCR output sibling)  → 'processed'  (no OCR needed)
- PDF (the only OCR target)          → 'pending'    (queue for OCR)
- anything else (.txt/.zip/.doc/...) → 'skipped'    (not an OCR target)
"""

# OCR currently runs only on PDFs (ocr_pdf renders PDF pages via pypdfium2).
# Images/other formats would need a separate code path, so they're 'skipped'.


def is_pdf(filename: str, content_type: str = '') -> bool:
    """True if this attachment is a PDF — the only thing we OCR."""
    if content_type and content_type.lower() == 'application/pdf':
        return True
    return (filename or '').lower().endswith('.pdf')


def is_derived(filename: str, content_type: str = '') -> bool:
    """True if this is a derived OCR-output sibling (our `{...}.json` cache)."""
    if content_type and content_type.lower() == 'application/json':
        return True
    return (filename or '').lower().endswith('.json')


def attachment_status(filename: str, content_type: str = '') -> str:
    """PaperFile.status to assign when an attachment is first created."""
    if is_derived(filename, content_type):
        return 'processed'
    if is_pdf(filename, content_type):
        return 'pending'
    return 'skipped'


def has_non_pdf_extension(filename: str) -> bool:
    """True only when the name has a concrete extension that isn't a PDF/JSON.

    For guards that have only the stored `PaperFile.path` (no Zotero
    contentType). A bare Zotero key (no extension) returns False — we can't
    tell from the name alone, so let the OCR path try rather than wrongly
    skipping a not-yet-downloaded PDF whose path is still the bare key.
    """
    import os
    ext = os.path.splitext(filename or '')[1].lower()
    return bool(ext) and ext not in ('.pdf', '.json')
