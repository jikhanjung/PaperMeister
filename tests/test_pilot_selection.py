"""The P16 pilot: the cases that break things, across years and lengths.

A random pick from this library is mostly 2010s articles of 10–25 pages. The
pilot exists to meet what those do not have — 19th-century plate volumes,
monographs, cut-up figures — so the selection has to push against the mix.
"""
import importlib.util
import os
import random

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='module')
def script():
    spec = importlib.util.spec_from_file_location(
        'assemble_figures', os.path.join(ROOT, 'scripts', 'assemble_figures.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def library(n=3000, seed=1):
    """Mostly recent short articles, a thin tail of old and long ones."""
    rng = random.Random(seed)
    papers = []
    for i in range(n):
        old = rng.random() < 0.08
        long = rng.random() < 0.10
        papers.append({
            'file': f'paper{i}.pdf.{i:08x}.json',
            'pages': rng.randint(80, 400) if long else rng.randint(4, 25),
            'year': rng.randint(1840, 1949) if old else rng.randint(1990, 2024),
            'figures': rng.randint(1, 30),
            'plates': int(rng.random() < 0.2), 'groups': int(rng.random() < 0.15),
            'compound': int(rng.random() < 0.4), 'maps': rng.random() < 0.1,
            'script': 'hangul' if rng.random() < 0.1 else 'latin',
            'in_library': rng.random() < 0.97,
        })
    return papers


@pytest.mark.unit
def test_the_pilot_has_its_size_and_each_stratum_its_share(script):
    pilot = script.choose_pilot(library(), seed=16, size=100)

    assert len(pilot) == 100
    assert len({p['file'] for p in pilot}) == 100
    counts = {s: sum(p['stratum'] == s for p in pilot) for s, _, _ in script.PILOT_STRATA}
    assert counts == {'plates': 30, 'cut_up': 20, 'compound': 23, 'non_latin': 17, 'maps': 10}


@pytest.mark.unit
def test_old_and_long_papers_are_not_crowded_out(script):
    papers = [p for p in library() if p['pages'] <= script.PILOT_MAX_PAGES and p['in_library']]
    pilot = script.choose_pilot(library(), seed=16, size=100)

    old_share_library = sum(p['year'] < 1950 for p in papers) / len(papers)
    old_share_pilot = sum(p['year'] < 1950 for p in pilot) / len(pilot)
    long_share_library = sum(p['pages'] > 60 for p in papers) / len(papers)
    long_share_pilot = sum(p['pages'] > 60 for p in pilot) / len(pilot)
    assert old_share_pilot > 2 * old_share_library
    assert long_share_pilot > 2 * long_share_library
    assert len({p['year_bin'] for p in pilot}) >= 5
    assert len({p['length_bin'] for p in pilot}) >= 4


@pytest.mark.unit
def test_papers_without_a_year_are_taken_only_when_nothing_dated_is_left(script):
    papers = library()
    for p in papers[::7]:
        p['year'] = None
    pilot = script.choose_pilot(papers, seed=16, size=100)
    assert all(p['year'] is not None for p in pilot)


@pytest.mark.unit
def test_papers_outside_the_library_or_too_long_are_left_out(script):
    pilot = script.choose_pilot(library(), seed=16, size=100)
    assert all(p['in_library'] and p['pages'] <= script.PILOT_MAX_PAGES for p in pilot)


@pytest.mark.unit
def test_the_same_seed_gives_the_same_pilot(script):
    first = [p['file'] for p in script.choose_pilot(library(), seed=16, size=100)]
    again = [p['file'] for p in script.choose_pilot(library(), seed=16, size=100)]
    assert first == again
