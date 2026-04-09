"""Bibliographic info extraction from OCR JSON.

Step 2 (P05): input preparation infrastructure. No LLM calls yet.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

OCR_JSON_DIR = os.path.join(os.path.expanduser('~'), '.papermeister', 'ocr_json')


@dataclass
class BiblioResult:
    """Structured bibliographic info extracted from a paper's first pages."""
    title: str = ''
    authors: list = field(default_factory=list)  # ordered list of "First Last"
    year: Optional[int] = None
    journal: str = ''
    doi: str = ''
    abstract: str = ''
    doc_type: str = 'unknown'   # article|book|chapter|thesis|report|unknown
    language: str = ''           # ISO 639-1
    confidence: str = ''         # high|medium|low
    notes: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(
            title=d.get('title', '') or '',
            authors=list(d.get('authors', []) or []),
            year=d.get('year'),
            journal=d.get('journal', '') or '',
            doi=d.get('doi', '') or '',
            abstract=d.get('abstract', '') or '',
            doc_type=d.get('doc_type', 'unknown') or 'unknown',
            language=d.get('language', '') or '',
            confidence=d.get('confidence', '') or '',
            notes=d.get('notes', '') or '',
        )


def load_ocr_pages(file_hash: str) -> list:
    """Load OCR result by file hash. Returns list of page markdown strings (in order).

    Returns empty list if cache file is missing or malformed.
    """
    path = os.path.join(OCR_JSON_DIR, f'{file_hash}.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    pages_data = data.get('pages', [])
    # Sort by page index to be safe
    pages_data = sorted(pages_data, key=lambda p: p.get('page', 0))
    return [
        (p.get('markdown') or p.get('text') or '').strip()
        for p in pages_data
    ]


def extract_first_pages(pages: list, max_chars: int = 6000, min_chars: int = 1500) -> str:
    """Concatenate the first few pages until reaching max_chars.

    Stops as soon as accumulated text exceeds min_chars AND we've consumed at
    least one page. This avoids returning a near-empty cover page alone.
    Truncates to max_chars at the end.
    """
    if not pages:
        return ''

    parts = []
    total = 0
    for i, page_text in enumerate(pages):
        if not page_text:
            continue
        parts.append(f'--- Page {i + 1} ---\n{page_text}')
        total += len(page_text)
        if total >= min_chars and len(parts) >= 1:
            # Always include at least 2 pages if available, to capture cover→title→abstract layouts
            if len(parts) >= 2 or i == len(pages) - 1:
                break

    combined = '\n\n'.join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + '\n[...truncated]'
    return combined
