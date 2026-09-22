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
