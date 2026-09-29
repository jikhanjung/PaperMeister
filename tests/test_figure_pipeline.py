"""One paper through the stages with a fake server: what runs, what is
skipped, what a cancel and a server error leave behind."""
import json
import os
import tempfile

import pytest

HASH = 'ef' * 32


def block(label, bbox, text):
    return f'<div data-label="{label}" data-bbox="{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}">{text}</div>'


PAGES = [
    block('Text', (100, 100, 900, 900), 'Introduction. ' * 30),
    block('Section-Header', (100, 100, 900, 130), 'Explanation of Plate 2')
    + block('Text', (100, 150, 900, 900), 'PLATE 2. Oistodus aff. breviconus. Fig. 1. Lateral view, YSUG 00287. Fig. 2. Posterior view, YSUG 00288. '
            + 'All specimens from the Dumugol Formation, Mungyeong; scale bars 100 micrometres unless stated. ' * 3),
    block('Page-Header', (300, 20, 700, 45), 'PLATE 2')
    + block('Image', (100, 100, 480, 480), '<img alt="a">') + block('Image', (520, 100, 900, 480), '<img alt="b">'),
]


@pytest.fixture
def paper(monkeypatch):
    work = tempfile.mkdtemp(prefix='pm-pipe-')
    monkeypatch.setenv('PAPERMEISTER_DATA_DIR', work)
    from papermeister.database import init_db
    database = init_db(os.path.join(work, 'test.db'))
    from papermeister.models import Paper, PaperFile
    from papermeister.paths import OCR_JSON_DIR
    from papermeister.text_extract import ocr_json_filename
    pf = PaperFile.create(paper=Paper.create(title='Lee 2004'), path='lee.pdf', hash=HASH, status='processed')
    os.makedirs(OCR_JSON_DIR, exist_ok=True)
    with open(os.path.join(OCR_JSON_DIR, ocr_json_filename(pf)), 'w', encoding='utf-8') as f:
        json.dump({'pages': [{'page': i, 'markdown': t} for i, t in enumerate(PAGES)]}, f)
    yield pf
    database.close()


class FakeClient:
    """Answers link with a caption for every figure sent, panels with two panels."""

    def __init__(self, fail_kind=None):
        self.client_id = 'papermeister-test'
        self.submitted = []
        self.fail_kind = fail_kind

    def has_pdf(self, h):
        return True

    def has_workspace(self, h, d):
        return True

    def submit(self, kind, body):
        from papermeister.figure_client import FigureServerError
        if kind == self.fail_kind:
            raise FigureServerError('boom')
        self.submitted.append((kind, body))
        return {'job_id': f'{kind}-1', 'total': len(body['items']), 'cached': 0, 'queued': len(body['items'])}

    # What a closed app left behind: the lanes' and the app's collect read these.
    def jobs(self, kind=None, status=None):
        return [{'job_id': f'{k}-{i}', 'kind': k, 'status': 'done', 'total': len(b['items'])}
                for i, (k, b) in enumerate(self.submitted) if kind in (None, k)]

    def job(self, kind, job_id):
        index = int(job_id.rsplit('-', 1)[1])
        return self._answer(kind, self.submitted[index][1])

    def wait(self, kind, job_id, poll_seconds=0, on_progress=None, should_stop=None):
        if should_stop:
            should_stop()
        body = next(b for k, b in self.submitted if k == kind)
        return self._answer(kind, body)

    def _answer(self, kind, body):
        items = []
        for it in body['items']:
            if kind == 'link':
                result = {'figures': [{'figure_id': f['figure_id'], 'name': 'Plate 2',
                                       'caption': 'PLATE 2. Oistodus aff. breviconus.', 'caption_source': 'explanation_page',
                                       'caption_pages': [1], 'continuation_of': None,
                                       'entries': [{'label': '1', 'printed_label': '1', 'description': 'Lateral view, YSUG 00287', 'specimen_number': 'YSUG 00287'},
                                                   {'label': '2', 'printed_label': '2', 'description': 'Posterior view, YSUG 00288', 'specimen_number': 'YSUG 00288'}]}
                                      for f in it['figures'] if not f['locked']],
                          'skipped': [], 'pages_consulted': [1, 2], 'notes': []}
            else:
                result = {'is_compound': True, 'figure_kind': 'fossil_plate', 'non_compound_reason': '',
                          'panels': [{'label': '1', 'bbox_figure_1000': [0, 0, 480, 1000], 'caption_indices': [0], 'confidence': 'high'},
                                     {'label': '2', 'bbox_figure_1000': [520, 0, 1000, 1000], 'caption_indices': [1], 'confidence': 'high'}],
                          'annotation_indices': [], 'notes': []}
            items.append({'key': it['key'], 'status': 'done', 'result': result, 'model': 'fake'})
        return {'status': 'done', 'items': items}


@pytest.mark.unit
def test_a_paper_runs_through_all_stages_and_resumes_where_it_stopped(paper):
    from papermeister import figure_pipeline as fp
    from papermeister.models import Figure, FigureEntry, FigurePanel
    log = []
    client = FakeClient()
    report = fp.process_file(paper, client, lambda k, m: log.append((k, m)))
    assert report.error == ''
    s = report.stages
    assert s['assemble'].ran and s['assemble'].due == 1
    assert not s['detect'].ran                              # a plate with a printed number: no doubt
    assert s['link'].ran and s['link'].written == 1
    assert s['panels'].ran and s['panels'].written == 1
    assert [k for k, _ in client.submitted] == ['link', 'panels']
    row = Figure.get(Figure.paper_file == paper.id)
    assert row.caption.startswith('PLATE 2') and FigureEntry.select().where(FigureEntry.figure == row.id).count() == 2
    assert FigurePanel.select().where(FigurePanel.figure == row.id).count() == 2
    # the Text tab's list reads the counts back
    from desktop.services.paper_service import load_figures
    shown = load_figures(paper.paper_id)
    assert (shown[0].entries, shown[0].panels, shown[0].unmatched, shown[0].panel_state) == (2, 2, 0, 'split')
    # the cache JSON carries it
    from papermeister.figure_share import cache_path
    with open(cache_path(paper), encoding='utf-8') as f:
        assert len(json.load(f)['figures']['rows']) == 1
    # a second run submits nothing: every stage is done by its key
    client2 = FakeClient()
    report2 = fp.process_file(paper, client2, lambda k, m: None)
    assert client2.submitted == [] and report2.summary().startswith('assemble')
    assert not report2.stages['link'].ran and not report2.stages['panels'].ran


@pytest.mark.unit
def test_cancel_and_server_error_leave_the_paper_resumable(paper):
    from papermeister import figure_pipeline as fp
    from papermeister.models import Figure
    stop = {'now': False}

    def should_stop():
        return stop['now']

    class StoppingClient(FakeClient):
        def submit(self, kind, body):
            stop['now'] = True          # the user cancels while the first job is out
            return super().submit(kind, body)

    log = []
    report = fp.process_file(paper, StoppingClient(), lambda k, m: log.append((k, m)), should_stop=should_stop)
    assert report.error == 'cancelled' and any(k == 'warn' for k, _ in log)
    assert Figure.get(Figure.paper_file == paper.id).caption == ''       # nothing half-written

    report = fp.process_file(paper, FakeClient(fail_kind='link'), lambda k, m: log.append((k, m)))
    assert report.error.startswith('server:') and not report.stages['panels'].ran
    # and the normal run afterwards completes
    assert fp.process_file(paper, FakeClient(), lambda k, m: None).error == ''
    assert Figure.get(Figure.paper_file == paper.id).caption.startswith('PLATE 2')


@pytest.mark.unit
def test_no_cache_means_nothing_runs(paper, monkeypatch):
    from papermeister import figure_pipeline as fp
    from papermeister.figure_share import cache_path
    os.remove(cache_path(paper))
    report = fp.process_file(paper, FakeClient(), lambda k, m: None)
    assert 'OCR' in report.error and not report.stages['assemble'].ran


@pytest.mark.unit
def test_the_server_hint_names_the_missing_setting(monkeypatch):
    from papermeister import figure_pipeline as fp
    monkeypatch.setattr('papermeister.preferences.get_pref', lambda k, d=None: {'ocr_backend': 'serverless'}.get(k, d))
    assert 'wrapper' in fp.server_hint()
    monkeypatch.setattr('papermeister.preferences.get_pref',
                        lambda k, d=None: {'ocr_backend': 'wrapper', 'ocr_pod_url': 'http://x'}.get(k, d))
    assert fp.server_hint() == ''


@pytest.mark.unit
def test_a_job_left_on_the_server_by_a_closed_app_is_collected_later(paper):
    """Closing the app mid-run leaves the submitted job finishing on the
    server. The next start (or the next Process Figures) lands it."""
    from papermeister import figure_pipeline as fp
    from papermeister.models import Figure, FigurePanel

    class ClosingClient(FakeClient):
        def wait(self, kind, job_id, poll_seconds=0, on_progress=None, should_stop=None):
            raise fp.Cancelled()                 # the app closed while the job was out

    client = ClosingClient()
    report = fp.process_file(paper, client, lambda k, m: None)
    assert report.error == 'cancelled' and [k for k, _ in client.submitted] == ['link']
    assert Figure.get(Figure.paper_file == paper.id).caption == ''
    # next start: the finished link job lands; nothing is re-asked
    log = []
    collected = fp.collect_finished(client, lambda k, m: log.append(m))
    assert collected.jobs == 1 and collected.link_written == 1 and collected.papers == {paper.paper_id}
    assert Figure.get(Figure.paper_file == paper.id).caption.startswith('PLATE 2')
    assert any('collected captions' in m for m in log)
    # collecting again finds nothing new; then a full run only needs panels
    again = fp.collect_finished(client)
    assert again.jobs == 0 and again.settled                 # read, wrote nothing: settled
    assert fp.collect_finished(client, skip_jobs=again.settled).settled == set()   # and not read again
    reopened = FakeClient()                      # the app open again, waiting normally
    reopened.submitted = client.submitted
    report = fp.process_file(paper, reopened, lambda k, m: None)
    assert report.error == '' and [k for k, _ in reopened.submitted] == ['link', 'panels']
    assert FigurePanel.select().where(FigurePanel.figure == Figure.get(Figure.paper_file == paper.id).id).count() == 2
    assert fp.collect_finished(reopened).jobs == 0


@pytest.mark.unit
def test_the_queue_runner_never_submits_what_is_already_waiting(paper):
    """2026-09-24/25: a figure whose split was queued stayed 'due' in the DB,
    and every five-minute pass submitted it again — fifty jobs for two
    figures, a full queue, and nothing else got in."""
    from papermeister import figure_pipeline as fp
    from papermeister import figure_prompts
    from scripts import figure_queue as fq

    client = FakeClient()
    fp.process_file(paper, client, lambda k, m: None, stages=('assemble', 'link'))
    fp.collect_finished(client)
    prompt = figure_prompts.load('panels')
    outstanding: set[str] = set()
    assert fq.submit_panels(client, paper, prompt, outstanding) == 1
    assert fq.submit_panels(client, paper, prompt, outstanding) == 0       # same pass: already out
    fresh_view = {it['key'] for k, b in client.submitted if k == 'panels' for it in b['items']}
    assert fq.submit_panels(client, paper, prompt, set(fresh_view)) == 0    # next pass, read off the server
    assert [k for k, _ in client.submitted].count('panels') == 1


@pytest.mark.unit
def test_a_batch_finishes_its_splits_before_the_next_batch_links(paper, monkeypatch):
    """The server is first in, first out. A batch's splits submitted after the
    next batch's captions would wait behind a day of captions — so the next
    batch's link waits until this batch's splits are asked for."""
    from collections import Counter
    from types import SimpleNamespace

    from papermeister import figure_pipeline as fp
    from papermeister import figure_prompts
    from papermeister.models import Paper, PaperFile
    from scripts import figure_queue as fq

    # batch B: a second paper nobody has linked yet
    other = PaperFile.create(paper=Paper.create(title='Kim 1999'), path='kim.pdf', hash='cd' * 32, status='processed')
    monkeypatch.setattr(fq, 'pages_of', lambda pf: PAGES)
    a = fq.Batch('A', 'first', [paper.id])
    b = fq.Batch('B', 'second', [other.id])
    client = FakeClient()
    state, done = {}, set()
    args = SimpleNamespace(per_item=80)
    link, panels = figure_prompts.load('link'), figure_prompts.load('panels')

    # pass 1: batch A's link goes out; B waits
    fq.fill_queue(client, [a, b], state, done, set(), 100, link, panels, args, Counter())
    assert [k for k, _ in client.submitted] == ['link']
    assert client.submitted[0][1]['file_hash'] == paper.hash
    # its captions land (and are no longer waiting on the server)
    fp.collect_finished(client)
    # pass 2: A's splits go out before B's link
    fq.fill_queue(client, [a, b], state, done, set(), 100, link, panels, args, Counter())
    kinds = [k for k, _ in client.submitted]
    assert kinds[:2] == ['link', 'panels'] and kinds.index('panels') < len(kinds)
    if len(kinds) > 2:                                   # B's link only after A's splits
        assert kinds[2] == 'link' and client.submitted[2][1]['file_hash'] == other.hash
    assert 'A' in done


@pytest.mark.unit
def test_a_failed_reattach_left_for_a_person_does_not_hold_the_batch_open(paper):
    """2026-09-30: 29 rows whose panels could not be re-attached to their
    new entries were flagged for a person — and counted as the batch's
    pending work, so the pilot never finished and the queue ran dry."""
    import json

    from papermeister import figure_panels
    from scripts import figure_queue as fq

    class Row:
        def __init__(self, reasons):
            self.uncertain_reasons_json = json.dumps(reasons)
    flagged = Row([figure_panels.ENTRIES_CHANGED_UNMAPPED])
    fresh = Row([])
    assert fq._pending_rematch([flagged, fresh]) == [fresh]
    assert fq._pending_rematch([flagged]) == []


@pytest.mark.unit
def test_process_figures_waits_for_what_the_runner_already_submitted(paper):
    """The app's Process Figures used to resubmit a paper the queue runner
    had already asked for. Now items already waiting on the server are
    waited for, not submitted again."""
    from papermeister import figure_pipeline as fp
    from papermeister.models import Figure, FigurePanel

    runner = FakeClient()                                  # the runner's view: link done, panels queued
    fp.process_file(paper, runner, lambda k, m: None, stages=('assemble', 'link'))
    fp.collect_finished(runner)
    from papermeister import figure_panels, figure_prompts
    v = figure_prompts.load('panels')['version']
    rows = figure_panels.split_targets(paper, v).due
    queued_body = {'items': [figure_panels.panel_item(r, v) for r in rows]}

    class AppClient(FakeClient):
        """The server holds the runner's queued panels job."""
        def jobs(self, kind=None, status=None):
            own = super().jobs(kind, status)
            return own + ([{'job_id': 'runner-panels', 'kind': 'panels', 'status': 'queued',
                            'total': len(queued_body['items']), 'done': 0}] if kind in (None, 'panels') else [])

        def job(self, kind, job_id):
            if job_id == 'runner-panels':
                return {'items': [{'key': it['key'], 'status': 'queued'} for it in queued_body['items']]}
            return super().job(kind, job_id)

        def wait(self, kind, job_id, poll_seconds=0, on_progress=None, should_stop=None):
            if job_id == 'runner-panels':
                return self._answer('panels', queued_body)
            return super().wait(kind, job_id, poll_seconds, on_progress, should_stop)

    app = AppClient()
    log = []
    report = fp.process_file(paper, app, lambda k, m: log.append(m))
    assert report.error == ''
    assert [k for k, _ in app.submitted] == []                          # nothing submitted twice
    assert any('already on the server' in m for m in log)
    row = Figure.get(Figure.paper_file == paper.id)
    assert FigurePanel.select().where(FigurePanel.figure == row.id).count() == 2   # and the reply landed
