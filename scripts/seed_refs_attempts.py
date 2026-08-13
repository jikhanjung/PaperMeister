#!/usr/bin/env python3
"""Seed `Paper.references_attempts` for papers that were already failing.

The give-up counter starts at zero for every existing paper, because the
migration records attempts we have observed rather than guessing. That is the
right default, but it means the papers that have been failing since July still
get three more goes at the head of the queue before they drop out — and they
are exactly the ones that made the queue slow.

This marks them as already exhausted, once, so the next full run skips them.

WHICH PAPERS: a partial parse saves the references it did manage and leaves
`references_checked` False so a later run can replace them. So a paper that is
unchecked *and* already has Reference rows can only have come back partial —
no log parsing needed, and no guessing.

The one case that signature misses is "model returned nothing for a located
section" (devlog 079), which saves no rows and is therefore indistinguishable
in the database from a paper nobody has tried yet. Name those with --paper-ids
or --titles.

Convention: dry-run by default; pass --execute to write.

    python scripts/seed_refs_attempts.py
    python scripts/seed_refs_attempts.py --execute
    python scripts/seed_refs_attempts.py --titles "Colorful world of Trilobites" --execute
    python scripts/seed_refs_attempts.py --reset --execute      # undo

Run it on Windows with the app closed, like the other data-mutating scripts.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, Reference
from papermeister.references import MAX_REFS_ATTEMPTS


def _short(title, n=54):
    t = ' '.join((title or '').split())
    return (t[:n] + '…') if len(t) > n else (t or '(untitled)')


def find_partials():
    """Papers left unchecked that nonetheless have saved references."""
    return list(
        Paper.select()
        .where(
            (Paper.references_checked == False)  # noqa: E712 (peewee)
            & (Paper.id.in_(Reference.select(Reference.citing_paper)))
        )
        .order_by(Paper.id)
    )


def find_named(paper_ids: str, titles: str):
    """Papers named explicitly, for the cases the signature cannot see."""
    found = {}
    if paper_ids:
        ids = [int(x) for x in paper_ids.split(',') if x.strip()]
        for p in Paper.select().where(Paper.id.in_(ids)):
            found[p.id] = p
        missing = set(ids) - set(found)
        if missing:
            print(f'  ! no paper with id {sorted(missing)}')
    for raw in (t.strip() for t in titles.split('|') if t.strip()):
        matches = list(Paper.select().where(Paper.title.contains(raw)))
        if not matches:
            print(f'  ! no title matching {raw!r}')
        elif len(matches) > 1:
            # Don't guess between them — a wrong pick retires the wrong paper.
            print(f'  ! {raw!r} matches {len(matches)} papers, skipping:')
            for p in matches[:5]:
                print(f'      #{p.id} {_short(p.title)}')
        else:
            found[matches[0].id] = matches[0]
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paper-ids', default='',
                    help='Comma-separated paper ids to include as well')
    ap.add_argument('--titles', default='',
                    help='Pipe-separated title substrings to include as well; '
                         'a substring matching several papers is skipped rather '
                         'than guessed at')
    ap.add_argument('--attempts', type=int, default=MAX_REFS_ATTEMPTS,
                    help=f'Value to write (default {MAX_REFS_ATTEMPTS}, the '
                         f'threshold at which a paper leaves the normal run)')
    ap.add_argument('--reset', action='store_true',
                    help='Write 0 instead — puts the papers back in the normal run')
    ap.add_argument('--no-signature', action='store_true',
                    help='Only touch --paper-ids / --titles, skipping the '
                         'unchecked-but-has-references scan')
    ap.add_argument('--execute', action='store_true',
                    help='Write to the DB (default: dry-run preview)')
    args = ap.parse_args()

    init_db()
    value = 0 if args.reset else args.attempts

    if args.reset:
        # Undo works off the counter itself, not the signature that seeded it:
        # papers named with --titles have no saved references to re-derive from,
        # so a signature scan could not reach them to put them back.
        papers = {p.id: p for p in
                  Paper.select().where(Paper.references_attempts > 0)}
        print(f'Papers with a non-zero attempt count: {len(papers)}')
    elif args.no_signature:
        papers = {}
    else:
        papers = {p.id: p for p in find_partials()}
        print(f'Unchecked papers with saved references (previous PARTIAL): {len(papers)}')
    if args.paper_ids or args.titles:
        named = find_named(args.paper_ids, args.titles)
        extra = {k: v for k, v in named.items() if k not in papers}
        papers.update(named)
        print(f'Named explicitly: {len(named)} ({len(extra)} not already found)')

    if not papers:
        print('Nothing to do.')
        return

    counts = {p.id: n for p, n in (
        (p, Reference.select().where(Reference.citing_paper == p.id).count())
        for p in papers.values())}
    todo = [p for p in papers.values() if p.references_attempts != value]

    print(f'\nWould set references_attempts = {value} on {len(todo)} paper(s) '
          f'({len(papers) - len(todo)} already there):')
    for p in sorted(todo, key=lambda p: -counts[p.id])[:25]:
        print(f'  #{p.id:<6} {counts[p.id]:>5} refs saved  '
              f'(attempts {p.references_attempts} -> {value})  {_short(p.title)}')
    if len(todo) > 25:
        print(f'  ... and {len(todo) - 25} more')

    if not args.execute:
        print('\nDRY-RUN (no --execute). Nothing written.')
        return

    ids = [p.id for p in todo]
    updated = Paper.update(references_attempts=value).where(Paper.id.in_(ids)).execute()
    print(f'\nUpdated {updated} paper(s).')
    if not args.reset:
        print('A normal run now skips them; "Retry Failed References…" in the '
              'desktop (or --only-failed on extract_references.py) brings them back.')


if __name__ == '__main__':
    main()
