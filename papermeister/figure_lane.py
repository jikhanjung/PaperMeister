"""What every figure lane does around a job: find the PDF, make sure the
server has it and the paper's workspace, submit, wait, and hand results back
by item key. The stages' own logic (what to send, what to believe, what to
write) stays in figure_link / figure_panels / figure_detect.

Job ids are not persisted: the item keys are the cursor. A key names the
file (hash prefix), the page or figure, the text digest and the prompt, so a
finished job found later through `GET /figures/jobs` can be applied without
remembering that it was ours (review category 2, "fetched, not applied").
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

from .figure_client import FigureClient
from .models import PaperFile
from .paths import PDF_CACHE_DIR

logger = logging.getLogger(__name__)


def local_pdf(pf: PaperFile) -> str | None:
    """Where this file's PDF is on this machine — the desktop's rule, without Qt."""
    if pf.path and os.path.isfile(pf.path):
        return pf.path
    if pf.zotero_key and pf.path:
        cached = os.path.join(PDF_CACHE_DIR, pf.zotero_key, pf.path)
        if os.path.isfile(cached):
            return cached
    return None


def fetch_pdf(pf: PaperFile) -> str:
    """The PDF, downloaded from Zotero into pdf_cache when it is not here."""
    path = local_pdf(pf)
    if path:
        return path
    from .text_extract import _resolve_filepath
    path, _ = _resolve_filepath(pf)
    return path


def ensure_pdf(client: FigureClient, pf: PaperFile, log: Callable[[str], None] = logger.info) -> None:
    if client.has_pdf(pf.hash):
        return
    path = fetch_pdf(pf)
    log(f'  uploading PDF {os.path.basename(path)} ({os.path.getsize(path) / 1e6:.1f} MB)')
    reply = client.upload_pdf(path)
    if reply.get('file_hash') and reply['file_hash'] != pf.hash:
        # Another edition of the file: its page boxes would cut the wrong document.
        raise RuntimeError(f'server hashed the upload as {reply["file_hash"][:12]}, the library has {pf.hash[:12]}')


def ensure_workspace(client: FigureClient, pf: PaperFile, workspace: dict,
                     log: Callable[[str], None] = logger.info) -> None:
    if client.has_workspace(pf.hash, workspace['ocr_digest']):
        return
    ensure_pdf(client, pf, log)
    log(f'  uploading workspace ({len(workspace["pages"])} pages)')
    client.upload_workspace(workspace)


def run_job(client: FigureClient, kind: str, body: dict, log: Callable[[str], None] = logger.info,
            poll_seconds: float = 20.0, wait: bool = True) -> dict | None:
    """Submit and, unless `wait` is False, block until the job is terminal.
    Progress lines name the worker's state, so a paused worker (login, usage
    limit) is visible as waiting rather than as a hang."""
    reply = client.submit(kind, body)
    job_id = reply['job_id']
    log(f'  {kind} job {job_id}: {reply.get("total", len(body["items"]))} item(s), '
        f'cached {reply.get("cached", 0)}, queued {reply.get("queued", 0)}')
    if not wait:
        return None

    def progress(job: dict) -> None:
        w = job.get('worker') or {}
        state = w.get('state', '?')
        paused = f' — PAUSED: {w["paused_reason"]}' if w.get('paused_reason') else ''
        log(f'    {job.get("status")}  done {job.get("done", 0)}/{job.get("total", 0)}  '
            f'failed {job.get("failed", 0)}  worker {state}{paused}')

    return client.wait(kind, job_id, poll_seconds=poll_seconds, on_progress=progress)


def results_by_key(job: dict) -> dict[str, dict]:
    return {it['key']: it for it in job.get('items', []) if 'key' in it}
