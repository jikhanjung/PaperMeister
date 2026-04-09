#!/usr/bin/env python3
"""Vision pass: render first/last PDF pages as PNG and ask Claude to extract biblio.

Uses claude -p with the Read tool — the prompt references local image files.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile, PaperBiblio
from papermeister.preferences import get_pref
from papermeister.zotero_client import ZoteroClient

PROMPT_TEMPLATE = """You are extracting bibliographic metadata from images of an academic document's first pages.

Please use the Read tool to view these page images:
{image_lines}

After viewing them, extract the bibliographic information that is present. Pay attention to spatial layout: journal title at top, table of contents in middle, issue number/date at bottom typically indicate a JOURNAL ISSUE COVER, not a single article.

Output STRICT JSON only (no prose, no markdown code fence) with this exact schema:
{{
  "title": string,                  // for a journal issue, the journal name + issue label
  "authors": [string],              // empty for journal issues
  "year": integer or null,
  "journal": string,                // publication title (or publisher for books)
  "doi": string,
  "abstract": string,
  "doc_type": "article" | "book" | "chapter" | "thesis" | "report" | "journal_issue" | "unknown",
  "language": string,               // ISO 639-1
  "issue": string,                  // for journal issues: issue number/volume label e.g. "No. 3", "第3号"
  "publication_date": string,       // human readable date as printed
  "table_of_contents": [string],    // for journal issues, list of article titles inside
  "confidence": "high" | "medium" | "low",
  "notes": string
}}

Rules:
- **Preserve the original script and language exactly as printed.** Do NOT translate or romanize. If the journal name is "化石", write "化石" — not "Fossils" or "Kaseki". If a Japanese title is on the cover, keep it in Japanese. If both Japanese and English appear on the cover (bilingual), prefer the dominant/original-script form for the main `title` and `journal` fields.
- If this is clearly a journal issue cover (one journal name dominant, table of contents listed, issue number/date present), set doc_type="journal_issue".
- For journal_issue: leave authors empty; put the journal name in `journal`; put the issue label in `issue`; list contained articles in `table_of_contents` (in original language).
- For a single article, fill authors and leave issue/table_of_contents empty.
- Output ONLY the JSON object after viewing the images.
"""


def render_pdf_pages(pdf_path, out_dir, pages=(0, -1), dpi=150):
    """Render selected pages of a PDF to PNG. Returns list of image paths."""
    doc = fitz.open(pdf_path)
    n = len(doc)
    out_paths = []
    selected = []
    for p in pages:
        idx = p if p >= 0 else n + p
        if 0 <= idx < n and idx not in selected:
            selected.append(idx)
    for idx in selected:
        page = doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        out = os.path.join(out_dir, f'page_{idx + 1}.png')
        pix.save(out)
        out_paths.append(out)
    doc.close()
    return out_paths


def call_claude_vision(prompt, model='claude-haiku-4-5', timeout=180):
    try:
        proc = subprocess.run(
            ['claude', '-p', '--model', model, '--output-format', 'json',
             '--allowed-tools', 'Read'],
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    if proc.returncode != 0:
        return None, f'exit {proc.returncode}: {proc.stderr[:200]}'
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, f'envelope parse: {proc.stdout[:200]}'
    if envelope.get('is_error'):
        return None, f'claude error: {envelope.get("result","")[:200]}'
    text = envelope.get('result', '').strip()
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    if not text.startswith('{'):
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f'json parse: {e}: {text[:200]}'


def save_biblio(paper, file_hash, pred, source, model):
    notes = pred.get('notes', '') or ''
    extras = []
    if pred.get('issue'): extras.append(f"issue={pred['issue']}")
    if pred.get('publication_date'): extras.append(f"date={pred['publication_date']}")
    if pred.get('table_of_contents'):
        toc = '; '.join(pred['table_of_contents'][:20])
        extras.append(f"toc=[{toc}]")
    if extras:
        notes = (notes + ' | ' + ' '.join(extras)).strip(' |')

    PaperBiblio.create(
        paper=paper,
        file_hash=file_hash,
        title=pred.get('title', '') or '',
        authors_json=json.dumps(pred.get('authors', []) or [], ensure_ascii=False),
        year=pred.get('year') if isinstance(pred.get('year'), int) else None,
        journal=pred.get('journal', '') or '',
        doi=pred.get('doi', '') or '',
        abstract=pred.get('abstract', '') or '',
        doc_type=pred.get('doc_type', 'unknown') or 'unknown',
        language=pred.get('language', '') or '',
        confidence=pred.get('confidence', '') or '',
        needs_visual_review=False,  # this IS the visual review
        notes=notes,
        source=source,
        model_version=model,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--paper-ids', required=True, help='Comma-separated paper IDs')
    parser.add_argument('--model', default='claude-haiku-4-5')
    parser.add_argument('--pages', default='0,-1', help='comma-separated page indices to render (0=first, -1=last)')
    parser.add_argument('--dpi', type=int, default=150)
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.')
        return 1
    client = ZoteroClient(user_id, api_key)
    pages = tuple(int(x) for x in args.pages.split(','))
    model_short = args.model.replace('claude-', '').split('-')[0]
    source = f'llm-{model_short}-vision'

    pids = [int(x) for x in args.paper_ids.split(',')]

    tmpdir = tempfile.mkdtemp(prefix='biblio_vision_')
    print(f'Using temp dir: {tmpdir}')

    for i, pid in enumerate(pids, 1):
        try:
            p = Paper.get_by_id(pid)
        except Paper.DoesNotExist:
            print(f'[{i}/{len(pids)}] pid={pid} NOT FOUND')
            continue

        # Find the original PDF PaperFile (Zotero attachment)
        pf = (PaperFile.select()
              .where((PaperFile.paper == p)
                     & (PaperFile.status == 'processed')
                     & (PaperFile.zotero_key != '')
                     & (~PaperFile.path.endswith('.json')))
              .first())
        if not pf:
            print(f'[{i}/{len(pids)}] pid={pid} no PDF PaperFile')
            continue

        print(f'\n[{i}/{len(pids)}] pid={pid} key={pf.zotero_key}', flush=True)
        try:
            pdf_path = client.download_attachment(pf.zotero_key)
        except Exception as e:
            print(f'    download failed: {e}')
            continue

        try:
            paper_dir = os.path.join(tmpdir, f'pid{pid}')
            os.makedirs(paper_dir, exist_ok=True)
            image_paths = render_pdf_pages(pdf_path, paper_dir, pages=pages, dpi=args.dpi)
            print(f'    rendered {len(image_paths)} pages')

            image_lines = '\n'.join(f'- {p}' for p in image_paths)
            prompt = PROMPT_TEMPLATE.format(image_lines=image_lines)
            t0 = time.time()
            pred, err = call_claude_vision(prompt, model=args.model)
            elapsed = time.time() - t0

            if err:
                print(f'    ERROR ({elapsed:.1f}s): {err[:150]}')
                continue
            print(f'    ok ({elapsed:.1f}s) doc_type={pred.get("doc_type")} title={(pred.get("title") or "")[:60]}')
            save_biblio(p, pf.hash, pred, source, args.model)
        finally:
            try: os.unlink(pdf_path)
            except OSError: pass

    print('\nDone.')


if __name__ == '__main__':
    main()
