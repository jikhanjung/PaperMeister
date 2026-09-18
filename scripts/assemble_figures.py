#!/usr/bin/env python3
"""P16: assemble figures from the OCR cache — survey the cache, or store them.

**Survey** (no targets; Phase 0). Runs the assembly judgement
(`papermeister.figures`) over every cached OCR result and reports how many
figures, plate pages and cut-up figures there are, and how many look like panel
candidates. The picture-block count is not that number — plate pages hold a
block per photograph and journal logos are pictures too. Also picks a pilot set
for the later phases: papers with plates, cut-up figures, compound captions,
non-Latin scripts and maps, so the pilot meets the cases that break things,
spread across publication years and lengths. Reads the cache, and the library
read-only for years.

**Store** (`--paper-ids` or `--pilot`; Phase 1). Assembles the chosen papers and
shows what storing would change — new figures, refreshed hints, figures folded
because a rule no longer produces them. Nothing is written without `--execute`,
and the dry run opens the database read-only, so it does not even add the new
tables to the library. Re-running is safe: see `papermeister.figure_store`.

    python scripts/assemble_figures.py                               # survey the whole cache
    python scripts/assemble_figures.py --sample 300                  # survey a random sample
    python scripts/assemble_figures.py --pilot-out pilot.json        # survey + write the pilot list
    python scripts/assemble_figures.py --pilot pilot.json            # dry run: what would be stored
    python scripts/assemble_figures.py --pilot pilot.json --execute  # store the pilot's figures
    python scripts/assemble_figures.py --paper-ids 12,345 --execute
"""
import argparse
import json
import os
import pathlib
import random
import re
import statistics
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister import figures, ocr_layout
from papermeister.paths import OCR_JSON_DIR


def _print_utf8():
    """Titles in this library are half non-English; the Windows console is cp949."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, ValueError):
            pass


_print_utf8()

_SCRIPTS = {
    'hangul': re.compile(r'[가-힣]'),
    'kana': re.compile(r'[぀-ヿ]'),
    'han': re.compile(r'[一-鿿]'),
    'cyrillic': re.compile(r'[Ѐ-ӿ]'),
}
_LATIN = re.compile(r'[A-Za-z]')
_MAP = re.compile(r'\b(?:maps?|locality|localities|location)\b|지도|위치도|位置図|地図|地图|карта', re.I)
_CACHE_HASH = re.compile(r'\.([0-9a-f]{8})\.json$')

#: What the pilot must meet, as shares of its size — the cases that break things.
PILOT_STRATA = (
    ('plates', 0.30, lambda p: p['plates'] > 0),
    ('cut_up', 0.20, lambda p: p['groups'] > 0),
    ('compound', 0.23, lambda p: p['compound'] > 0),
    ('non_latin', 0.17, lambda p: p['script'] != 'latin'),
    ('maps', 0.10, lambda p: p['maps']),
)
PILOT_SIZE = 100
#: Long enough for monographs, short of the Treatise volumes (2,500 figures in one file).
PILOT_MAX_PAGES = 300
#: Publication years and lengths the pilot spreads across. A 1852 plate volume and
#: a 2019 PLOS paper break different rules; so do a 4-page note and a 200-page monograph.
YEAR_BINS = ((None, 1899, '<1900'), (1900, 1949, '1900-49'), (1950, 1979, '1950-79'),
             (1980, 1999, '1980-99'), (2000, 2009, '2000-09'), (2010, None, '2010-'))
LENGTH_BINS = ((1, 10, '1-10p'), (11, 25, '11-25p'), (26, 60, '26-60p'),
               (61, 150, '61-150p'), (151, None, '151p+'))


def _bin(value, bins) -> str:
    if value is None:
        return 'unknown'
    for low, high, name in bins:
        if (low is None or value >= low) and (high is None or value <= high):
            return name
    return 'unknown'


def dominant_script(text: str) -> str:
    """The non-Latin script a paper is mostly in, or 'latin'."""
    sample = text[:20_000]
    latin = len(_LATIN.findall(sample))
    counts = {name: len(pattern.findall(sample)) for name, pattern in _SCRIPTS.items()}
    name, count = max(counts.items(), key=lambda kv: kv[1])
    return name if count and count > latin * 0.3 else 'latin'


def load_pages(path: str) -> list[str] | None:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    ordered = sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))
    return [(p.get('markdown') or '') for p in ordered]


# ── survey ──────────────────────────────────────────────────────────

def survey(names: list[str], cache: str):
    totals: Counter = Counter()
    verdicts: Counter = Counter()
    dropped: Counter = Counter()
    reasons: Counter = Counter()
    suspicions: Counter = Counter()
    papers = []
    many_marks = []
    started = time.time()

    for index, name in enumerate(names, 1):
        pages = load_pages(os.path.join(cache, name))
        totals['files'] += 1
        if pages is None:
            totals['unreadable'] += 1
            continue
        if not any(ocr_layout.is_structured(text) for text in pages):
            totals['not_structured'] += 1
            continue
        totals['structured_files'] += 1
        totals['pages'] += len(pages)

        record = {'file': name, 'pages': len(pages), 'figures': 0, 'plates': 0, 'groups': 0,
                  'compound': 0, 'captioned': 0, 'maps': False,
                  'script': dominant_script('\n'.join(pages))}
        for assembled in figures.assemble_document(pages):
            totals['picture_blocks'] += assembled.picture_blocks
            if assembled.verdict:
                verdicts[assembled.verdict] += 1
            dropped.update(assembled.dropped)
            if assembled.verdict == figures.MANY_MARKS:
                many_marks.append((name, assembled.page))
            suspicions.update(assembled.suspicions)
            for figure in assembled.figures:
                record['figures'] += 1
                reasons.update(figure.reasons)
                if figure.reasons:
                    record['suspect'] = record.get('suspect', 0) + 1
                    totals['figures_suspect'] += 1
                caption = figure.caption_hint
                if figure.plate_inferred:
                    totals['plates_inferred'] += 1
                if figure.page_kind == figures.PLATE_KIND:
                    record['plates'] += 1
                    totals['figures_plate' if figure.assembly == figures.PLATE_UNION else 'figures_plate_single'] += 1
                elif figure.page_kind == figures.CAPTIONED_PLATE:
                    totals['figures_captioned_plate'] += 1
                elif figure.assembly == figures.CAPTION_GROUP:
                    record['groups'] += 1
                    totals['figures_group'] += 1
                    totals['group_blocks'] += len(figure.blocks)
                    if figure.label_hints:
                        totals['figures_group_labelled'] += 1
                else:
                    totals['figures_single'] += 1
                    if figures.looks_compound(caption):
                        record['compound'] += 1
                        totals['figures_single_compound'] += 1
                if caption:
                    record['captioned'] += 1
                    totals['figures_captioned'] += 1
                    if _MAP.search(caption):
                        record['maps'] = True
                        totals['figures_map_caption'] += 1
        papers.append(record)

        if index % 500 == 0:
            elapsed = time.time() - started
            print(f'  {index:,}/{len(names):,} files  ({elapsed:.0f}s)')

    return totals, verdicts, dropped, papers, many_marks, reasons, suspicions


def _quotas(size: int) -> list[int]:
    """Each stratum's share of `size`, rounded so the quotas add up to `size`."""
    raw = [share * size for _, share, _ in PILOT_STRATA]
    quotas = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - quotas[i], reverse=True)[:size - sum(quotas)]:
        quotas[i] += 1
    return quotas


def choose_pilot(papers: list[dict], seed: int, size: int = PILOT_SIZE) -> list[dict]:
    """Papers for the pilot: each stratum's quota, spread across years and lengths.

    Within a stratum every pick takes the paper whose year bin and length bin the
    pilot holds least of so far, so the common case (a 2010s article of 10–25
    pages) does not crowd out old plate volumes and long monographs. Ties go to
    the shuffled order, so the same seed gives the same pilot.
    """
    rng = random.Random(seed)
    usable = [p for p in papers
              if p['figures'] and p['pages'] <= PILOT_MAX_PAGES and p.get('in_library', True)]
    chosen, seen = [], set()
    years: Counter = Counter()
    lengths: Counter = Counter()
    for (stratum, _share, wanted), quota in zip(PILOT_STRATA, _quotas(size), strict=True):
        pool = [p for p in usable if wanted(p) and p['file'] not in seen]
        rng.shuffle(pool)
        for _ in range(quota):
            pool = [p for p in pool if p['file'] not in seen]
            if not pool:
                break
            year_bin = lambda p: _bin(p.get('year'), YEAR_BINS)  # noqa: E731
            length_bin = lambda p: _bin(p['pages'], LENGTH_BINS)  # noqa: E731
            # A paper without a year spreads nothing across years: take one only
            # when the stratum has no dated paper left.
            paper = min(pool, key=lambda p: (p.get('year') is None,
                                             years[year_bin(p)] + lengths[length_bin(p)]))
            chosen.append({**paper, 'stratum': stratum,
                           'year_bin': year_bin(paper), 'length_bin': length_bin(paper)})
            seen.add(paper['file'])
            years[year_bin(paper)] += 1
            lengths[length_bin(paper)] += 1
    return chosen


def library_years(cache_dir_names: list[str]) -> dict[str, int | None] | None:
    """{hash prefix: publication year} for PDFs in the library, read-only; None without a library.

    The cache file name carries the PDF hash prefix, and the year lives on the
    paper. A cache whose PDF has left the library gets no entry, and the pilot
    leaves it out — storing figures needs the PDF's library row.
    """
    try:
        open_database(write=False)
        from papermeister.models import Paper, PaperFile
        rows = (PaperFile.select(PaperFile.hash, Paper.year).join(Paper)
                .where((PaperFile.hash != '') & PaperFile.trashed_at.is_null()
                       & ~PaperFile.path.endswith('.json')).tuples())
        years: dict[str, int | None] = {}
        for file_hash, year in rows:
            if years.get(file_hash[:8]) is None:
                years[file_hash[:8]] = year
        return years
    except Exception as exc:
        print(f'  (library not readable, pilot ignores years: {exc})')
        return None


def report(totals, verdicts, dropped, papers, many_marks, reasons=None, suspicions=None) -> dict:
    figure_counts = [p['figures'] for p in papers]
    with_figures = [c for c in figure_counts if c]
    candidates = (totals['figures_plate'] + totals['figures_plate_single'] + totals['figures_group']
                  + totals['figures_single_compound'])
    summary = {
        'files': totals['files'],
        'structured_files': totals['structured_files'],
        'not_structured': totals['not_structured'],
        'unreadable': totals['unreadable'],
        'pages': totals['pages'],
        'picture_blocks': totals['picture_blocks'],
        'dropped': dict(dropped),
        'page_verdicts': dict(verdicts),
        'figures_single': totals['figures_single'],
        'figures_plate': totals['figures_plate'],
        'figures_group': totals['figures_group'],
        'group_blocks': totals['group_blocks'],
        'figures_group_labelled': totals['figures_group_labelled'],
        'figures_plate_single': totals['figures_plate_single'],
        'plates_inferred': totals['plates_inferred'],
        'figures_captioned_plate': totals['figures_captioned_plate'],
        'figures_total': (totals['figures_single'] + totals['figures_plate'] + totals['figures_plate_single']
                          + totals['figures_group'] + totals['figures_captioned_plate']),
        'figures_captioned': totals['figures_captioned'],
        'figures_single_compound': totals['figures_single_compound'],
        'figures_map_caption': totals['figures_map_caption'],
        'panel_candidates_estimate': candidates,
        'papers_with_figures': len(with_figures),
        'papers_with_plates': sum(1 for p in papers if p['plates']),
        'figures_per_paper_median': statistics.median(with_figures) if with_figures else 0,
        'figures_per_paper_p90': (statistics.quantiles(with_figures, n=10)[-1]
                                  if len(with_figures) >= 10 else max(with_figures, default=0)),
        'figures_per_paper_max': max(with_figures, default=0),
        'many_marks_pages': len(many_marks),
        'figures_suspect': totals['figures_suspect'],
        'reasons': dict(reasons or {}),
        'page_suspicions': dict(suspicions or {}),
        'papers_with_suspects': sum(1 for p in papers if p.get('suspect')),
    }

    print()
    print(f"Files scanned            {summary['files']:>9,}")
    print(f"  structured             {summary['structured_files']:>9,}   "
          f"(not structured {summary['not_structured']:,}, unreadable {summary['unreadable']:,})")
    print(f"  pages                  {summary['pages']:>9,}")
    print()
    print(f"Picture blocks           {summary['picture_blocks']:>9,}")
    for why, count in sorted(dropped.items()):
        print(f"  dropped as {why:<11} {count:>9,}")
    print()
    print('Pages with pictures, by verdict')
    for verdict, count in verdicts.most_common():
        print(f"  {verdict:<22} {count:>9,}")
    print()
    print(f"Figures                  {summary['figures_total']:>9,}")
    print(f"  ordinary               {summary['figures_single']:>9,}")
    print(f"  plate pages merged     {summary['figures_plate']:>9,}   "
          f"in {summary['papers_with_plates']:,} papers")
    print(f"  one-photo plate pages  {summary['figures_plate_single']:>9,}")
    print(f"  plate number inferred  {summary['plates_inferred']:>9,}   (not printed on the page)")
    print(f"  captioned plate photos {summary['figures_captioned_plate']:>9,}   (named Plate N, Fig. M)")
    print(f"  cut-up pieces merged   {summary['figures_group']:>9,}   "
          f"from {summary['group_blocks']:,} blocks; {summary['figures_group_labelled']:,} with panel labels")
    print(f"  with a caption below   {summary['figures_captioned']:>9,}")
    print(f"  caption looks compound {summary['figures_single_compound']:>9,}")
    print(f"  caption mentions a map {summary['figures_map_caption']:>9,}")
    print()
    print(f"Panel split candidates   {candidates:>9,}   "
          f"(plates + cut-up figures + ordinary figures whose caption looks compound; estimate)")
    print(f"Figures per paper        median {summary['figures_per_paper_median']}, "
          f"p90 {summary['figures_per_paper_p90']:.0f}, max {summary['figures_per_paper_max']}")
    print(f"Pages with two plate numbers (left unmerged, worth a look): {len(many_marks):,}")
    if reasons is not None:
        total = summary['figures_total'] or 1
        print()
        print(f"Suspect figures (for ①′)  {summary['figures_suspect']:>8,}   "
              f"{100 * summary['figures_suspect'] / total:.1f}% of figures, "
              f"in {summary['papers_with_suspects']:,} papers")
        for why, count in reasons.most_common():
            print(f"  {why:<22} {count:>9,}")
        print('Suspect pages (no figure to carry it)')
        for why, count in (suspicions or Counter()).most_common():
            print(f"  {why:<22} {count:>9,}")
    return summary


def survey_mode(args) -> int:
    names = sorted(f for f in os.listdir(args.cache_dir) if f.endswith('.json'))
    if args.sample:
        random.Random(args.seed).shuffle(names)
        names = names[:args.sample]
    print(f'Surveying {len(names):,} cached OCR results in {args.cache_dir}')

    totals, verdicts, dropped, papers, many_marks, reasons, suspicions = survey(names, args.cache_dir)
    summary = report(totals, verdicts, dropped, papers, many_marks, reasons, suspicions)

    years = library_years(names)
    if years is not None:
        for paper in papers:
            m = _CACHE_HASH.search(paper['file'])
            key = m.group(1) if m else ''
            paper['in_library'] = key in years
            paper['year'] = years.get(key)
    pilot = choose_pilot(papers, args.seed, args.pilot_size)
    print()
    print(f'Pilot set ({len(pilot)} papers)')
    for title, key in (('stratum', 'stratum'), ('year', 'year_bin'), ('length', 'length_bin')):
        counts = Counter(p[key] for p in pilot)
        print(f'  {title:<8} ' + '  '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    if args.pilot_out:
        with open(args.pilot_out, 'w', encoding='utf-8') as f:
            json.dump(pilot, f, ensure_ascii=False, indent=2)
        print(f'  written to {args.pilot_out}')
    if args.report_out:
        with open(args.report_out, 'w', encoding='utf-8') as f:
            json.dump({**summary, 'many_marks': many_marks[:200]}, f, ensure_ascii=False, indent=2)
        print(f'Summary written to {args.report_out}')
    return 0


# ── store ───────────────────────────────────────────────────────────

def open_database(write: bool):
    """The live database: migrated for --execute, read-only otherwise.

    `init_db` creates any missing tables — the figure tables included — so a
    dry run that called it would already have changed the user's library.
    """
    if write:
        from papermeister.database import init_db
        return init_db()
    import peewee

    from papermeister.models import db
    from papermeister.paths import DB_PATH
    uri = pathlib.Path(DB_PATH).resolve().as_uri() + '?mode=ro'
    database = peewee.SqliteDatabase(uri, uri=True)
    db.initialize(database)
    _require_migrated(database)
    return database


def _require_migrated(database) -> None:
    """A read-only run cannot add columns; say so instead of failing on every file."""
    from papermeister.models import Figure, FigureEntry, FigurePanel
    missing = []
    for model in (Figure, FigureEntry, FigurePanel):
        table = model._meta.table_name
        have = {row[1] for row in database.execute_sql(f"PRAGMA table_info('{table}')").fetchall()}
        if have:
            missing += [f'{table}.{f.column_name}' for f in model._meta.sorted_fields if f.column_name not in have]
    if missing:
        sys.exit('The library\'s figure tables predate this version (missing '
                 + ', '.join(missing[:3]) + (', …' if len(missing) > 3 else '') + ').\n'
                 'Open the app once, or run `python cli.py list papers -n 1`, to migrate; then retry.')


def target_files(args) -> list:
    """The PDF files to assemble: of the given papers, or of the pilot list."""
    from papermeister.models import PaperFile
    pdfs = PaperFile.select().where(
        (PaperFile.hash != '') & PaperFile.trashed_at.is_null() & ~PaperFile.path.endswith('.json'))
    if args.paper_ids:
        ids = [int(x) for x in args.paper_ids.split(',') if x.strip()]
        return list(pdfs.where(PaperFile.paper.in_(ids)).order_by(PaperFile.paper, PaperFile.id))
    with open(args.pilot, encoding='utf-8') as f:
        pilot = json.load(f)
    files = []
    for entry in pilot:
        m = _CACHE_HASH.search(entry['file'])
        if m is None:
            print(f"  skip  {entry['file']}  (not a cache file name)")
            continue
        found = list(pdfs.where(PaperFile.hash.startswith(m.group(1))).order_by(PaperFile.id))
        if not found:
            print(f"  skip  {entry['file']}  (no PDF in the library has this hash)")
        files.extend(found)
    return files


def store_mode(args) -> int:
    open_database(write=args.execute)
    from papermeister import figure_store

    cache_by_hash = {}
    for name in os.listdir(args.cache_dir):
        m = _CACHE_HASH.search(name)
        if m:
            cache_by_hash.setdefault(m.group(1), name)

    files = target_files(args)
    print(f"{'Storing' if args.execute else 'Dry run for'} {len(files)} PDF file(s)\n")
    totals: Counter = Counter()
    failed: list[tuple[int, str, str]] = []
    for pf in files:
        label = os.path.basename(pf.path)[:70]
        name = cache_by_hash.get(pf.hash[:8])
        pages = load_pages(os.path.join(args.cache_dir, name)) if name else None
        if not pages or not any(ocr_layout.is_structured(text) for text in pages):
            print(f'  skip   paper {pf.paper_id:>6}  {label}  (no structured OCR cache)')
            totals['skipped'] += 1
            continue
        try:
            if args.execute and not figure_store.Figure.select().where(figure_store.Figure.paper_file == pf.id).exists():
                # Figures another machine found ride in the cache JSON: land
                # them before the rule stores its own, so they match by identity.
                from papermeister.figure_share import import_from_cache
                report = import_from_cache(pf)
                if report.created:
                    print(f'  paper {pf.paper_id:>6}  figures from the cache JSON: {report}')
            assemblies = figures.assemble_document(pages)
            assembled = figure_store.with_placeholders(assemblies)
            plan = figure_store.plan_store(pf, assembled)
            if args.execute:
                figure_store.apply_plan(plan)
        except Exception as exc:  # one broken cache file must not stop the other hundred (fsis DG §6-1)
            print(f'  FAIL   paper {pf.paper_id:>6}  {label}  {type(exc).__name__}: {exc}')
            failed.append((pf.paper_id, label, f'{type(exc).__name__}: {exc}'))
            continue
        kinds = Counter(f.assembly for f in assembled)
        doubts = sum(1 for f in assembled if f.reasons)
        print(f'  paper {pf.paper_id:>6}  {len(assembled):>4} figures '
              f'(plates {kinds[figures.PLATE_UNION]}, cut-up {kinds[figures.CAPTION_GROUP]}, '
              f'page doubts {kinds[figure_store.PAGE]}, doubted {doubts})  '
              f'new {len(plan.create)}, refreshed {len(plan.refresh)}, moved {len(plan.move)}, '
              f'restored {len(plan.restore)}, folded {len(plan.dismiss)}'
              + (f', absorbed {plan.absorbed}' if plan.absorbed else '')
              + (f', contested {plan.contested}' if plan.contested else '')
              + f'  {label}')
        totals['files'] += 1
        totals['figures'] += len(assembled)
        totals['doubted'] += doubts
        totals['new'] += len(plan.create)
        totals['refreshed'] += len(plan.refresh)
        totals['moved'] += len(plan.move)
        totals['restored'] += len(plan.restore)
        totals['folded'] += len(plan.dismiss)
        totals['left_for_people'] += plan.untouched_by_rule
        totals['absorbed'] += plan.absorbed
        totals['contested'] += plan.contested

    print(f"\n{totals['files']} file(s), {totals['figures']} figures ({totals['doubted']} doubted): "
          f"new {totals['new']}, refreshed {totals['refreshed']}, moved {totals['moved']}, "
          f"restored {totals['restored']}, folded {totals['folded']}, "
          f"left alone (person's decision) {totals['left_for_people']}, "
          f"absorbed by a person's row {totals['absorbed']}, contested {totals['contested']}, "
          f"skipped {totals['skipped']}, failed {len(failed)}")
    for paper_id, label, why in failed:
        print(f'  failed  paper {paper_id}  {label}  {why}')
    if not args.execute:
        print('Dry run — nothing written. Add --execute to store.')
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cache-dir', default=OCR_JSON_DIR)
    parser.add_argument('--sample', type=int, help='survey: a random sample of this many files')
    parser.add_argument('--seed', type=int, default=16)
    parser.add_argument('--pilot-out', help='survey: write the pilot paper list (JSON) here')
    parser.add_argument('--pilot-size', type=int, default=PILOT_SIZE, help='survey: papers in the pilot')
    parser.add_argument('--report-out', help='survey: write the summary (JSON) here')
    parser.add_argument('--paper-ids', help='store: comma-separated paper ids')
    parser.add_argument('--pilot', help='store: the papers in a pilot list written by --pilot-out')
    parser.add_argument('--execute', action='store_true', help='store: write to the database')
    args = parser.parse_args()

    if args.paper_ids or args.pilot:
        return store_mode(args)
    if args.execute:
        parser.error('--execute stores figures for chosen papers: give --paper-ids or --pilot')
    return survey_mode(args)


if __name__ == '__main__':
    sys.exit(main())
