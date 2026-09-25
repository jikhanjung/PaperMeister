"""One paper through the figure stages, in order: ① assemble → ①′ detect →
② link → ③ panels. What the app's "Process Figures" runs; the lane scripts
do the same stages one at a time across many papers.

A stage that has nothing due is skipped — the keys on the rows say what is
done (`detect_key`, `link_key`, `panel_key`), so a paper processed halfway
resumes where it stopped, and a paper whose captions a person fixed re-runs
only the panels. Every stage ends by writing the paper's figures into its
cache JSON (figure_share), so the next machine sees them.

Runs off the UI thread with its own DB connection (peewee's are
thread-local); one paper at a time — the server is serial anyway. Nothing is
killed on cancel: the job already submitted finishes on the server and is
picked up later by the lanes' `--collect`.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from . import (
    figure_detect,
    figure_lane,
    figure_link,
    figure_panels,
    figure_prompts,
    figure_share,
    figure_store,
    figures,
)
from .figure_client import FigureClient, FigureServerError
from .models import Figure, PaperFile
from .paths import OCR_JSON_DIR

Notify = Callable[[str, str], None]        # (kind, message): 'info' | 'wait' | 'warn' | 'error'
Progress = Callable[[int, int], None]      # (done, total) within the paper
Stop = Callable[[], bool]

STAGES = ('assemble', 'detect', 'link', 'panels')


class Cancelled(Exception):
    pass


@dataclass
class StageReport:
    ran: bool = False
    due: int = 0
    written: int = 0
    failed: int = 0
    note: str = ''


@dataclass
class PipelineReport:
    paper_file_id: int
    stages: dict[str, StageReport] = field(default_factory=lambda: {s: StageReport() for s in STAGES})
    error: str = ''

    def summary(self) -> str:
        bits = []
        for name in STAGES:
            r = self.stages[name]
            if not r.ran:
                continue
            bits.append(f'{name} {r.written}/{r.due}' + (f' ({r.note})' if r.note else ''))
        return ', '.join(bits) if bits else 'nothing to do'


def server_hint() -> str:
    """Why "Process Figures" cannot run now, or '' when it can."""
    from .preferences import get_pref
    if get_pref('ocr_backend', 'serverless') != 'wrapper' or not get_pref('ocr_pod_url', ''):
        return ('Figure processing needs the wrapper OCR server (Preferences → OCR → Wrapper API). '
                'Figures found on another machine still show in the Text tab.')
    return ''


def _pages_of(pf: PaperFile) -> list[str] | None:
    import json

    from . import ocr_layout
    from .text_extract import ocr_json_filename
    path = os.path.join(OCR_JSON_DIR, ocr_json_filename(pf))
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    pages = [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]
    return pages if any(ocr_layout.is_structured(t) for t in pages) else None


def process_file(pf: PaperFile, client: FigureClient, notify: Notify, progress: Progress | None = None,
                 should_stop: Stop | None = None, stages: tuple[str, ...] = STAGES) -> PipelineReport:
    report = PipelineReport(paper_file_id=pf.id)
    stop = should_stop or (lambda: False)

    def check():
        if stop():
            raise Cancelled()

    pages = _pages_of(pf)
    if pages is None:
        report.error = 'no structured OCR cache for this file (run OCR first)'
        notify('warn', report.error)
        return report
    digest = figure_link.ocr_digest(pages)
    prompts = {kind: figure_prompts.load(kind) for kind in ('detect', 'link', 'panels')}
    total = len(stages)
    try:
        for index, stage in enumerate(stages):
            check()
            if progress:
                progress(index, total)
            notify('info', f'{stage}…')
            _STAGE_FN[stage](pf, pages, digest, client, prompts, notify, report.stages[stage], check)
        if progress:
            progress(total, total)
    except Cancelled:
        report.error = 'cancelled'
        notify('warn', 'cancelled — a job already submitted finishes on the server; collect it later')
    except FigureServerError as exc:
        report.error = f'server: {exc}'
        notify('error', report.error)
    return report


# ── stages ───────────────────────────────────────────────────────────

def _assemble(pf, pages, digest, client, prompts, notify, r: StageReport, check) -> None:
    r.ran = True
    if not Figure.select().where(Figure.paper_file == pf.id).exists():
        shared = figure_share.import_from_cache(pf)
        if shared.created:
            r.note = f'{shared.created} from the cache JSON'
    assembled = figure_store.with_placeholders(figures.assemble_document(pages))
    plan = figure_store.plan_store(pf, assembled)
    figure_store.apply_plan(plan)
    r.due = len(assembled)
    r.written = len(plan.create) + len(plan.refresh) + len(plan.move) + len(plan.restore)
    notify('info', f'assembled {len(assembled)} figures (new {len(plan.create)}, folded {len(plan.dismiss)})')


def _detect(pf, pages, digest, client, prompts, notify, r: StageReport, check) -> None:
    prompt = prompts['detect']
    targets = figure_detect.detect_items(pf, pages, digest, prompt['version'])
    r.due = len(targets.items)
    if not targets.items:
        return
    r.ran = True
    figure_lane.ensure_workspace(client, pf, figure_link.workspace_payload(pf, pages), lambda m: notify('info', m))
    body = figure_detect.detect_payload(pf, digest, targets, client.client_id, prompt)
    job = _run(client, 'detect', body, notify, check)
    results = figure_lane.results_by_key(job)
    for item in targets.items:
        reply = results.get(item['key'], {})
        result = reply.get('result') if reply.get('status') == 'done' else None
        applied = figure_detect.apply_detect(pf, item, targets.rows_by_item[item['key']], result, digest,
                                             prompt['version'], reply.get('model') or 'gpt-6-astra')
        r.written += 1 if result else 0
        r.failed += applied.failed
    r.note = _note(r)
    figure_share.write_to_cache(pf)


def _link(pf, pages, digest, client, prompts, notify, r: StageReport, check) -> None:
    prompt = prompts['link']
    targets = figure_link.link_targets(pf, digest, prompt['version'])
    r.due = len(targets.due)
    if not targets.due:
        return
    r.ran = True
    request = figure_link.link_payload(pf, pages, targets, digest, client.client_id, prompt)
    figure_lane.ensure_workspace(client, pf, figure_link.workspace_for(pf, pages, request), lambda m: notify('info', m))
    if request.get('reading_pages'):
        notify('info', f'link: reading {len(request["reading_pages"])} of {len(pages)} pages')
    job = _run(client, 'link', request, notify, check)
    replies = figure_lane.results_by_key(job)
    check_ = figure_link.LinkCheck()
    existing = {str(x.id): x for x in targets.due}
    model = 'gpt-6-astra'
    for item in request['items']:
        reply = replies.get(item['key'], {})
        if reply.get('status') == 'done' and isinstance(reply.get('result'), dict):
            check_.merge(figure_link.validate_link_result(item, reply['result'], pages, existing))
            model = reply.get('model') or model
        else:
            r.note = reply.get('status', 'missing')
    applied = figure_link.apply_link(targets, check_, {}, digest, prompt['version'], model)
    r.written, r.failed = applied.written, applied.failed
    figure_link.propagate_link(pf)
    r.note = r.note or _note(r)
    figure_share.write_to_cache(pf)


def _panels(pf, pages, digest, client, prompts, notify, r: StageReport, check) -> None:
    prompt = prompts['panels']
    targets = figure_panels.split_targets(pf, prompt['version'])
    for row in targets.rematch:
        figure_panels.rematch(row)
    r.due = len(targets.due)
    if not targets.due:
        if targets.rematch:
            r.ran, r.note = True, f'{len(targets.rematch)} re-attached'
            figure_share.write_to_cache(pf)
        return
    r.ran = True
    figure_lane.ensure_pdf(client, pf, lambda m: notify('info', m))
    items = [figure_panels.panel_item(row, prompt['version']) for row in targets.due]
    body = {'client_id': client.client_id, 'file_hash': pf.hash, 'items': items, 'prompt': prompt,
            'options': {'model': 'gpt-6-astra', 'effort': 'high', 'dpi': figure_panels.RENDER_DPI}}
    job = _run(client, 'panels', body, notify, check)
    results = figure_lane.results_by_key(job)
    for row, item in zip(targets.due, items, strict=True):
        reply = results.get(item['key'], {})
        result = reply.get('result') if reply.get('status') == 'done' else None
        siblings = Figure.select().where((Figure.paper_file == pf.id) & (Figure.page == row.page)
                                         & (Figure.id != row.id) & (Figure.dismissed == False)).count()  # noqa: E712
        check_ = figure_panels.validate_panel_result(item, result, siblings) if result else None
        applied = figure_panels.apply_panels(row, item, result, check_, prompt['version'],
                                             reply.get('model') or 'gpt-6-astra')
        r.written += applied.written + applied.unchanged
        r.failed += applied.failed
    r.note = _note(r)
    figure_share.write_to_cache(pf)


_STAGE_FN = {'assemble': _assemble, 'detect': _detect, 'link': _link, 'panels': _panels}


# ── what the server still holds ──────────────────────────────────────

@dataclass
class CollectReport:
    jobs: int = 0
    link_written: int = 0
    panels_written: int = 0
    papers: set = field(default_factory=set)      # paper ids touched
    skipped: int = 0                              # replies nothing here was waiting for
    #: Finished jobs that wrote nothing and never will (every row they name
    #: is applied, or gone): a caller may pass them back as `skip_jobs`, so
    #: a long run does not re-read the same job bodies every pass.
    settled: set = field(default_factory=set)

    def summary(self) -> str:
        if not self.jobs:
            return 'nothing to collect'
        return (f'{self.jobs} finished job(s): {self.link_written} caption(s), {self.panels_written} panel split(s) '
                f'landed on {len(self.papers)} paper(s)')


def collect_finished(client: FigureClient, notify: Notify | None = None,
                     skip_jobs: set | None = None) -> CollectReport:
    """Land the replies of finished link and panels jobs this client left on
    the server — a paper whose Process Figures was cut short by closing the
    app, or one run by the lane scripts elsewhere. Same code path as the
    lanes' `--collect`; a reply already applied is unchanged."""
    from . import figure_lane, figure_link, figure_panels, figure_prompts, figure_share
    report = CollectReport()
    say = notify or (lambda k, m: None)
    link_prompt = figure_prompts.load('link')
    panels_prompt = figure_prompts.load('panels')

    skip = skip_jobs or set()
    for job in client.jobs(kind='link'):
        if job.get('status') not in ('done', 'done_with_errors') or job['job_id'] in skip:
            continue
        replies = figure_lane.results_by_key(client.job('link', job['job_id']))
        pf = _file_of_replies(replies)
        if pf is None:
            report.skipped += 1
            report.settled.add(job['job_id'])
            continue
        pages = _pages_of(pf)
        if pages is None:
            report.skipped += 1
            report.settled.add(job['job_id'])
            continue
        digest = figure_link.ocr_digest(pages)
        targets = figure_link.link_targets(pf, digest, link_prompt['version'])
        if not targets.due:
            report.settled.add(job['job_id'])
            continue
        items = figure_link.items_from_replies(pf, pages, targets, digest, link_prompt['version'], replies)
        if not items:
            report.skipped += 1
            report.settled.add(job['job_id'])
            continue
        check = figure_link.LinkCheck()
        existing = {str(x.id): x for x in targets.due}
        model = 'gpt-6-astra'
        for item in items:
            reply = replies.get(item['key'], {})
            if reply.get('status') == 'done' and isinstance(reply.get('result'), dict):
                check.merge(figure_link.validate_link_result(item, reply['result'], pages, existing))
                model = reply.get('model') or model
        applied = figure_link.apply_link(targets, check, {}, digest, link_prompt['version'], model)
        figure_link.propagate_link(pf)
        if not applied.written:
            # The same reply read again (skipped rows stay due without a new
            # attempt): nothing will change until a new reply arrives.
            report.settled.add(job['job_id'])
            continue
        report.jobs += 1
        report.link_written += applied.written
        report.papers.add(pf.paper_id)
        figure_share.write_to_cache(pf)
        say('info', f'collected captions for paper {pf.paper_id}: {applied.written} written')

    for job in client.jobs(kind='panels'):
        if job.get('status') not in ('done', 'done_with_errors') or job['job_id'] in skip:
            continue
        replies = figure_lane.results_by_key(client.job('panels', job['job_id']))
        rows, items = [], []
        for key in replies:
            fid = key.split('@')[0]
            row = Figure.get_or_none(Figure.id == int(fid)) if fid.isdigit() else None
            if row is None or row.dismissed:
                continue
            item = figure_panels.panel_item(row, panels_prompt['version'])
            if item['key'] != key or (row.panel_key == key.split('@', 1)[1] and row.panel_result_digest):
                continue
            rows.append(row)
            items.append(item)
        if not rows:
            report.settled.add(job['job_id'])
            continue
        report.jobs += 1
        pf = PaperFile.get_by_id(rows[0].paper_file_id)
        for row, item in zip(rows, items, strict=True):
            reply = replies.get(item['key'], {})
            result = reply.get('result') if reply.get('status') == 'done' else None
            siblings = Figure.select().where((Figure.paper_file == pf.id) & (Figure.page == row.page)
                                             & (Figure.id != row.id) & (Figure.dismissed == False)).count()  # noqa: E712
            check_ = figure_panels.validate_panel_result(item, result, siblings) if result else None
            applied = figure_panels.apply_panels(row, item, result, check_, panels_prompt['version'],
                                                 reply.get('model') or 'gpt-6-astra')
            report.panels_written += applied.written
        report.papers.add(pf.paper_id)
        figure_share.write_to_cache(pf)
        say('info', f'collected panels for paper {pf.paper_id}: {len(rows)} figure(s)')
    return report


def _file_of_replies(replies: dict) -> PaperFile | None:
    """The file whose rows a link reply names; twins of one PDF share the hash prefix."""
    for reply in replies.values():
        result = reply.get('result') if isinstance(reply, dict) else None
        for f in ((result or {}).get('figures') or []) + ((result or {}).get('skipped') or []):
            fid = str(f.get('figure_id', ''))
            if fid.isdigit():
                row = Figure.get_or_none(Figure.id == int(fid))
                if row is not None:
                    return PaperFile.get_or_none(PaperFile.id == row.paper_file_id)
    prefix = next(iter(replies), '').split('@')[0]
    if prefix:
        return PaperFile.select().where(PaperFile.hash.startswith(prefix) & ~PaperFile.path.endswith('.json')).first()
    return None


def _note(r: StageReport) -> str:
    return f'{r.failed} without a usable reply' if r.failed else ''


def _run(client: FigureClient, kind: str, body: dict, notify: Notify, check) -> dict:
    """Submit and wait, reporting the worker's state; a paused worker is a wait, not a failure."""
    reply = client.submit(kind, body)
    notify('info', f'{kind}: {reply.get("total", len(body["items"]))} item(s) submitted'
                   + (f', {reply["cached"]} cached' if reply.get('cached') else ''))

    def on_progress(job: dict) -> None:
        w = job.get('worker') or {}
        if w.get('paused_reason'):
            notify('wait', f'server worker paused: {w["paused_reason"]} — waiting')
        else:
            notify('info', f'{kind}: {job.get("done", 0)}/{job.get("total", 0)} done, worker {w.get("state", "?")}')

    return client.wait(kind, reply['job_id'], poll_seconds=15, on_progress=on_progress, should_stop=check)
