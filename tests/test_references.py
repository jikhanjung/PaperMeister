"""Reference-to-held-paper matching (P14 scorer regression).

Pins the resolve_one / _score_title behavior that the P14 scorer refinement
established: a short reference title embedded in a long paper title must NOT be a
false positive, and a near-identical title must be recovered even when the year
disagrees.
"""
from collections import defaultdict

import pytest

from papermeister.references import _score_title, resolve_one, title_tokens


def _info(title, year=None, surname=""):
    return {
        "tokens": set(title_tokens(title)),
        "year": year,
        "surname": surname,
        "title": title,
    }


def _index(papers, doi_map=None):
    inverted = defaultdict(set)
    for pid, info in papers.items():
        for tok in info["tokens"]:
            inverted[tok].add(pid)
    return {"doi_map": doi_map or {}, "papers": papers, "inverted": inverted}


@pytest.mark.unit
def test_short_title_in_long_title_is_not_false_positive():
    # "On Growth and Form" (2 significant tokens) fully embedded in an unrelated
    # long title used to score a perfect containment 1.0 and mis-match.
    ref_toks = title_tokens("On Growth and Form")
    paper = _info(
        "A universal power law for modelling the growth and form of teeth, "
        "claws and horns", year=2020)
    score = _score_title(ref_toks, paper, 1917, "")
    assert score < 0.7


@pytest.mark.unit
def test_near_exact_title_survives_year_mismatch():
    title = "Nonmetric Multidimensional Scaling A Numerical Method"
    ref_toks = title_tokens("Nonmetric multidimensional scaling: a numerical method")
    paper = _info(title, year=1964, surname="kruskal")
    # A near-identical title is a confident match; a disagreeing year must not veto it.
    assert _score_title(ref_toks, paper, 1970, "") >= 0.7


@pytest.mark.unit
def test_resolve_one_title_match():
    title = "Nonmetric Multidimensional Scaling A Numerical Method"
    index = _index({2: _info(title, 1964, "kruskal")})
    pid, method, score = resolve_one(
        "", "Nonmetric multidimensional scaling: a numerical method", 1964, "[]", index)
    assert pid == 2
    assert method == "title"


@pytest.mark.unit
def test_resolve_one_short_generic_title_not_matched():
    index = _index({7: _info(
        "A universal power law for modelling the growth and form of teeth", 2020,
        "evans")})
    pid, method, _score = resolve_one("", "On Growth and Form", 1917, "[]", index)
    assert pid is None
    assert method == "none"


@pytest.mark.unit
def test_resolve_one_doi_exact_wins():
    index = _index({}, doi_map={"10.1007/bf02289565": 2})
    pid, method, score = resolve_one(
        "https://doi.org/10.1007/BF02289565", "whatever", None, "[]", index)
    assert (pid, method, score) == (2, "doi", 1.0)
