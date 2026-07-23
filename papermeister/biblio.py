"""Bibliographic info extraction from OCR JSON."""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field

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
    year: int | None = None
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
    # Try markdown code fence (strict=False tolerates raw control chars in strings)
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1), strict=False)
    # Try bare JSON
    if text.startswith('{'):
        return json.loads(text, strict=False)
    # Find first {...}
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return json.loads(m.group(0), strict=False)
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


def _call_qwen(prompt: str, base_url: str, max_tokens: int = 2048,
               read_timeout: int = 180, retries: int = 0, label: str = '') -> str:
    """Call Qwen3 via OpenAI-compatible API. Returns raw text output.

    `read_timeout` is the per-attempt read timeout (connect is fixed at 10s).
    `retries` extra attempts on a timeout / connection drop (the server may be
    momentarily busy with OCR) — the request itself is idempotent.
    `label` is an optional caller tag (e.g. the paper) for log attribution.
    """
    import requests as req
    url = f'{base_url.rstrip("/")}/llm/v1/chat/completions'
    logger.debug('Qwen request: POST %s', url)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = req.post(url, json={
                'model': 'qwen',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': max_tokens,
                'temperature': 0.1,
                'chat_template_kwargs': {'enable_thinking': False},
            }, timeout=(10, read_timeout))
        except (req.exceptions.Timeout, req.exceptions.ConnectionError) as exc:
            last_exc = exc
            tag = f'{label} ' if label else ''
            logger.warning('%sQwen attempt %d/%d failed: %s',
                           tag, attempt + 1, retries + 1, exc)
            continue
        if resp.status_code != 200:
            logger.error('Qwen %d: %s', resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
    raise last_exc


def references_server_alive(base_url: str = '', timeout: int = 6) -> bool:
    """Quick health probe of the references LLM endpoint (the exact server the
    parser calls). True if it answers a trivial request promptly. Used to decide
    whether a run of parse failures means the server is down (stop) or was just a
    transient blip (keep going). A tiny max_tokens keeps it fast even when the
    server is up but busy, so it distinguishes 'down' from 'slow'."""
    from .preferences import get_pref
    url = (base_url or get_pref('ocr_pod_url', '')).rstrip('/')
    if not url:
        return False
    import requests as req
    try:
        resp = req.post(f'{url}/llm/v1/chat/completions', json={
            'model': 'qwen',
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 1,
            'temperature': 0.0,
            'chat_template_kwargs': {'enable_thinking': False},
        }, timeout=(5, timeout))
        return resp.status_code == 200
    except Exception:
        return False


def biblio_server_alive() -> bool:
    """Health signal for the biblio batch. Only the Qwen backend hits a pollable
    server; with Claude (`claude -p` subprocess) there is nothing to poll, so
    report 'alive' — per-item Claude failures handle themselves and shouldn't
    pause the batch."""
    from .preferences import get_pref
    if get_pref('biblio_backend', '') != 'qwen':
        return True
    return references_server_alive()


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


def _is_cjk(ch: str) -> bool:
    """True for a CJK ideograph, kana, or Hangul syllable."""
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF)


def _heading_word_pattern(w: str) -> str:
    """Regex for one heading word, tolerant of OCR spacing in CJK/Hangul.

    CJK/Hangul headings are routinely OCR'd with spaces between glyphs ("文 献",
    "참고 문헌"), so allow optional whitespace between every character. Latin
    words keep their literal spacing (a space there is a real word boundary).
    """
    if any(_is_cjk(c) for c in w):
        return r'\s*'.join(re.escape(c) for c in w)
    return re.escape(w)


_REF_HEADING_RE = re.compile(
    r'^\s{0,3}#{0,6}\s*(?:[0-9IVXivx]+\s*[.)]\s*)?(?:' +
    '|'.join(_heading_word_pattern(w) for w in _REF_HEADING_WORDS) +
    r')' + _REF_HEADING_SUFFIX + r'\s*[:：.]?\s*$',
    re.IGNORECASE,
)
# Back-matter section headings that END the references section when they appear
# after it (appendix / acknowledgments / supplementary material). `#{0,6}` so a
# PLAIN (un-hashed) OCR line like "Appendix. Descriptions of landmarks…" also
# stops — these words essentially never start an actual reference line, so the
# no-hash match is safe. (Risky bare words like "Tables"/"Plates" are omitted
# on purpose — they overlap with reference titles.)
_REF_STOP_RE = re.compile(
    r'^\s{0,3}#{0,6}\s*(?:[0-9]+\s*[.)]\s*)?'
    r'(appendix|appendices|acknowledg|supplement|supporting\s+information|'
    r'author\s+contributions|data\s+availability|competing\s+interest|'
    r'conflict.{0,15}interest|declaration\s+of|funding|'
    r'부록|보충자료|감사의?\s*글|附录|謝辞|致谢)',
    re.IGNORECASE,
)


# Chandra2's OCR `markdown` is heterogeneous: simple docs come out as plain
# markdown, but complex layouts come out as HTML with bounding-box + semantic
# labels — `<div data-bbox="..." data-label="Section-Header"><h2>References</h2>
# </div>`, `data-label="Bibliography"` for the reference region, one `<p>` per
# entry. Those labels are far more reliable than text heading-matching.
_HTML_HINT_RE = re.compile(r'data-label=|<div\b|<h[1-6]>', re.IGNORECASE)
_DIV_RE = re.compile(r'data-label="([^"]+)"[^>]*>(.*?)</div>', re.DOTALL)
_P_RE = re.compile(r'<p>(.*?)</p>', re.DOTALL)
# Reference entries live in divs Chandra labels 'Bibliography' (preferred) or a
# 'List-Group' that follows the references header.
_REF_BLOCK_LABELS = ('Bibliography', 'List-Group')


def _html_to_text(s: str) -> str:
    """Strip OCR HTML tags + unescape entities, preserving inner text."""
    s = re.sub(r'<[^>]+>', '', s)
    for a, b in (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'),
                 ('&#39;', "'"), ('&nbsp;', ' ')):
        s = s.replace(a, b)
    return re.sub(r'[ \t]+', ' ', s).strip()


def _div_entries(inner: str) -> list:
    """Per-`<p>` text inside a labeled div (one reference each); whole div if no <p>."""
    found = _P_RE.findall(inner)
    items = [_html_to_text(p) for p in found] if found else [_html_to_text(inner)]
    return [x for x in items if x]


def _extract_refs_html(full: str) -> tuple[str, str]:
    """Pull the references region from HTML-flavoured OCR via semantic labels.

    Returns (block, confidence) — block has one entry per paragraph (joined by
    blank lines), or ('', '') if no references region was identified.
    """
    divs = _DIV_RE.findall(full)
    # Last Section-Header whose text is a references heading.
    hdr = None
    for i, (label, inner) in enumerate(divs):
        if label == 'Section-Header' and _REF_HEADING_RE.match(_html_to_text(inner)):
            hdr = i

    entries: list = []
    if hdr is not None:
        for label, inner in divs[hdr + 1:]:
            if label == 'Section-Header':
                if _REF_HEADING_RE.match(_html_to_text(inner)):
                    continue          # a continued references header
                break                 # a different section → references end here
            if label in _REF_BLOCK_LABELS:
                entries += _div_entries(inner)
    if not entries:
        # No header match (or it yielded nothing): trust explicit Bibliography
        # labels anywhere in the document.
        for label, inner in divs:
            if label == 'Bibliography':
                entries += _div_entries(inner)

    return ('\n\n'.join(entries), 'high') if entries else ('', '')


# A citation "head" line: an author/title line that carries a publication year
# near its start, followed by a citation delimiter — covers "Ager, D. V., 1963:",
# "岩崎泰顕・坂本吾省, 1981:" and the Western "Smith, J. (2001). …" style (year in
# parentheses). Body prose also contains years, but deep inside a long sentence,
# so anchoring the year within the first ~55 chars + a delimiter separates
# references from running text. Used to bound a references section by content
# density in multi-article journal issues / multi-chapter books.
_CITATION_HEAD_RE = re.compile(
    r'^\s{0,4}\S.{0,55}?\(?(?:18|19|20)\d{2}[a-z]?\)?\s*[.:：,，、]')

# Tuning for _capture_refs_section (multi-article path only).
_REFS_GAP_STOP = 12      # consecutive non-head lines ⇒ references region ended
_REFS_MAX_CONT = 8       # max continuation lines attached to the last entry
_REFS_MIN_HEADS = 2      # min author-year heads for a section to be real

# A line that signals the article body / a back-matter section has resumed
# (these never begin a reference, so they end the references region).
_BODY_TEXT_RE = re.compile(
    r'^\s*(?:指名討論|討論|質疑|司会|はじめに|おわりに|まとめ|要\s*約|序\s*論|緒\s*言|'
    r'abstract|introduction)', re.IGNORECASE)


def _is_body_line(s: str) -> bool:
    """True if a (non-head) line looks like article prose, not a reference fragment.

    Chandra fragments each reference into several SHORT lines (author-year head,
    then the italic journal, volume, pages each on their own line), none of which
    carry a CJK sentence period. Body prose, by contrast, is long and/or ends
    sentences with '。'. So short fragment lines are kept; long / '。' / section-
    heading lines end the references region.
    """
    return ('。' in s) or len(s) > 120 or bool(_BODY_TEXT_RE.match(s))


def _capture_refs_section(lines: list, start: int, end: int) -> str:
    """Bound ONE references section inside [start, end) by citation-head density.

    In a journal-issue PDF each article's reference list is followed immediately
    by the next article's body (and often a data table or figure block), so
    running to `end` (the next refs heading) would swallow all of it. Heads alone
    can't bound it — one reference is OCR-fragmented across ~5-7 short lines, so a
    long gap of non-head lines is normal WITHIN the references. We therefore walk
    the window keeping reference content (heads + short non-body continuation
    lines) and stop only once `_REFS_GAP_STOP` consecutive non-head lines pile up
    — which is what a resumed body paragraph or a numeric table (e.g. "1*", "2*"
    rows) produces, but a single fragmented entry does not. A window with fewer
    than `_REFS_MIN_HEADS` author-year lines is rejected as a false heading (e.g.
    a "文 献" line inside the journal's submission guidelines).
    """
    seg = lines[start:end]
    for off, line in enumerate(seg):
        if _REF_STOP_RE.match(line):
            seg = seg[:off]
            break
    if sum(1 for line in seg if _CITATION_HEAD_RE.match(line)) < _REFS_MIN_HEADS:
        return ''
    out, gap, keep = [], 0, 0
    for line in seg:
        s = line.strip()
        out.append(line)
        if not s:
            continue
        if _CITATION_HEAD_RE.match(line) or _NUMBERED_ENTRY_RE.match(line):
            gap = 0
            keep = len(out)
            continue
        gap += 1
        if gap >= _REFS_GAP_STOP:
            break
        if gap <= _REFS_MAX_CONT and not _is_body_line(s):
            keep = len(out)               # continuation of the last entry
    return '\n'.join(out[:keep]).strip()


def _extract_refs_markdown(full: str) -> tuple[str, str]:
    """Line-based references locator for plain-markdown OCR output.

    Single references heading → capture to a back-matter STOP heading or EOF
    (long-standing behavior, robust to mid-section page furniture). Multiple
    headings → a multi-article journal issue: bound EACH section by content
    density so the last one doesn't run to EOF and swallow trailing articles,
    figures, tables and covers.
    """
    lines = full.split('\n')
    heads = [i for i, line in enumerate(lines) if _REF_HEADING_RE.match(line)]
    if not heads:
        return '', ''

    if len(heads) == 1:
        start = heads[0]
        body = []
        for line in lines[start + 1:]:
            if _REF_STOP_RE.match(line):
                break
            body.append(line)
        block = '\n'.join(body).strip()
        return (block, 'high') if block else ('', '')

    blocks = []
    for i, h in enumerate(heads):
        win_end = heads[i + 1] if i + 1 < len(heads) else len(lines)
        b = _capture_refs_section(lines, h + 1, win_end)
        if b:
            blocks.append(b)
    block = '\n\n'.join(blocks).strip()
    return (block, 'high') if block else ('', '')


def extract_references_block(pages: list) -> tuple[str, str]:
    """Locate the references section in OCR page output.

    Handles both HTML-flavoured OCR (via Chandra's semantic labels) and plain
    markdown (via heading text). Returns (block_text, confidence):
      - 'high'   references region identified (label or heading)
      - 'low'    nothing identified → fell back to the last 2 pages (HTML stripped)
      - 'none'   no usable text at all
    The returned block is plain text (HTML stripped), entries separated by
    blank lines where known.
    """
    if not pages:
        return '', 'none'

    full = '\n'.join(p or '' for p in pages)

    if _HTML_HINT_RE.search(full):
        block, conf = _extract_refs_html(full)
        if block:
            return block, conf
        # HTML present but no references region found → fall through to the
        # last-2-pages fallback (stripped of tags below).
    else:
        block, conf = _extract_refs_markdown(full)
        if block:
            return block, conf

    # Fallback: last 2 non-empty pages, low-confidence. Strip HTML so the LLM
    # gets clean text either way.
    tail = [p for p in pages if (p or '').strip()][-2:]
    block = '\n\n'.join(_html_to_text(p) if _HTML_HINT_RE.search(p) else p
                        for p in tail).strip()
    return (block, 'low') if block else ('', 'none')


# A reference entry that starts with a marker: "[12]", "12.", "12)" or
# "(12)". Used to split a numbered bibliography deterministically.
_NUMBERED_ENTRY_RE = re.compile(r'^\s*(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,4})[.)])\s+')


def split_reference_entries(block: str) -> list:
    """Split a references block into individual entry strings.

    Three strategies, in order:
      1. Numbered ("[1] ...", "1. ...") → split on the markers.
      2. Blank-line-separated paragraphs (e.g. HTML <p>-per-entry, joined by
         blank lines upstream, or double-spaced OCR) → one entry per paragraph.
      3. Otherwise → the whole block as one (the LLM segments it).
    """
    if not block.strip():
        return []

    lines = block.split('\n')
    # (1) Numbered — at least 3 markers (avoids a stray "1. Introduction").
    starts = [i for i, ln in enumerate(lines) if _NUMBERED_ENTRY_RE.match(ln)]
    # Guard: the markers must begin NEAR THE TOP of the block. If there's a lot
    # of un-numbered text before the first "1." it isn't a numbered bibliography
    # — it's e.g. unnumbered references followed by a numbered appendix that
    # leaked in. Numbered-splitting there would silently drop the real
    # references (everything before starts[0]). Fall through to blank-line.
    nonempty_before = sum(1 for ln in lines[:starts[0]] if ln.strip()) if starts else 0
    if len(starts) >= 3 and nonempty_before <= 2:
        entries = []
        for j, s in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(lines)
            entry = '\n'.join(lines[s:end]).strip()
            if entry:
                entries.append(entry)
        return entries

    # (2) Blank-line-separated paragraphs, minus page furniture (running
    # headers/footers, bare DOIs/URLs/page numbers leak into plain-markdown OCR
    # between references at page breaks).
    paras = [p.strip() for p in re.split(r'\n\s*\n', block) if p.strip()]
    paras = [p for p in paras if not _is_page_furniture(p)]
    if len(paras) >= 3:
        return paras

    # (3) No clear separators (refs run together / single-newline separated).
    # Split into char-bounded pieces so the batcher can chunk it and each call's
    # output stays within the token budget; the LLM segments each piece.
    block = block.strip()
    if len(block) <= 1500:
        return [block]
    groups, cur, cur_len = [], [], 0
    for ln in block.split('\n'):
        if cur and cur_len + len(ln) > 1200:
            groups.append('\n'.join(cur))
            cur, cur_len = [], 0
        cur.append(ln)
        cur_len += len(ln) + 1
    if cur:
        groups.append('\n'.join(cur))
    # Hard-split any monster piece (references on a single long line) by chars.
    pieces = []
    for g in groups:
        g = g.strip()
        if not g:
            continue
        if len(g) <= 1800:
            pieces.append(g)
        else:
            pieces.extend(g[k:k + 1500] for k in range(0, len(g), 1500))
    return pieces


# A line that is ONLY a URL / DOI / page number / punctuation, or that STARTS
# with a known footer/header phrase — i.e. page furniture, not a reference.
_FURNITURE_RE = re.compile(
    r'^(?:https?://\S+\s*$|doi:\s*\S+\s*$|\d{1,4}\s*$|[.,;:\-–—]+\s*$|'
    r'(?:published\s+online|downloaded\s+from|this\s+content\s+downloaded|'
    r'all\s+use\s+subject|for\s+personal\s+use|copyright\b|©))',
    re.IGNORECASE,
)


def _is_page_furniture(paragraph: str) -> bool:
    """True if a blank-line paragraph is a running header/footer, not a ref.

    Conservative: real references start with an author surname, so they never
    match these URL-only / page-number / footer-phrase patterns."""
    first = paragraph.strip().splitlines()[0].strip() if paragraph.strip() else ''
    return bool(_FURNITURE_RE.match(first))


_REFS_PROMPT = (
    "You are parsing the REFERENCES / bibliography section of an academic paper "
    "(OCR'd text, may contain noise, broken lines, and layout artifacts).\n\n"
    "Split the text into individual reference entries and extract structured "
    "fields for each. Extract only what is EXPLICITLY present — do NOT guess. "
    "Leave a field empty/null if it is not clearly stated.\n\n"
    "The entries are separated by blank lines. Output STRICT JSON only: a "
    "single JSON ARRAY (no prose, no markdown fence), ONE object per entry in "
    "the SAME ORDER as the input. Each element has this exact schema:\n"
    '{"authors": [{"family": string, "given": string}], '
    '"year": integer or null, "title": string, "container": string, '
    '"volume": string, "issue": string, "pages": string, "doi": string, '
    '"type": "article"|"book"|"chapter"|"thesis"|"report"|"unknown"}\n\n'
    "Rules:\n"
    "- Do NOT echo the original text — only the structured fields above.\n"
    "- `container` is the journal name, book title, or proceedings title.\n"
    "- `authors` in the order shown; split family/given names. For an "
    "organization or a single-token name, put it in `family` and leave `given` empty.\n"
    "- `pages` as a plain range like \"123-145\", no \"pp.\".\n"
    "- `year`: the publication year only.\n"
    "- Return one object per input entry; if an entry is not a real reference, "
    "use type \"unknown\" with empty fields (do not drop it).\n"
    "- Output ONLY the JSON array.\n\n"
)


def _parse_llm_json_array(text: str) -> list:
    """Extract a JSON array from LLM output, handling fences and <think> tags.

    strict=False so a raw control character inside a string (the LLM sometimes
    emits a literal newline/tab in a title) doesn't blow up the whole batch
    ('Invalid control character at …').
    """
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    m = re.search(r'```(?:json)?\s*(\[.*\])\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1), strict=False)
    if text.startswith('['):
        return json.loads(text, strict=False)
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        return json.loads(m.group(0), strict=False)
    raise ValueError(f'No JSON array found in LLM output: {text[:200]}')


class _AdaptiveBatcher:
    """Adaptive controller for references-per-LLM-call, with a moving ceiling.

    Starts by sending ONE reference (prove it works + measure latency), then:
      - **warms up fast** (exponential) toward the ceiling while responses are
        quick — cheap initial ramp from 1;
      - on a timeout / near-timeout, **lowers the ceiling a little** (−BACKOFF_STEP,
        not a halving) and keeps going just under it. Backing off hard wastes
        throughput when the wall is only a couple of entries away; nibbling down
        finds the edge.
      - the lowered ceiling is a *hard cap* on the batch, so we don't climb
        straight back into the same wall and re-incur an (expensive) 240s
        timeout. It **recovers slowly** — +1 only after RECOVER_AFTER consecutive
        fast batches at the ceiling — in case the slowdown was transient
        (e.g. another paper hammering the shared server at the same time).

    State persists across papers within a run (refs extraction is serialized in
    both the CLI and the desktop, so no locking needed).
    """
    # Tuned for a ~20 tok/s server with a large fixed per-call overhead, so
    # bigger batches amortize better. With `raw` no longer echoed, output is
    # ~80-130 tok/entry; a 20-entry call ≈ 2-3k tok ≈ 100-150s, safely under
    # the 240s references read timeout. The controller still self-corrects.
    MIN = 1
    MAX = 20
    TARGET_LO = 25.0    # under this → fast: warm up (exp) toward the ceiling
    TARGET_HI = 130.0   # over this → close to timeout, lower the ceiling
    MAX_CHARS = 5000    # hard input cap per call (keeps output under the timeout)
    BACKOFF_STEP = 3    # how much to drop the ceiling on a timeout / near-timeout
    RECOVER_AFTER = 6   # fast batches at the ceiling before nudging it up by 1

    def __init__(self, size: int = 1):
        self.size = size
        self.ceiling = self.MAX   # hard cap on size; lowered on backoff, recovers slowly
        self._good = 0            # consecutive fast batches while pinned at the ceiling

    def update(self, elapsed: float):
        if elapsed > self.TARGET_HI:
            self._backoff()                                   # near timeout → ease down
        elif elapsed < self.TARGET_LO:
            if self.size < self.ceiling:
                self.size = min(self.size * 2, self.ceiling)  # warm-up ramp toward ceiling
                self._good = 0
            else:
                # Pinned at the ceiling and still fast → maybe the wall moved up.
                self._good += 1
                if self._good >= self.RECOVER_AFTER:
                    self._good = 0
                    self.ceiling = min(self.MAX, self.ceiling + 1)
                    self.size = self.ceiling
        # in-band (TARGET_LO..TARGET_HI): a healthy size — hold steady.

    def shrink(self):
        """Ease down after a timeout, so we retry the same refs a bit smaller."""
        self._backoff()

    def _backoff(self):
        # Lower the ceiling a little (not a halving) and sit just under it; cap
        # regrowth here so we don't slam back into the same wall.
        self.ceiling = max(self.MIN, self.size - self.BACKOFF_STEP)
        self.size = self.ceiling
        self._good = 0


# Process-wide controller: warms up once, reused across papers (refs extraction
# is serialized in both the CLI and the desktop, so no locking needed).
_refs_batcher = _AdaptiveBatcher()


def _chunk_entries(entries: list, max_chars: int = 4500,
                   max_entries: int = 15) -> list:
    """Group entry strings into batches for the LLM.

    A batch ends at whichever comes first: `max_entries` entries or `max_chars`
    of input. Capping the *count* (not just input size) bounds the JSON the
    model has to generate per call — a single call producing dozens of entries
    can exceed the request read-timeout (the model generates near max_tokens).
    A single oversized entry still becomes its own chunk.
    """
    chunks = []
    cur, cur_len = [], 0
    for e in entries:
        if cur and (len(cur) >= max_entries or cur_len + len(e) > max_chars):
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(e)
        cur_len += len(e) + 1
    if cur:
        chunks.append(cur)
    return chunks


def extract_references_llm(
    file_hash: str, backend: str = 'qwen', base_url: str = '', label: str = '',
) -> tuple[list, str, str, bool]:
    """Parse a paper's references section into structured entries via LLM.

    Args:
        file_hash: SHA256 hash of the citing PDF.
        backend: 'qwen' (ocrserver, default) or 'claude'.
        base_url: ocrserver URL (qwen). If empty, read from preferences.

    Returns:
        (entries, source_label, model_version, complete). `entries` is a list of
        dicts each carrying the parsed fields plus 'raw' and 'parse_confidence';
        it is EMPTY when no references section was found (a valid "checked,
        none" outcome — the caller should mark the paper checked, not retry).
        `complete` is False when one or more batches were skipped (timeout at the
        floor, or malformed JSON): the returned entries are PARTIAL and worth
        saving, but the caller should leave the paper unchecked so a later run
        can re-parse it. Raises ValueError only when the OCR text itself is
        missing (genuine error — retry after OCR), or RuntimeError on misconfig.
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
        return [], source, model_version, True

    entries = split_reference_entries(block)

    if backend == 'qwen':
        from .preferences import get_pref
        url = base_url or get_pref('ocr_pod_url', '')
        if not url:
            raise RuntimeError('Server URL not configured in Preferences')

    import requests as _req
    total = len(entries)
    parsed = []
    complete = True   # flips False if any batch is skipped (timeout / bad JSON)
    i = 0
    while i < total:
        # Take up to the current adaptive batch size, also bounded by chars.
        size = _refs_batcher.size
        batch, chars = [], 0
        while (i + len(batch) < total and len(batch) < size
               and (not batch or chars + len(entries[i + len(batch)])
                    <= _AdaptiveBatcher.MAX_CHARS)):
            chars += len(entries[i + len(batch)]) + 1
            batch.append(entries[i + len(batch)])

        prompt = _REFS_PROMPT + '--- REFERENCES TEXT ---\n' + '\n\n'.join(batch)
        tag = f'{label} ' if label else ''
        if backend == 'qwen':
            # Scale by INPUT size, not just entry count: a single un-split blob
            # is one "entry" but yields many reference objects — sizing by count
            # alone (≈712) truncated the JSON ('Unterminated string').
            in_chars = sum(len(b) for b in batch)
            mt = min(8192, max(len(batch) * 256, in_chars // 2) + 1024)
            t0 = time.monotonic()
            try:
                raw = _call_qwen(prompt, url, max_tokens=mt, read_timeout=240,
                                 retries=0, label=label)
            except (_req.exceptions.Timeout, _req.exceptions.ConnectionError):
                # Too slow at this size — shrink and retry the SAME refs, unless
                # already at the floor (then it's a real failure).
                if _refs_batcher.size > _AdaptiveBatcher.MIN:
                    _refs_batcher.shrink()
                    logger.info('%srefs %d/%d: timeout at batch %d → shrink to %d, '
                                'retrying', tag, i + len(batch), total, len(batch),
                                _refs_batcher.size)
                    continue
                # At the floor and still timing out — skip THIS batch (lose its
                # refs) but keep what we've parsed so far and carry on, rather
                # than discarding the whole paper. Mark the result incomplete so
                # the caller can re-run it later.
                logger.info('%srefs %d/%d: timeout at batch %d (already at floor) '
                            '→ skipping %d refs', tag, i + len(batch), total,
                            len(batch), len(batch))
                complete = False
                i += len(batch)
                continue
            dt = time.monotonic() - t0
            _refs_batcher.update(dt)
            logger.info('%srefs %d/%d: %d in %.1fs → next batch %d',
                        tag, i + len(batch), total, len(batch), dt, _refs_batcher.size)
        else:
            raw = _call_claude(prompt)

        try:
            items = [it for it in _parse_llm_json_array(raw) if isinstance(it, dict)]
        except (json.JSONDecodeError, ValueError) as ex:
            # The model returned malformed / truncated JSON for this batch. Skip
            # just this batch — keep the references parsed from the other batches
            # — instead of losing the whole paper. Flag the result incomplete.
            logger.info('%srefs %d/%d: bad JSON for batch %d (%s) → skipping %d refs',
                        tag, i + len(batch), total, len(batch),
                        str(ex)[:60], len(batch))
            complete = False
            i += len(batch)
            continue
        # We split the entries ourselves, so attach the original text as `raw`
        # by position (store-first) instead of paying the LLM to echo it. Only
        # when counts line up; otherwise leave raw empty (fields are still valid).
        aligned = len(items) == len(batch)
        for k, item in enumerate(items):
            if aligned:
                item['raw'] = batch[k]
            item.setdefault('parse_confidence', confidence)
            parsed.append(item)
        i += len(batch)

    return parsed, source, model_version, complete


# ===========================================================================
# P11 Phase 2 — LLM merge adjudication for external-work dedup (pass 2).
# Deterministic exact dedup (references.canonicalize_reference) runs first; this
# is only asked to judge a small cluster of near-duplicate candidates that the
# exact pass left separate. Conservative: keep entries apart unless clearly the
# same work.
# ===========================================================================

_WORK_MERGE_PROMPT = (
    "You are de-duplicating bibliographic references. Below is a NUMBERED list "
    "of candidate works parsed from OCR'd reference lists, so the text may be "
    "noisy, abbreviated, or partially garbled. Some entries may be the SAME "
    "underlying work; others are different works that merely share an author or "
    "year.\n\n"
    "Group together ONLY entries that refer to the SAME work (same authors + "
    "same title + same year; a journal/volume/page or initials difference is OK "
    "if the identity is clearly the same). Be CONSERVATIVE: if you are not "
    "confident two entries are the same work, keep them in separate groups.\n\n"
    "Output STRICT JSON only (no prose, no markdown fence): an array of groups, "
    "each group an array of the integer indices that refer to the same work. "
    "Include EVERY index exactly once; an entry that matches nothing is its own "
    "group of one. Example: [[0,2],[1],[3]]\n\n"
    "--- CANDIDATES ---\n"
)


def _work_candidate_line(idx: int, w) -> str:
    """One compact descriptor line for a CitedWork in the merge prompt."""
    try:
        authors = json.loads(w.authors_json or '[]')
    except (json.JSONDecodeError, TypeError):
        authors = []
    names = []
    for a in authors[:3]:
        if isinstance(a, dict):
            fam, giv = a.get('family', ''), a.get('given', '')
            names.append(f'{fam}, {giv}'.strip(', ') if fam else giv)
        else:
            names.append(str(a))
    parts = [f'[{idx}]']
    if names:
        parts.append('authors: ' + '; '.join(n for n in names if n))
    if w.year:
        parts.append(f'year: {w.year}')
    if w.title:
        parts.append(f'title: {w.title}')
    if w.container:
        parts.append(f'in: {w.container}')
    if w.doi:
        parts.append(f'doi: {w.doi}')
    return ' | '.join(parts)


def llm_match_works(works, backend: str = 'qwen', base_url: str = '',
                    read_timeout: int = 120) -> list:
    """Ask the LLM which of `works` (a small cluster of CitedWork rows) are the
    same work. Returns a list of groups (lists of indices into `works`); every
    index appears exactly once. Pure LLM call (no DB) — safe in worker threads.
    """
    prompt = _WORK_MERGE_PROMPT + '\n'.join(
        _work_candidate_line(i, w) for i, w in enumerate(works))
    if backend == 'qwen':
        from .preferences import get_pref
        url = base_url or get_pref('ocr_pod_url', '')
        if not url:
            raise RuntimeError('Server URL not configured in Preferences')
        raw = _call_qwen(prompt, url, max_tokens=1024,
                         read_timeout=read_timeout, retries=1)
    else:
        raw = _call_claude(prompt)

    groups = _parse_llm_json_array(raw)
    seen, clean = set(), []
    for g in groups:
        if not isinstance(g, list):
            continue
        gg = [i for i in g if isinstance(i, int) and 0 <= i < len(works)
              and i not in seen]
        for i in gg:
            seen.add(i)
        if gg:
            clean.append(gg)
    # any index the model dropped becomes its own singleton (don't lose nodes)
    for i in range(len(works)):
        if i not in seen:
            clean.append([i])
    return clean
