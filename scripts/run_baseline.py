#!/usr/bin/env python3
"""Step 5: Baseline regex/heuristic extractor evaluated against the eval set."""

import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Paper, PaperFile
from papermeister.biblio import BiblioResult, load_ocr_pages, extract_first_pages
from papermeister.biblio_eval import overall_score

EVAL_SET_PATH = os.path.expanduser('~/.papermeister/eval_set.json')

DOI_RE = re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+')
YEAR_RE = re.compile(r'\b(19[0-9]{2}|20[0-2][0-9])\b')
HEADER_RE = re.compile(r'^#{1,3}\s+(.+?)\s*$', re.MULTILINE)


def extract_baseline(text: str) -> BiblioResult:
    """Extract minimal info via regex/heuristics. No LLM."""
    r = BiblioResult()

    # DOI: first match
    m = DOI_RE.search(text)
    if m:
        # strip trailing punctuation that often gets included
        r.doi = m.group(0).rstrip('.,;)')

    # Year: most frequent year on first pages
    years = YEAR_RE.findall(text)
    if years:
        # pick the most common; tie-break by first occurrence
        counts = defaultdict(int)
        for y in years:
            counts[int(y)] += 1
        r.year = max(counts.items(), key=lambda kv: (kv[1], -years.index(str(kv[0]))))[0]

    # Title: first markdown header (very weak heuristic)
    h = HEADER_RE.search(text)
    if h:
        r.title = h.group(1).strip()

    # journal/authors/abstract: not attempted in baseline
    return r


def get_ground_truth(paper_id: int) -> dict:
    p = Paper.get_by_id(paper_id)
    authors = list(
        Author.select().where(Author.paper == p).order_by(Author.order)
    )
    return {
        'title': p.title,
        'authors': [a.name for a in authors],
        'year': p.year,
        'journal': p.journal or '',
        'doi': p.doi or '',
    }


def get_pdf_hash(paper_id: int) -> str:
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
    init_db()
    with open(EVAL_SET_PATH, encoding='utf-8') as f:
        eval_set = json.load(f)
    paper_ids = eval_set['paper_ids']
    print(f'Eval set: {len(paper_ids)} papers')

    sums = defaultdict(float)
    counts = 0
    misses = 0

    field_hits = defaultdict(int)

    for pid in paper_ids:
        h = get_pdf_hash(pid)
        if not h:
            misses += 1
            continue
        pages = load_ocr_pages(h)
        if not pages:
            misses += 1
            continue
        text = extract_first_pages(pages)
        pred = extract_baseline(text)
        gt = get_ground_truth(pid)
        scores = overall_score(gt, pred.to_dict())
        for k, v in scores.items():
            sums[k] += v
        counts += 1

        if scores['doi'] == 1.0:
            field_hits['doi'] += 1
        if scores['year'] == 1.0:
            field_hits['year'] += 1
        if scores['title'] >= 0.8:
            field_hits['title>=0.8'] += 1

    print(f'\nProcessed: {counts}, missing OCR: {misses}\n')
    print('=== Average scores (baseline regex) ===')
    for k in ('title', 'authors', 'year', 'journal', 'doi', 'overall'):
        avg = sums[k] / counts if counts else 0
        print(f'  {k:>10}: {avg:.3f}')

    print(f'\n=== Field hit rates ===')
    print(f'  DOI exact:    {field_hits["doi"]}/{counts} ({100*field_hits["doi"]/counts:.1f}%)')
    print(f'  Year exact:   {field_hits["year"]}/{counts} ({100*field_hits["year"]/counts:.1f}%)')
    print(f'  Title ≥0.8:   {field_hits["title>=0.8"]}/{counts} ({100*field_hits["title>=0.8"]/counts:.1f}%)')


if __name__ == '__main__':
    main()
