"""Bibliographic info extraction from OCR JSON."""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger('biblio')

OCR_JSON_DIR = os.path.join(os.path.expanduser('~'), '.papermeister', 'ocr_json')


def _find_cache_by_hash(file_hash: str) -> str | None:
    """Locate the OCR cache file for a given PDF hash.

    Cache filenames are `{pdf_basename}.{hash[:8]}.json` — keyed on the
    8-char hash prefix because the same hash may have multiple PaperFile
    rows (one PDF imported into several Zotero parents). The first match
    is fine: same hash → identical content → any copy works.

    Returns the absolute path or None.
    """
    if not file_hash or not os.path.isdir(OCR_JSON_DIR):
        return None
    suffix = f'.{file_hash[:8]}.json'
    try:
        for fname in os.listdir(OCR_JSON_DIR):
            if fname.endswith(suffix):
                return os.path.join(OCR_JSON_DIR, fname)
    except OSError:
        pass
    return None


@dataclass
class BiblioResult:
    """Structured bibliographic info extracted from a paper's first pages."""
    title: str = ''
    authors: list = field(default_factory=list)  # ordered list of "First Last"
    year: Optional[int] = None
    journal: str = ''
    volume: str = ''             # journal volume
    issue: str = ''              # journal issue/number
    pages: str = ''              # page range, e.g. "123-145"
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
            volume=str(d.get('volume', '') or ''),
            issue=str(d.get('issue', '') or ''),
            pages=str(d.get('pages', '') or ''),
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
    path = _find_cache_by_hash(file_hash)
    if path is None:
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
    path = _find_cache_by_hash(file_hash)
    if path is None:
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
    '"journal": string, "volume": string, "issue": string, "pages": string, '
    '"doi": string, "abstract": string, '
    '"doc_type": "article"|"book"|"chapter"|"thesis"|"report"|"unknown", '
    '"language": string, "confidence": "high"|"medium"|"low", '
    '"needs_visual_review": boolean, "notes": string}\n\n'
    "Rules:\n"
    "- Authors must be in the order shown in the document.\n"
    "- Year: the publication year, not received/accepted dates.\n"
    "- DOI: only if explicitly written.\n"
    "- For a journal article: volume, issue (number), and pages (page range like "
    '"123-145") if explicitly present; otherwise leave them empty. Use plain '
    "digits/range strings, no labels like \"Vol.\" or \"pp.\".\n"
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


def _call_qwen(prompt: str, base_url: str, max_tokens: int = 2048) -> str:
    """Call Qwen3 via OpenAI-compatible API. Returns raw text output."""
    import requests as req
    url = f'{base_url.rstrip("/")}/llm/v1/chat/completions'
    logger.debug('Qwen request: POST %s', url)
    resp = req.post(url, json={
        'model': 'qwen',
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': max_tokens,
        'temperature': 0.1,
        'chat_template_kwargs': {'enable_thinking': False},
    }, timeout=180)
    if resp.status_code != 200:
        logger.error('Qwen %d: %s', resp.status_code, resp.text[:500])
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content'].strip()


def extract_biblio_llm(
    file_hash: str, backend: str = 'claude', filename: str = '',
) -> tuple[dict, str, str]:
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

    hint = ''
    if filename:
        hint = (
            f"--- SOURCE FILENAME ---\n{filename}\n"
            "Academic PDF filenames very often encode the author surname(s) and "
            "the publication year, e.g. 'Smith2023.pdf', 'Brock & Holmer 2004 "
            "Ameghiniana.pdf', 'Temple1980.pdf'. Treat such an encoded year/author "
            "as evidence (not a guess) and use it to fill `year`/`authors` when the "
            "document text doesn't state them clearly. Explicit text always wins "
            "over the filename.\n\n"
        )
    prompt = _BIBLIO_PROMPT + hint + f"--- DOCUMENT TEXT ---\n{text}"

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


# ===========================================================================
# P11: references-section extraction (citation network, Phase 1)
# ===========================================================================

QWEN_REFS_MODEL_VERSION = 'qwen3-32b'

# Headings that mark the start of a references / bibliography section. The
# heading wording varies a lot across journals, eras, and languages, so the
# list is deliberately broad (EN + the European + CJK languages present in the
# library). Multi-word phrases are listed BEFORE their shorter prefixes so the
# longest heading wins. Matched case-insensitively on a heading-like line —
# `#{0,6}` allows a plain (un-hashed) line too, since OCR'd headings are often
# just bold/plain text. The line must be ONLY the heading (anchored to end),
# which keeps "Literature Review" / "Funding Sources" / "see references" from
# false-matching.
_REF_HEADING_WORDS = (
    # English (longest first)
    'list of references', 'references and notes', 'literature cited',
    'cited literature', 'cited references', 'references cited', 'works cited',
    'sources cited', 'selected bibliography', 'reference list',
    'references', 'reference', 'bibliography', 'literature', 'citations',
    # French
    'références bibliographiques', 'bibliographie', 'références',
    # German
    'literaturverzeichnis', 'literatur',
    # Spanish
    'referencias bibliográficas', 'referencias', 'bibliografía',
    # Italian / Portuguese
    'riferimenti bibliografici', 'riferimenti', 'bibliografia',
    'referências bibliográficas', 'referências',
    # CJK (Korean / Japanese / Chinese trad+simp)
    '참고문헌', '인용문헌', '참고자료', '인용자료',
    '引用文献', '参考文献', '參考文獻', '引用文獻',
    '参考资料', '參考資料', '引用書目', '主要参考文献', '文献', '文獻',
)
# Optional trailing clause some journals append, e.g. "References and Notes",
# "References and Further Reading".
_REF_HEADING_SUFFIX = r'(?:\s*(?:and|&|及び|및)\s*(?:notes?|further\s+reading|cited))?'
_REF_HEADING_RE = re.compile(
    r'^\s{0,3}#{0,6}\s*(?:[0-9IVXivx]+\s*[.)]\s*)?(?:' +
    '|'.join(re.escape(w) for w in _REF_HEADING_WORDS) +
    r')' + _REF_HEADING_SUFFIX + r'\s*[:：.]?\s*$',
    re.IGNORECASE,
)
# Headings that, if they appear AFTER the references heading, end the section
# (appendix / acknowledgments / supplementary material that some papers place
# after the bibliography).
_REF_STOP_RE = re.compile(
    r'^\s{0,3}#{1,6}\s*(?:[0-9]+\s*[.)]\s*)?'
    r'(appendix|appendices|acknowledg|supplement|supporting information|'
    r'author contributions|figure legends|tables?\b|plates?\b|부록|보충)',
    re.IGNORECASE,
)


def extract_references_block(pages: list) -> tuple[str, str]:
    """Locate the references section in OCR page markdown.

    Searches backwards from the last page for a references heading. Returns
    (block_text, confidence) where confidence is:
      - 'high'   heading found, section delimited cleanly
      - 'low'    no heading found → fell back to the last 2 pages

    Returns ('', 'none') if there is no usable text at all.
    """
    if not pages:
        return '', 'none'

    # Join pages with explicit markers so we can scan line-by-line while still
    # knowing we covered the whole tail of the document.
    full = '\n'.join(p or '' for p in pages)
    lines = full.split('\n')

    # Find the LAST line that looks like a references heading.
    start = None
    for i, line in enumerate(lines):
        if _REF_HEADING_RE.match(line):
            start = i
    if start is None:
        # Fallback: last 2 non-empty pages, flagged low-confidence.
        tail = [p for p in pages if (p or '').strip()][-2:]
        block = '\n\n'.join(tail).strip()
        return (block, 'low') if block else ('', 'none')

    # From the heading, take lines until a stop heading (appendix/etc.) appears.
    body = []
    for line in lines[start + 1:]:
        if _REF_STOP_RE.match(line):
            break
        body.append(line)
    block = '\n'.join(body).strip()
    return (block, 'high') if block else ('', 'low')


# A reference entry that starts with a marker: "[12]", "12.", "12)" or
# "(12)". Used to split a numbered bibliography deterministically.
_NUMBERED_ENTRY_RE = re.compile(r'^\s*(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,4})[.)])\s+')


def split_reference_entries(block: str) -> list:
    """Split a references block into individual entry strings.

    Numbered bibliographies ("[1] ...", "1. ...") split deterministically.
    For unnumbered styles this returns a single-element list with the whole
    block so the LLM can segment it itself.
    """
    if not block.strip():
        return []

    lines = block.split('\n')
    # Count how many lines begin a numbered entry; only treat as numbered if
    # there are at least 3 such markers (avoids false positives on a stray
    # "1. Introduction" leftover or volume numbers).
    starts = [i for i, ln in enumerate(lines) if _NUMBERED_ENTRY_RE.match(ln)]
    if len(starts) < 3:
        return [block.strip()]

    entries = []
    for j, s in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        entry = '\n'.join(lines[s:end]).strip()
        if entry:
            entries.append(entry)
    return entries


_REFS_PROMPT = (
    "You are parsing the REFERENCES / bibliography section of an academic paper "
    "(OCR'd text, may contain noise, broken lines, and layout artifacts).\n\n"
    "Split the text into individual reference entries and extract structured "
    "fields for each. Extract only what is EXPLICITLY present — do NOT guess. "
    "Leave a field empty/null if it is not clearly stated.\n\n"
    "Output STRICT JSON only: a single JSON ARRAY (no prose, no markdown fence). "
    "Each element has this exact schema:\n"
    '{"raw": string, "authors": [{"family": string, "given": string}], '
    '"year": integer or null, "title": string, "container": string, '
    '"volume": string, "issue": string, "pages": string, "doi": string, '
    '"type": "article"|"book"|"chapter"|"thesis"|"report"|"unknown"}\n\n'
    "Rules:\n"
    "- `raw` MUST be the original reference text exactly as it appears (your "
    "evidence; keep it verbatim including the leading number if any).\n"
    "- `container` is the journal name, book title, or proceedings title.\n"
    "- `authors` in the order shown; split family/given names. For an "
    "organization or a single-token name, put it in `family` and leave `given` empty.\n"
    "- `pages` as a plain range like \"123-145\", no \"pp.\".\n"
    "- `year`: the publication year only.\n"
    "- If a line is clearly NOT a reference (a stray heading, page number), skip it.\n"
    "- Output ONLY the JSON array.\n\n"
)


def _parse_llm_json_array(text: str) -> list:
    """Extract a JSON array from LLM output, handling fences and <think> tags."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    m = re.search(r'```(?:json)?\s*(\[.*\])\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    if text.startswith('['):
        return json.loads(text)
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f'No JSON array found in LLM output: {text[:200]}')


def _chunk_entries(entries: list, max_chars: int = 9000) -> list:
    """Group entry strings into chunks under max_chars (for batched LLM calls).

    A single oversized entry becomes its own chunk.
    """
    chunks = []
    cur, cur_len = [], 0
    for e in entries:
        if cur and cur_len + len(e) > max_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(e)
        cur_len += len(e) + 1
    if cur:
        chunks.append(cur)
    return chunks


def extract_references_llm(
    file_hash: str, backend: str = 'qwen', base_url: str = '',
) -> tuple[list, str, str]:
    """Parse a paper's references section into structured entries via LLM.

    Args:
        file_hash: SHA256 hash of the citing PDF.
        backend: 'qwen' (ocrserver, default) or 'claude'.
        base_url: ocrserver URL (qwen). If empty, read from preferences.

    Returns:
        (entries, source_label, model_version). `entries` is a list of dicts
        each carrying the parsed fields plus 'raw' and 'parse_confidence';
        it is EMPTY when no references section was found (a valid "checked,
        none" outcome — the caller should mark the paper checked, not retry).
        Raises ValueError only when the OCR text itself is missing (genuine
        error — retry after OCR), or RuntimeError on misconfiguration.
    """
    source = 'llm-qwen' if backend == 'qwen' else 'llm-sonnet'
    model_version = QWEN_REFS_MODEL_VERSION if backend == 'qwen' else 'claude-sonnet-4-6'

    pages = load_ocr_pages(file_hash)
    if not pages:
        raise ValueError('No OCR pages found')
    block, confidence = extract_references_block(pages)
    if not block:
        # No references section in this document — a valid empty result, not
        # a failure. No LLM call needed.
        return [], source, model_version

    entries = split_reference_entries(block)
    chunks = _chunk_entries(entries)

    if backend == 'qwen':
        from .preferences import get_pref
        url = base_url or get_pref('ocr_pod_url', '')
        if not url:
            raise RuntimeError('Server URL not configured in Preferences')

    parsed = []
    for chunk in chunks:
        prompt = _REFS_PROMPT + '--- REFERENCES TEXT ---\n' + '\n\n'.join(chunk)
        if backend == 'qwen':
            raw = _call_qwen(prompt, url, max_tokens=8192)
        else:
            raw = _call_claude(prompt)
        for item in _parse_llm_json_array(raw):
            if isinstance(item, dict):
                item.setdefault('parse_confidence', confidence)
                parsed.append(item)

    return parsed, source, model_version
