"""Papers that cannot be parsed must stop leading every batch.

A partial parse deliberately leaves `references_checked` False so a later run
can replace it, but target selection orders by paper id descending — so the
same unparseable documents come back at the head of the next batch, run after
run (devlog 076). Two weeks of that left a queue whose first papers were 40%
PARTIAL against a 1.0% background rate.

The counter retires them from a normal run while keeping them reachable through
an explicit retry, and resets on success so a server outage does not retire
papers that were only failing because the server was down.
"""
import os
import tempfile

import pytest


@pytest.fixture
def db(monkeypatch):
    """A real SQLite database with the real schema, migrations included."""
    work = tempfile.mkdtemp(prefix='pm-giveup-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


def _paper(title='p'):
    from papermeister.models import Paper
    return Paper.create(title=title)


@pytest.mark.unit
def test_the_column_exists_after_migration(db):
    """_migrate() has to add it to databases that predate the column, which is
    every existing install — the live one is 2.7GB and not re-created."""
    cols = {r[1] for r in db.execute_sql("PRAGMA table_info('paper')").fetchall()}
    assert 'references_attempts' in cols


@pytest.mark.unit
def test_a_partial_parse_counts_against_the_paper(db):
    from papermeister.models import Paper
    from papermeister.references import record_refs_attempt

    p = _paper()
    for expected in (1, 2, 3):
        record_refs_attempt(p.id, complete=False)
        assert Paper.get_by_id(p.id).references_attempts == expected


@pytest.mark.unit
def test_success_resets_the_counter(db):
    """Otherwise an outage that fails a paper twice leaves it two-thirds retired
    forever, and a long-lived library slowly retires everything."""
    from papermeister.models import Paper
    from papermeister.references import record_refs_attempt

    p = _paper()
    record_refs_attempt(p.id, complete=False)
    record_refs_attempt(p.id, complete=False)
    record_refs_attempt(p.id, complete=True)

    assert Paper.get_by_id(p.id).references_attempts == 0


@pytest.mark.unit
def test_only_exhausted_papers_are_retired(db):
    from papermeister.references import (
        MAX_REFS_ATTEMPTS,
        exhausted_paper_ids,
        record_refs_attempt,
    )

    fine, doomed = _paper('fine'), _paper('doomed')
    record_refs_attempt(fine.id, complete=False)          # one strike
    for _ in range(MAX_REFS_ATTEMPTS):
        record_refs_attempt(doomed.id, complete=False)

    assert exhausted_paper_ids() == {doomed.id}


@pytest.mark.unit
def test_a_paper_is_retired_only_on_the_threshold_attempt(db):
    from papermeister.references import (
        MAX_REFS_ATTEMPTS,
        exhausted_paper_ids,
        record_refs_attempt,
    )

    p = _paper()
    for _ in range(MAX_REFS_ATTEMPTS - 1):
        record_refs_attempt(p.id, complete=False)
    assert exhausted_paper_ids() == set()      # still in the normal run

    record_refs_attempt(p.id, complete=False)
    assert exhausted_paper_ids() == {p.id}


@pytest.mark.unit
def test_fresh_papers_are_never_retired(db):
    """The migration backfills 0 rather than guessing, so nothing is retired
    until it has actually been observed failing."""
    from papermeister.references import exhausted_paper_ids

    for i in range(5):
        _paper(f'p{i}')

    assert exhausted_paper_ids() == set()
