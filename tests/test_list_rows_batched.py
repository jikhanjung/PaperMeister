"""A list's rows are built from three queries over the whole list, and say
exactly what the one-row path says (status pill, authors, stub)."""
import os
import tempfile

import pytest


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-rows-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def library(db):
    from papermeister.models import (
        Author,
        Folder,
        Paper,
        PaperBiblio,
        PaperFile,
        PaperFolder,
        Source,
    )
    src = Source.create(name='Papers', source_type='directory', path='/x')
    folder = Folder.create(source=src, name='root', path='/x')
    made = []
    for title, year, files, biblio, authors in [
        ('Done paper', 2004, [('a.pdf', 'processed'), ('a.pdf.deadbeef.json', 'processed')], ['applied'], ['Lee, C.', 'Kim, D.']),
        ('Review paper', 1936, [('b.pdf', 'processed')], ['needs_review'], ['정직한', '최덕근', '홍길동']),
        ('', None, [('c.pdf', 'pending')], [], []),                       # a stub
        ('Plain OCR', 1997, [('d.pdf', 'processed')], [], ['Hammann, W.']),
        ('Failed', 1888, [('e.pdf', 'failed')], [], ['Kayser, E.']),
    ]:
        p = Paper.create(title=title, year=year, folder=folder)
        PaperFolder.create(paper=p, folder=folder)
        for path, status in files:
            PaperFile.create(paper=p, path=path, hash='', status=status)
        for status in biblio:
            PaperBiblio.create(paper=p, source='test', status=status, file_hash='')
        for order, name in enumerate(authors):
            Author.create(paper=p, name=name, order=order)
        made.append(p.id)
    return folder.id, made


@pytest.mark.unit
def test_batched_rows_match_the_single_row_path(library):
    from desktop.services import paper_service as ps
    folder_id, ids = library
    rows = {r.paper_id: r for r in ps.list_by_folder(folder_id)}
    assert set(rows) == set(ids)
    for pid in ids:
        assert rows[pid] == ps.row_for_paper(pid)
    by_title = {r.title: r for r in rows.values()}
    assert by_title['Done paper'].status == 'done' and by_title['Done paper'].authors == 'Lee and Kim'
    assert by_title['Review paper'].status == 'review' and by_title['Review paper'].authors == '정직한 외'
    assert by_title['(untitled)'].is_stub and by_title['(untitled)'].status == 'pending'
    assert by_title['Plain OCR'].status == 'processed' and by_title['Failed'].status == 'failed'
    assert by_title['Done paper'].file_id is not None       # the PDF, not the JSON sibling
    lib = {r.paper_id: r for r in ps.list_by_library('all')}
    assert {pid: lib[pid] for pid in ids} == rows
    # the stages read the same way batched and single
    st = by_title['Done paper'].stages
    assert (st.ocr, st.biblio, st.refs, st.figs) == ('done', 'done', 'none', 'none')
    assert by_title['Review paper'].stages.biblio == 'review' and by_title['Failed'].stages.ocr == 'failed'
    assert 'Bibliography: applied' in st.tooltip()


@pytest.mark.unit
def test_the_status_counts_agree_with_the_lists(library):
    from desktop.services import library as lib_svc
    from desktop.services import paper_service as ps
    folders = {f.key: f.count for f in lib_svc.load_library_folders()}
    assert folders['all'] == 5 and folders['processed'] == 3 and folders['pending'] == 1 and folders['failed'] == 1
    assert folders['needs_review'] == 1 == len(ps.list_by_library('needs_review')) == len(lib_svc.needs_review_paper_ids())
    assert lib_svc.corpus_counts() == (5, 1, 1)
