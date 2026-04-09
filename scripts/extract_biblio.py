#!/usr/bin/env python3
"""Phase D: LLM extraction of bibliographic info for all OCR-processed papers.

Saves results to PaperBiblio table. Skips already-extracted (paper_id, file_hash, source).
Uses claude -p (Claude Code subprocess) — counts against the Max plan session quota.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile, PaperBiblio, Folder, Source, db
from papermeister.biblio import load_ocr_pages, extract_first_pages

PROMPT_TEMPLATE = """You are extracting bibliographic metadata from the first pages of an academic document (OCR'd text). The text below may contain noise, broken lines, and layout artifacts.

Your task: extract the bibliographic information that is EXPLICITLY present in the text. Do NOT guess or infer; if a field is not clearly stated, leave it empty/null.

Output STRICT JSON only (no prose, no markdown code fence) with this exact schema:
{{
  "title": string,
  "authors": [string],
  "year": integer or null,
  "journal": string,
  "doi": string,
  "abstract": string,
  "doc_type": "article" | "book" | "chapter" | "thesis" | "report" | "unknown",
  "language": string,
  "confidence": "high" | "medium" | "low",
  "needs_visual_review": boolean,
  "notes": string
}}

Rules:
- Authors must be in the order shown in the document.
- Year: the publication year, not "received" or "accepted" dates.
- DOI: only if explicitly written.
- Set needs_visual_review=true if the first pages look like a journal-issue cover, a table of contents, or any layout where spatial/visual structure is essential to identify the document — i.e. plain text alone is not enough to be confident.
- Output ONLY the JSON object.

--- DOCUMENT TEXT ---
{text}
--- END ---
"""


def call_claude(prompt, model='claude-haiku-4-5', timeout=120):
    try:
        proc = subprocess.run(
            ['claude', '-p', '--model', model, '--output-format', 'json'],
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


def fetch_targets(args):
    """Return list of (paper_id, file_hash). Filter by --scope and skip already extracted."""
    query = (
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
        )
    )

    if args.paper_ids:
        ids = [int(x) for x in args.paper_ids.split(',') if x.strip()]
        query = query.where(Paper.id.in_(ids))
    elif args.scope == 'standalone':
        # Standalone: Paper.zotero_key == PaperFile.zotero_key
        query = query.where(Paper.zotero_key == PaperFile.zotero_key)
    elif args.scope == 'directory':
        query = query.join(Folder).join(Source).where(Source.source_type == 'directory')
    elif args.scope == 'missing':
        # Papers with no title or no authors
        query = query.where((Paper.title == '') | (Paper.year.is_null(True)))

    targets = []
    for pf in query:
        targets.append((pf.paper.id, pf.hash))

    if args.skip_existing:
        existing = set(
            (b.paper_id, b.file_hash) for b in
            PaperBiblio.select(PaperBiblio.paper_id, PaperBiblio.file_hash)
            .where(PaperBiblio.source == f'llm-{args.model_short}')
        )
        targets = [t for t in targets if t not in existing]

    return targets


def process_one(paper_id, file_hash, model, model_short):
    pages = load_ocr_pages(file_hash)
    if not pages:
        return paper_id, None, 'no ocr pages'
    text = extract_first_pages(pages)
    if not text:
        return paper_id, None, 'no text'
    prompt = PROMPT_TEMPLATE.format(text=text)
    pred, err = call_claude(prompt, model=model)
    return paper_id, pred, err


def save_extraction(paper_id, file_hash, pred, model_short, model):
    PaperBiblio.create(
        paper=paper_id,
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
        needs_visual_review=bool(pred.get('needs_visual_review', False)),
        notes=pred.get('notes', '') or '',
        source=f'llm-{model_short}',
        model_version=model,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='claude-haiku-4-5')
    parser.add_argument('--scope', choices=['all', 'standalone', 'directory', 'missing'], default='all')
    parser.add_argument('--paper-ids', default='', help='Comma-separated paper IDs to override scope')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--skip-existing', action='store_true', default=True)
    parser.add_argument('--source-suffix', default='', help='Append to source label e.g. "v2"')
    args = parser.parse_args()

    init_db()
    args.model_short = args.model.replace('claude-', '').split('-')[0]
    if args.source_suffix:
        args.model_short = f'{args.model_short}-{args.source_suffix}'

    targets = fetch_targets(args)
    print(f'Targets ({args.scope}): {len(targets)}')
    if args.limit > 0:
        targets = targets[:args.limit]
        print(f'  --limit {args.limit} → {len(targets)}')

    if not targets:
        return

    ok = 0
    err = 0
    t0 = time.time()

    def worker(t):
        pid, h = t
        return process_one(pid, h, args.model, args.model_short)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, t): t for t in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            pid, pred, error = fut.result()
            t = futures[fut]
            if error:
                err += 1
                print(f'[{i}/{len(targets)}] pid={pid} ERR: {error[:80]}', flush=True)
            else:
                try:
                    save_extraction(pid, t[1], pred, args.model_short, args.model)
                    ok += 1
                    if i % 25 == 0 or i <= 5:
                        title = (pred.get('title', '') or '')[:50]
                        print(f'[{i}/{len(targets)}] pid={pid} ok | {title}', flush=True)
                except Exception as e:
                    err += 1
                    print(f'[{i}/{len(targets)}] pid={pid} SAVE ERR: {e}', flush=True)

    elapsed = time.time() - t0
    print(f'\n=== Done ===')
    print(f'  ok:    {ok}')
    print(f'  err:   {err}')
    print(f'  time:  {elapsed:.1f}s ({elapsed/max(1,len(targets)):.1f}s/paper)')


if __name__ == '__main__':
    main()
