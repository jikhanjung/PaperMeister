#!/usr/bin/env python3
"""Step 6: Run claude -p (Haiku) on the eval set, score against ground truth."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Paper, PaperFile
from papermeister.biblio import BiblioResult, load_ocr_pages, extract_first_pages
from papermeister.biblio_eval import overall_score

EVAL_SET_PATH = os.path.expanduser('~/.papermeister/eval_set.json')


def results_path_for(model):
    short = model.replace('claude-', '').split('-')[0]
    return os.path.expanduser(f'~/.papermeister/eval_results_{short}.json')

PROMPT_TEMPLATE = """You are extracting bibliographic metadata from the first pages of an academic document (OCR'd text). The text below may contain noise, broken lines, and layout artifacts.

Your task: extract the bibliographic information that is EXPLICITLY present in the text. Do NOT guess or infer; if a field is not clearly stated, leave it empty/null.

Output STRICT JSON only (no prose, no markdown code fence) with this exact schema:
{{
  "title": string,
  "authors": [string],   // ordered as listed; format "First Last" if possible
  "year": integer or null,
  "journal": string,     // for books, the publisher; empty if neither
  "doi": string,
  "abstract": string,
  "doc_type": "article" | "book" | "chapter" | "thesis" | "report" | "unknown",
  "language": string,    // ISO 639-1 (en, ko, zh, ja, fr, de, ...)
  "confidence": "high" | "medium" | "low",
  "notes": string
}}

Rules:
- Authors must be in the order shown in the document.
- Year: the publication year, not "received" or "accepted" dates.
- DOI: only if explicitly written (e.g., "10.xxxx/...").
- Set confidence "low" if the first pages look like a cover/TOC and you had to guess.
- Output ONLY the JSON object. Nothing else.

--- DOCUMENT TEXT ---
{text}
--- END ---
"""


def call_claude(prompt, model='claude-haiku-4-5', timeout=120):
    """Run claude -p, return parsed bibliographic dict or None on failure."""
    try:
        proc = subprocess.run(
            ['claude', '-p', '--model', model, '--output-format', 'json'],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
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
        return None, f'claude error: {envelope.get("result", "")[:200]}'

    text = envelope.get('result', '').strip()
    # Strip optional ```json ... ``` fence
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    # Or pull the first {...} block
    if not text.startswith('{'):
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f'json parse: {e}: {text[:200]}'


def get_ground_truth(paper_id):
    p = Paper.get_by_id(paper_id)
    authors = list(Author.select().where(Author.paper == p).order_by(Author.order))
    return {
        'title': p.title,
        'authors': [a.name for a in authors],
        'year': p.year,
        'journal': p.journal or '',
        'doi': p.doi or '',
    }


def get_pdf_hash(paper_id):
    pf = (
        PaperFile.select()
        .where(
            (PaperFile.paper == paper_id)
            & (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
        )
        .first()
    )
    return pf.hash if pf else ''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='0 = full eval set')
    parser.add_argument('--model', default='claude-haiku-4-5')
    parser.add_argument('--resume', action='store_true', help='skip already-processed papers in results file')
    args = parser.parse_args()

    init_db()
    results_path = results_path_for(args.model)
    with open(EVAL_SET_PATH, encoding='utf-8') as f:
        eval_set = json.load(f)
    paper_ids = eval_set['paper_ids']
    if args.limit > 0:
        paper_ids = paper_ids[:args.limit]

    results = {}
    if args.resume and os.path.exists(results_path):
        with open(results_path, encoding='utf-8') as f:
            results = json.load(f)
        print(f'Resuming with {len(results)} existing results')

    print(f'Processing {len(paper_ids)} papers with {args.model}')

    for i, pid in enumerate(paper_ids, 1):
        key = str(pid)
        if key in results:
            continue
        h = get_pdf_hash(pid)
        if not h:
            results[key] = {'error': 'no hash'}
            continue
        pages = load_ocr_pages(h)
        text = extract_first_pages(pages)
        if not text:
            results[key] = {'error': 'no ocr text'}
            continue

        prompt = PROMPT_TEMPLATE.format(text=text)
        t0 = time.time()
        pred, err = call_claude(prompt, model=args.model)
        elapsed = time.time() - t0

        if err:
            results[key] = {'error': err, 'elapsed': elapsed}
            print(f'[{i}/{len(paper_ids)}] pid={pid} ERROR ({elapsed:.1f}s): {err[:80]}')
        else:
            gt = get_ground_truth(pid)
            scores = overall_score(gt, pred)
            results[key] = {
                'pred': pred,
                'gt': gt,
                'scores': scores,
                'elapsed': elapsed,
            }
            print(f'[{i}/{len(paper_ids)}] pid={pid} ok ({elapsed:.1f}s) overall={scores["overall"]:.2f}')

        # Save incrementally
        if i % 5 == 0:
            with open(results_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Aggregate
    sums = defaultdict(float)
    counts = 0
    errors = 0
    for v in results.values():
        if 'scores' in v:
            for k, s in v['scores'].items():
                sums[k] += s
            counts += 1
        elif 'error' in v:
            errors += 1

    print(f'\n=== Aggregate ({counts} ok, {errors} errors) ===')
    for k in ('title', 'authors', 'year', 'journal', 'doi', 'overall'):
        avg = sums[k] / counts if counts else 0
        print(f'  {k:>10}: {avg:.3f}')


if __name__ == '__main__':
    main()
