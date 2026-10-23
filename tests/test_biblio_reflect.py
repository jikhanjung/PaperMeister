"""Auto-commit gates in biblio_reflect.evaluate.

A placeholder Paper (title from the PDF filename, no year, no authors) has no
curated metadata to protect, so evaluate relaxes the soft gates for it — a
'medium' confidence goes through. On 2026-10-23 that let a literature-review
note opening "Hsiang et al. (2019)…" auto-commit to Zotero with "Hsiang et al."
as its author and 2019 as its year.
"""
import json
import os
import tempfile

import pytest

HASH = 'cd' * 32


@pytest.fixture
def db(monkeypatch):
    """A real SQLite database with the real schema, migrations included."""
    work = tempfile.mkdtemp(prefix='pm-reflect-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


def _placeholder_with_biblio(authors, confidence='medium'):
    from papermeister.models import Paper, PaperBiblio
    paper = Paper.create(title='foraminifera_automated_identification_2019_2026')
    biblio = PaperBiblio.create(
        paper=paper, file_hash=HASH, title='Foraminifera 자동 동정 연구',
        authors_json=json.dumps(authors), year=2019, doc_type='article',
        confidence=confidence, source='llm-qwen')
    return paper, biblio


def test_et_al_author_is_held_for_review(db):
    from papermeister.biblio_reflect import evaluate
    paper, biblio = _placeholder_with_biblio(['Hsiang et al.'])
    decision = evaluate(biblio, paper)
    assert (decision.action, decision.reason) == ('needs_review', 'et_al_author')


@pytest.mark.parametrize('name', ['Hsiang et al', 'HSIANG ET AL.', 'Hsiang, et. al.', 'Hsiang etal'])
def test_et_al_spellings(db, name):
    from papermeister.biblio_reflect import evaluate
    paper, biblio = _placeholder_with_biblio(['Allison Y. Hsiang', name])
    assert evaluate(biblio, paper).reason == 'et_al_author'


def test_real_authors_on_a_placeholder_still_auto_commit(db):
    """The gate is the 'et al.', not the relaxed placeholder rule."""
    from papermeister.biblio_reflect import evaluate
    paper, biblio = _placeholder_with_biblio(['Allison Y. Hsiang', 'Metallo, A.', 'Al-Rawi, K.'])
    assert evaluate(biblio, paper).action == 'auto_commit'
