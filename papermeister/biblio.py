"""Bibliographic info extraction from OCR JSON."""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger('biblio')

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


def load_ocr_meta(file_hash: str) -> dict | None:
    """Return the `papermeister_meta` dict embedded in the OCR JSON, or None.

    Used to detect cross-machine state (e.g. biblio already applied on another
    machine) without re-running the LLM.
    """
    path = os.path.join(OCR_JSON_DIR, f'{file_hash}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    meta = data.get('papermeister_meta')
    return meta if isinstance(meta, dict) else None


class BiblioAlreadyApplied(Exception):
    """Raised when extract_biblio_llm sees a JSON whose papermeister_meta
    indicates biblio is already applied or auto-committed elsewhere.

    Carries the meta dict so callers can decide how to surface the skip.
    """
    def __init__(self, meta: dict):
        super().__init__(
            f"biblio already applied (state={meta.get('biblio_state', '?')}, "
            f"source={meta.get('biblio_source', '?')})"
        )
        self.meta = meta


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


_BIBLIO_PROMPT = (
    "You are extracting bibliographic metadata from the first pages of an academic document (OCR'd text). "
    "The text below may contain noise, broken lines, and layout artifacts.\n\n"
    "Your task: extract the bibliographic information that is EXPLICITLY present in the text. "
    "Do NOT guess or infer; if a field is not clearly stated, leave it empty/null.\n\n"
    "Output STRICT JSON only (no prose, no markdown code fence) with this exact schema:\n"
    '{"title": string, "authors": [string], "year": integer or null, '
    '"journal": string, "doi": string, "abstract": string, '
    '"doc_type": "article"|"book"|"chapter"|"thesis"|"report"|"unknown", '
    '"language": string, "confidence": "high"|"medium"|"low", '
    '"needs_visual_review": boolean, "notes": string}\n\n'
    "Rules:\n"
    "- Authors must be in the order shown in the document.\n"
    "- Year: the publication year, not received/accepted dates.\n"
    "- DOI: only if explicitly written.\n"
    "- Set needs_visual_review=true if the first pages look like a journal-issue cover, "
    "a table of contents, or any layout where spatial/visual structure is essential.\n"
    "- Output ONLY the JSON object.\n\n"
)


def _parse_llm_json(text: str) -> dict:
    """Extract a JSON object from LLM output, handling markdown fences and thinking tags."""
    # Strip <think>...</think> blocks (Qwen3 thinking mode)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # Try markdown code fence
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Try bare JSON
    if text.startswith('{'):
        return json.loads(text)
    # Find first {...}
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f'No JSON found in LLM output: {text[:200]}')


def _call_claude(prompt: str) -> str:
    """Call Claude via claude -p CLI. Returns raw text output."""
    import subprocess
    proc = subprocess.run(
        ['claude', '-p', '--model', 'claude-sonnet-4-6', '--output-format', 'json'],
        input=prompt, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'claude exit {proc.returncode}')
    envelope = json.loads(proc.stdout)
    if envelope.get('is_error'):
        raise RuntimeError(f'claude error: {envelope.get("result", "")[:200]}')
    return envelope.get('result', '').strip()


def _call_qwen(prompt: str, base_url: str) -> str:
    """Call Qwen3 via OpenAI-compatible API. Returns raw text output."""
    import requests as req
    url = f'{base_url.rstrip("/")}/llm/v1/chat/completions'
    logger.debug('Qwen request: POST %s', url)
    resp = req.post(url, json={
        'model': 'qwen',
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 2048,
        'temperature': 0.1,
        'chat_template_kwargs': {'enable_thinking': False},
    }, timeout=120)
    if resp.status_code != 200:
        logger.error('Qwen %d: %s', resp.status_code, resp.text[:500])
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content'].strip()


def extract_biblio_llm(file_hash: str, backend: str = 'claude') -> tuple[dict, str, str]:
    """Extract biblio from OCR text using LLM.

    Args:
        file_hash: SHA256 hash of the PDF file
        backend: 'claude' or 'qwen'

    Returns:
        (pred_dict, source_label, model_version) on success.
        Raises BiblioAlreadyApplied if the OCR JSON's papermeister_meta
        indicates a terminal apply state from another run — saves the LLM call.
        Raises other exceptions on failure.
    """
    meta = load_ocr_meta(file_hash)
    if meta and meta.get('biblio_state') in ('applied', 'auto_committed'):
        raise BiblioAlreadyApplied(meta)

    pages = load_ocr_pages(file_hash)
    if not pages:
        raise ValueError('No OCR pages found')
    text = extract_first_pages(pages)
    if not text:
        raise ValueError('No text in first pages')

    prompt = _BIBLIO_PROMPT + f"--- DOCUMENT TEXT ---\n{text}"

    if backend == 'qwen':
        from .preferences import get_pref
        base_url = get_pref('ocr_pod_url', '')
        if not base_url:
            raise RuntimeError('Server URL not configured in Preferences')
        raw = _call_qwen(prompt, base_url)
        source = 'llm-qwen'
        model_version = 'qwen3-14b'
    else:
        raw = _call_claude(prompt)
        source = 'llm-sonnet'
        model_version = 'claude-sonnet-4-6'

    pred = _parse_llm_json(raw)
    return pred, source, model_version
