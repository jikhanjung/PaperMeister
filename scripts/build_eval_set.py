#!/usr/bin/env python3
"""Build a stratified evaluation set of papers with reliable ground-truth metadata.

Output: ~/.papermeister/eval_set.json
  {"seed": 42, "size": 200, "strata": {...}, "paper_ids": [...]}
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Author, Paper, PaperFile, Folder, Source

EVAL_SET_PATH = os.path.expanduser('~/.papermeister/eval_set.json')


def fetch_candidates():
    """Return list of (paper_id, title, year, journal) for all eligible papers."""
    query = (
        Paper.select(Paper.id, Paper.title, Paper.year, Paper.journal)
        .join(Folder).join(Source)
        .switch(Paper)
        .join(PaperFile)
        .where(
            (Source.source_type == 'zotero')
            & (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (~PaperFile.path.endswith('.json'))
            & (Paper.title != '')
            & (Paper.year.is_null(False))
        )
        .distinct()
    )
    rows = []
    for p in query:
        # Must have at least one author
        if Author.select().where(Author.paper == p).exists():
            rows.append((p.id, p.title, p.year, p.journal or ''))
    return rows


def is_cjk(s):
    """Heuristic: contains a CJK unified ideograph or Hangul."""
    for ch in s:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x30FF:    # Hiragana/Katakana
            return True
        if 0x3400 <= cp <= 0x9FFF:    # CJK Unified Ideographs (incl. extension A)
            return True
        if 0xAC00 <= cp <= 0xD7AF:    # Hangul Syllables
            return True
    return False


def stratify(rows):
    """Split candidates into strata."""
    strata = {
        'cjk': [],
        'old': [],          # year < 1960
        'no_journal': [],   # likely book/report
        'with_journal': [],
    }
    for r in rows:
        pid, title, year, journal = r
        if is_cjk(title):
            strata['cjk'].append(pid)
        elif year is not None and year < 1960:
            strata['old'].append(pid)
        elif not journal:
            strata['no_journal'].append(pid)
        else:
            strata['with_journal'].append(pid)
    return strata


def sample_stratified(strata, total, rng):
    """Sample paper_ids respecting target proportions; fall back if a stratum is too small."""
    # Targets: with_journal 65%, no_journal 15%, cjk 10%, old 10%
    targets = {
        'with_journal': int(total * 0.65),
        'no_journal':   int(total * 0.15),
        'cjk':          int(total * 0.10),
        'old':          int(total * 0.10),
    }
    # Adjust rounding
    diff = total - sum(targets.values())
    targets['with_journal'] += diff

    picked = {}
    leftover_pool = []
    for name, target in targets.items():
        pool = list(strata[name])
        rng.shuffle(pool)
        take = pool[:target]
        picked[name] = take
        leftover_pool.extend(pool[target:])

    # If any stratum was short, fill from leftover
    chosen = sum((v for v in picked.values()), [])
    if len(chosen) < total:
        rng.shuffle(leftover_pool)
        need = total - len(chosen)
        chosen.extend(leftover_pool[:need])

    return picked, chosen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', type=int, default=200)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--out', default=EVAL_SET_PATH)
    args = parser.parse_args()

    init_db()
    rows = fetch_candidates()
    print(f'Eligible candidates: {len(rows)}')

    strata = stratify(rows)
    for name, ids in strata.items():
        print(f'  stratum "{name}": {len(ids)}')

    rng = random.Random(args.seed)
    picked, chosen = sample_stratified(strata, args.size, rng)

    print(f'\nPicked per stratum:')
    for name, ids in picked.items():
        print(f'  {name}: {len(ids)}')
    print(f'Total: {len(chosen)}')

    out = {
        'seed': args.seed,
        'size': args.size,
        'strata': {k: len(v) for k, v in picked.items()},
        'paper_ids': sorted(chosen),
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\nSaved → {args.out}')


if __name__ == '__main__':
    main()
