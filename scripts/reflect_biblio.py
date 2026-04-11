"""CLI wrapper for papermeister.biblio_reflect.

Examples:
    # Dry-run everything
    python scripts/reflect_biblio.py --dry-run

    # Apply to a specific source
    python scripts/reflect_biblio.py --source 3

    # Apply to a specific folder
    python scripts/reflect_biblio.py --folder 42

    # Single paper (mirror of GUI "Apply Biblio")
    python scripts/reflect_biblio.py --paper 1234
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from papermeister.database import init_db
from papermeister import biblio_reflect


def _parse_args():
    p = argparse.ArgumentParser(description='Reflect PaperBiblio into Paper per P08.')
    scope = p.add_mutually_exclusive_group()
    scope.add_argument('--source', type=int, help='Scope to a Source.id')
    scope.add_argument('--folder', type=int, help='Scope to a Folder.id')
    scope.add_argument('--paper', type=int, help='Single paper (GUI-style apply)')
    scope.add_argument('--paper-ids', type=str, help='Comma-separated paper ids')
    p.add_argument('--dry-run', action='store_true', help='Do not write any changes')
    p.add_argument(
        '--force', action='store_true',
        help='(Single-paper only) Replace non-empty Zotero fields where biblio '
             'has more data. Escape hatch for curated_author_shortfall etc.',
    )
    return p.parse_args()


def _print_stats(stats: biblio_reflect.ReflectStats, *, dry_run: bool):
    prefix = '[DRY RUN] ' if dry_run else ''
    print(f'{prefix}scanned:        {stats.scanned}')
    print(f'{prefix}auto_committed: {stats.auto_committed}')
    print(f'{prefix}needs_review:   {stats.needs_review}')
    print(f'{prefix}skipped:        {stats.skipped}')
    print(f'{prefix}errors:         {stats.errors}')
    if stats.reasons:
        print('reasons:')
        for k, v in sorted(stats.reasons.items(), key=lambda x: -x[1]):
            print(f'  {k:24s} {v}')


def main():
    args = _parse_args()
    init_db()

    if args.paper:
        decision, changed = biblio_reflect.apply_single(
            args.paper, force_override=args.force,
        )
        print(
            f'paper={args.paper} decision={decision.action} '
            f'reason={decision.reason!r} changed={changed} '
            f'force={args.force}'
        )
        return 0

    paper_ids = None
    if args.paper_ids:
        paper_ids = [int(x) for x in args.paper_ids.split(',') if x.strip()]

    def progress(msg: str):
        print(f'  … {msg}')

    stats = biblio_reflect.reflect_all(
        source_id=args.source,
        folder_id=args.folder,
        paper_ids=paper_ids,
        dry_run=args.dry_run,
        progress=progress,
    )
    _print_stats(stats, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
