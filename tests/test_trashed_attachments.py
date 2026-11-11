"""An attachment trashed on its own in Zotero leaves the app (devlog 118 §8.4).

A Zotero item can lose one attachment to the trash while the item itself stays.
Before, the app still showed that file's figures, could pick it as the paper's
PDF, and counted its figures in the Stages column. A paper trashed as a whole
keeps all of its files, so the Trash view still shows it as it was.
"""
import datetime
import os
import tempfile

import pytest

from papermeister.figures import SINGLE, AssembledFigure

NOW = datetime.datetime(2026, 11, 12, 9, 0, tzinfo=datetime.UTC)


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-trashed-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def paper(db):
    """A paper with two PDFs: the article (kept) and a second copy (trashed
    on its own later), each with one figure."""
    from papermeister import figure_store
    from papermeister.models import Paper, PaperFile
    paper = Paper.create(title='Bruton et al. 2004')
    article = PaperFile.create(paper=paper, path='a-article.pdf', hash='ab' * 32, status='processed')
    copy = PaperFile.create(paper=paper, path='b-copy.pdf', hash='cd' * 32, status='processed')
    for pf, name in ((article, 'Fig. 1'), (copy, 'Fig. 9')):
        fig = AssembledFigure(page=3, bbox=(100, 100, 900, 800), blocks=((100, 100, 900, 800),),
                              assembly=SINGLE, name_hint=name, caption_hint=f'{name}. A trilobite.')
        figure_store.apply_plan(figure_store.plan_store(pf, [fig]))
    return paper


def _trash(model, row_id):
    model.update(trashed_at=NOW).where(model.id == row_id).execute()


def _files(paper):
    from papermeister.models import PaperFile
    return list(PaperFile.select().where(PaperFile.paper == paper).order_by(PaperFile.id))


def _reload(paper):
    from papermeister.models import Paper
    return Paper.get_by_id(paper.id)


def _figure_names(paper):
    from papermeister.figure_store import figures_for_paper
    return [f.name for f in figures_for_paper(paper.id)]


def _figure_count(paper):
    from desktop.services.paper_service import _figure_counts_query
    return {r['paper']: r['n'] for r in _figure_counts_query([paper.id]).dicts()}.get(paper.id, 0)


@pytest.mark.unit
def test_nothing_trashed_shows_both_files(paper):
    from desktop.services.paper_service import _primary_file, _RowContext
    assert sorted(_figure_names(paper)) == ['Fig. 1', 'Fig. 9']
    assert _figure_count(paper) == 2
    assert _primary_file(paper).path == 'a-article.pdf'
    assert _RowContext([paper]).primary_file(paper).path == 'a-article.pdf'


@pytest.mark.unit
def test_a_file_trashed_on_its_own_leaves_figures_and_counts(paper):
    copy = _files(paper)[1]
    _trash(type(copy), copy.id)

    assert _figure_names(paper) == ['Fig. 1']
    assert _figure_count(paper) == 1


@pytest.mark.unit
def test_a_trashed_file_is_never_the_papers_pdf(paper):
    """The trashed file would win on order: it is the first PDF."""
    from desktop.services.paper_service import _primary_file, _RowContext
    article = _files(paper)[0]
    _trash(type(article), article.id)
    paper = _reload(paper)

    assert _primary_file(paper).path == 'b-copy.pdf'
    assert _RowContext([paper]).primary_file(paper).path == 'b-copy.pdf'


@pytest.mark.unit
def test_a_paper_whose_only_file_is_trashed_has_no_pdf_and_no_figures(paper):
    from desktop.services.paper_service import _primary_file, _RowContext
    for f in _files(paper):
        _trash(type(f), f.id)
    paper = _reload(paper)

    assert _primary_file(paper) is None
    assert _RowContext([paper]).primary_file(paper) is None
    assert _figure_names(paper) == []
    assert _figure_count(paper) == 0


@pytest.mark.unit
def test_a_paper_in_the_trash_keeps_its_files(paper):
    """Trashing the whole item flags its files too; the Trash view still
    shows the paper's PDF and figures."""
    from desktop.services.paper_service import _primary_file, _RowContext
    from papermeister.models import Paper
    for f in _files(paper):
        _trash(type(f), f.id)
    _trash(Paper, paper.id)
    paper = _reload(paper)

    assert sorted(_figure_names(paper)) == ['Fig. 1', 'Fig. 9']
    assert _figure_count(paper) == 2
    assert _primary_file(paper).path == 'a-article.pdf'
    assert _RowContext([paper]).primary_file(paper).path == 'a-article.pdf'
