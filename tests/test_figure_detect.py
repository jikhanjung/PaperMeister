"""The re-judgement stage's client side: which pages go, and what a reply's
`from`/`dismiss` do to the rows — without touching what a person claimed.
Plus the HTTP client against a fake session."""
import json
import os
import tempfile

import pytest

from papermeister.figures import SINGLE, AssembledFigure

HASH = 'cd' * 32
DIGEST = 'e' * 64
PROMPT = 'detect-v1-test'
PAGES = ['<div data-label="Text" data-bbox="0 0 10 10">x</div>'] * 30


@pytest.fixture
def db(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-detect-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    yield database
    database.close()


@pytest.fixture
def doubted(db):
    """p.28: three uncaptioned photographs (unmarked plate page); p.5: a
    settled body figure; p.9: a page-level doubt with no figure."""
    from papermeister import figure_store
    from papermeister.models import Figure, Paper, PaperFile
    paper = Paper.create(title='Zhou & Zhang 1978')
    pf = PaperFile.create(paper=paper, path='zz.pdf', hash=HASH, status='processed')
    photos = [AssembledFigure(page=28, bbox=b, blocks=(b,), assembly=SINGLE, reasons=('unmarked_plate_page',))
              for b in ((48, 70, 282, 188), (294, 70, 527, 188), (48, 200, 282, 318))]
    body = AssembledFigure(page=5, bbox=(100, 100, 900, 600), blocks=((100, 100, 900, 600),), assembly=SINGLE,
                           caption_hint='Fig. 1. x')
    placeholder = figure_store.placeholder(9, ['plate_without_pictures'])
    figure_store.apply_plan(figure_store.plan_store(pf, [*photos, body, placeholder]))
    return pf, list(Figure.select().order_by(Figure.id))


@pytest.mark.unit
def test_one_item_per_doubted_page_with_hint_boxes_in_order(doubted):
    from papermeister import figure_detect as fd
    pf, rows = doubted
    t = fd.detect_items(pf, PAGES, DIGEST, PROMPT)
    assert [it['page'] for it in t.items] == [9, 28]
    p28 = t.items[1]
    assert p28['reasons'] == ['unmarked_plate_page'] and len(p28['hint_boxes']) == 3
    assert p28['figure_keys'] == [str(r.id) for r in rows if r.page == 28]
    assert p28['hint_boxes'][0] == [48, 70, 282, 188] and p28['hints']['pages_nearby'] == [27, 29]
    p9 = t.items[0]
    assert p9['hint_boxes'] == [] and p9['figures'][0]['placeholder'] is True
    assert [why for _, why in t.excluded] == ['no_trigger']       # the settled body figure
    body = fd.detect_payload(pf, DIGEST, t, 'c', {'version': PROMPT})
    assert body['ocr_digest'] == DIGEST and len(body['items']) == 2


@pytest.mark.unit
def test_a_merge_reply_folds_the_pieces_into_one_locked_figure(doubted):
    from papermeister import figure_detect as fd
    from papermeister.figure_store import plan_store
    from papermeister.models import Figure
    pf, rows = doubted
    t = fd.detect_items(pf, PAGES, DIGEST, PROMPT)
    item = t.items[1]
    ids = item['figure_keys']
    reply = {'figures': [{'bbox_page_1000': [40, 60, 540, 330], 'from': ids, 'name': 'Plate IV', 'name_inferred': True,
                          'kind': 'plate', 'caption': '', 'caption_pages': [27], 'caption_kind': 'explanation_page',
                          'confidence': 'high'}],
             'dismiss': [], 'pages_consulted': [27, 28], 'notes': []}
    applied = fd.apply_detect(pf, item, t.rows_by_item[item['key']], reply, DIGEST, PROMPT, 'm')
    assert applied.new == 1 and applied.merged == 3 and applied.conflicts == 0
    made = Figure.get((Figure.assembly == 'detect') & (Figure.page == 28))
    assert json.loads(made.bbox_page_1000) == [40, 60, 540, 330] and made.bbox_locked and made.bbox_source == 'detect'
    assert made.name == 'Plate IV' and made.plate == 4 and made.plate_inferred and made.page_kind == 'plate'
    assert len(json.loads(made.blocks_json)) == 3 and made.detect_key == item['key']
    assert all(Figure.get_by_id(int(i)).dismissed_by == 'detect' for i in ids)
    # re-assembly neither raises the pieces again nor folds the new row
    pieces = [AssembledFigure(page=28, bbox=tuple(b), blocks=(tuple(b),), assembly=SINGLE)
              for b in item['hint_boxes']]
    plan = plan_store(pf, pieces)
    # the pieces find their folded rows (folded by detect, not by re-assembly: left alone),
    # and the locked new row is neither folded nor duplicated
    assert plan.create == [] and plan.restore == [] and made.id not in [r.id for r in plan.dismiss]
    assert plan.untouched_by_rule >= 4
    # and the lane sees the page as done
    assert [it['page'] for it in fd.detect_items(pf, PAGES, DIGEST, PROMPT).items] == [9]


@pytest.mark.unit
def test_kept_adjusted_split_and_dismiss(doubted):
    from papermeister import figure_detect as fd
    from papermeister.models import Figure
    pf, rows = doubted
    t = fd.detect_items(pf, PAGES, DIGEST, PROMPT)
    item = t.items[1]
    a, b, c = item['figure_keys']
    reply = {'figures': [
        {'bbox_page_1000': [48, 70, 282, 188], 'from': [a], 'name': 'Fig. 2', 'name_inferred': False, 'kind': 'body',
         'caption': 'Fig. 2. Left.', 'caption_pages': [28], 'caption_kind': 'same_page', 'confidence': 'high'},
        {'bbox_page_1000': [290, 60, 530, 190], 'from': [b], 'name': '', 'name_inferred': False, 'kind': 'body',
         'caption': '', 'caption_pages': [], 'caption_kind': '', 'confidence': 'medium'},
        {'bbox_page_1000': [48, 200, 160, 318], 'from': [c], 'name': '', 'name_inferred': False, 'kind': 'body',
         'caption': '', 'caption_pages': [], 'caption_kind': '', 'confidence': 'low'},
        {'bbox_page_1000': [170, 200, 282, 318], 'from': [c], 'name': '', 'name_inferred': False, 'kind': 'body',
         'caption': '', 'caption_pages': [], 'caption_kind': '', 'confidence': 'low'},
    ], 'dismiss': [], 'pages_consulted': [28], 'notes': []}
    applied = fd.apply_detect(pf, item, t.rows_by_item[item['key']], reply, DIGEST, PROMPT, 'm')
    assert (applied.kept, applied.adjusted, applied.split, applied.new) == (1, 1, 1, 2)
    kept = Figure.get_by_id(int(a))
    assert kept.name == 'Fig. 2' and not kept.bbox_locked and json.loads(kept.detect_caption_json)['caption'] == 'Fig. 2. Left.'
    assert json.loads(kept.uncertain_reasons_json) == []
    adjusted = Figure.get_by_id(int(b))
    assert json.loads(adjusted.bbox_page_1000) == [290, 60, 530, 190] and adjusted.bbox_locked
    assert Figure.get_by_id(int(c)).dismissed_by == 'detect'
    assert Figure.select().where((Figure.page == 28) & (Figure.assembly == 'detect')).count() == 2

    # a table the parser boxed: dismissed by kind
    t2 = fd.detect_items(pf, PAGES, DIGEST, 'detect-v2')
    item9 = [it for it in t2.items if it['page'] == 9][0]
    reply9 = {'figures': [{'bbox_page_1000': [0, 0, 1000, 1000], 'from': [], 'name': '', 'name_inferred': False,
                           'kind': 'table', 'caption': '', 'caption_pages': [], 'caption_kind': '', 'confidence': 'high'}],
              'dismiss': [], 'pages_consulted': [9], 'notes': []}
    applied = fd.apply_detect(pf, item9, t2.rows_by_item[item9['key']], reply9, DIGEST, 'detect-v2', 'm')
    placeholder = Figure.get((Figure.page == 9) & (Figure.assembly == 'page'))
    assert applied.new == 0 and not placeholder.dismissed and placeholder.detect_key == item9['key']


@pytest.mark.unit
def test_a_persons_row_is_never_moved_or_folded_by_a_reply(doubted):
    from papermeister import figure_detect as fd
    from papermeister.models import Figure
    pf, rows = doubted
    a = [r for r in rows if r.page == 28][0]
    a.user_confirmed = True
    a.save()
    t = fd.detect_items(pf, PAGES, DIGEST, PROMPT)
    item = t.items[1]
    assert str(a.id) not in item['figure_keys'] and ('locked' in [why for _, why in t.excluded])
    b, c = item['figure_keys']
    reply = {'figures': [{'bbox_page_1000': [40, 60, 540, 330], 'from': [str(a.id), b, c], 'name': '', 'name_inferred': False,
                          'kind': 'plate', 'caption': '', 'caption_pages': [], 'caption_kind': '', 'confidence': 'high'}],
             'dismiss': [b], 'pages_consulted': [28], 'notes': []}
    applied = fd.apply_detect(pf, item, t.rows_by_item[item['key']], reply, DIGEST, PROMPT, 'm')
    # `a` was not even sent, so the merge is of b and c only — and a stays whole
    assert applied.new == 1 and applied.merged == 2 and applied.conflicts == 0
    assert not Figure.get_by_id(a.id).dismissed and json.loads(Figure.get_by_id(a.id).bbox_page_1000) == [48, 70, 282, 188]


@pytest.mark.unit
def test_no_reply_counts_an_attempt(doubted):
    from papermeister import figure_detect as fd
    from papermeister.models import Figure
    pf, rows = doubted
    t = fd.detect_items(pf, PAGES, DIGEST, PROMPT)
    item = t.items[1]
    applied = fd.apply_detect(pf, item, t.rows_by_item[item['key']], None, DIGEST, PROMPT, 'm')
    assert applied.failed == 1
    assert all(Figure.get_by_id(int(i)).detect_attempts == 1 for i in item['figure_keys'])
    for i in item['figure_keys']:
        r = Figure.get_by_id(int(i))
        r.detect_attempts = 3
        r.save()
    assert [it['page'] for it in fd.detect_items(pf, PAGES, DIGEST, PROMPT).items] == [9]
    assert [it['page'] for it in fd.detect_items(pf, PAGES, DIGEST, PROMPT, retry_errors=True).items] == [9, 28]


# ── the HTTP client against a fake session ───────────────────────────

class FakeResponse:
    def __init__(self, status, body=None, text=''):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.jobs = {}

    def head(self, url, **kw):
        self.calls.append(('HEAD', url))
        return FakeResponse(200 if url.endswith('/pdfs/have') or url.endswith('/ws/have') else 404)

    def post(self, url, json=None, files=None, data=None, **kw):
        self.calls.append(('POST', url, json))
        if url.endswith('/figures/link'):
            return FakeResponse(202, {'job_id': 'j1', 'total': 1, 'cached': 0, 'queued': 1})
        if url.endswith('/figures/workspace'):
            return FakeResponse(201, {'ok': True})
        return FakeResponse(500, None, '<html>proxy error</html>')

    def get(self, url, params=None, **kw):
        self.calls.append(('GET', url))
        n = sum(1 for c in self.calls if c[0] == 'GET' and '/figures/link/j1' in c[1])
        if url.endswith('/figures/link/j1'):
            if n == 1:
                return FakeResponse(200, {'status': 'processing', 'done': 0, 'total': 1,
                                          'worker': {'state': 'paused', 'paused_reason': 'usage limit'}})
            return FakeResponse(200, {'status': 'done', 'done': 1, 'total': 1, 'worker': {'state': 'idle'},
                                      'items': [{'key': 'k', 'status': 'done', 'result': {'figures': []}}]})
        return FakeResponse(200, [])


@pytest.mark.unit
def test_the_client_sends_the_id_polls_and_reports_a_paused_worker(monkeypatch):
    from papermeister import figure_client as fc
    monkeypatch.setattr(fc.time, 'sleep', lambda s: None)
    s = FakeSession()
    c = fc.FigureClient('http://wrapper/', 'papermeister-test', session=s)
    assert s.headers['X-Client-ID'] == 'papermeister-test'
    assert c.has_pdf('have') and not c.has_pdf('missing')
    r = c.submit('link', {'items': [{'key': 'k'}]})
    assert r['job_id'] == 'j1' and s.calls[-1][2]['client_id'] == 'papermeister-test'
    seen = []
    job = c.wait('link', 'j1', poll_seconds=0, on_progress=lambda j: seen.append(j['worker']['state']))
    assert job['status'] == 'done' and seen == ['paused', 'idle']
    with pytest.raises(fc.FigureServerError, match='not JSON'):
        c.upload_workspace({'file_hash': 'x', 'ocr_digest': 'y', 'pages': []}) if False else fc._json(
            FakeResponse(200, None, '<html>'), 'x')
    with pytest.raises(fc.FigureServerError, match='HTTP 500'):
        c.submit('panels', {'items': []})
