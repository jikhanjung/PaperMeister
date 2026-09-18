"""HTTP to ocrserver's figure endpoints (wrapper 0.3.3, `docs/figure_server_spec_v2.md`).

Thin on purpose: one method per endpoint, plus `wait()` for a job. Nothing
here knows what a figure is. The base URL is the wrapper the OCR stage
already talks to (`ocr_pod_url`), and `client_id` is the same per-install id
the OCR stage sends, so the server's fair-share scheduler and dedup see one
client.

Replies that are not JSON are reported with what came back — a proxy in
front of the wrapper returns HTML pages with good status codes, and "Expecting
value: line 1 column 1" once cost a run's worth of guessing (ocr.py).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)

TERMINAL = frozenset({'done', 'done_with_errors', 'failed', 'cancelled'})   # wrapper 0.3.4: cancel endpoint


class FigureServerError(RuntimeError):
    pass


def _json(resp: requests.Response, what: str) -> dict:
    try:
        return resp.json()
    except ValueError:
        snippet = (resp.text or '')[:200].replace('\n', ' ')
        raise FigureServerError(f'{what}: HTTP {resp.status_code} but the reply is not JSON: {snippet!r}') from None


class FigureClient:
    def __init__(self, base_url: str, client_id: str, session: requests.Session | None = None):
        if not base_url:
            raise FigureServerError('ocr_pod_url is empty: set the wrapper URL in Preferences')
        self.base = base_url.rstrip('/')
        self.client_id = client_id
        self.http = session or requests.Session()
        self.http.headers['X-Client-ID'] = client_id

    # ── PDFs and workspaces ───────────────────────────────────────────

    def has_pdf(self, file_hash: str) -> bool:
        r = self.http.head(f'{self.base}/pdfs/{file_hash}', timeout=15)
        return r.status_code == 200

    def upload_pdf(self, path: str) -> dict:
        with open(path, 'rb') as f:
            r = self.http.post(f'{self.base}/pdfs', files={'file': f}, data={'client_id': self.client_id},
                               timeout=600)
        if r.status_code not in (200, 201):
            raise FigureServerError(f'POST /pdfs: HTTP {r.status_code} {r.text[:200]!r}')
        return _json(r, 'POST /pdfs')

    def has_workspace(self, file_hash: str, ocr_digest: str) -> bool:
        r = self.http.head(f'{self.base}/figures/workspace/{file_hash}/{ocr_digest}', timeout=15)
        return r.status_code == 200

    def upload_workspace(self, body: dict) -> dict:
        r = self.http.post(f'{self.base}/figures/workspace', json={**body, 'client_id': self.client_id},
                           timeout=300)
        if r.status_code == 404:
            raise FigureServerError('POST /figures/workspace: the server has no PDF for this hash (pdf_missing)')
        if r.status_code not in (200, 201):
            raise FigureServerError(f'POST /figures/workspace: HTTP {r.status_code} {r.text[:200]!r}')
        return _json(r, 'POST /figures/workspace')

    # ── jobs ─────────────────────────────────────────────────────────

    def submit(self, kind: str, body: dict) -> dict:
        r = self.http.post(f'{self.base}/figures/{kind}', json={**body, 'client_id': self.client_id}, timeout=120)
        if r.status_code not in (200, 202):
            raise FigureServerError(f'POST /figures/{kind}: HTTP {r.status_code} {r.text[:300]!r}')
        return _json(r, f'POST /figures/{kind}')

    def job(self, kind: str, job_id: str) -> dict:
        r = self.http.get(f'{self.base}/figures/{kind}/{job_id}', timeout=30)
        if r.status_code != 200:
            raise FigureServerError(f'GET /figures/{kind}/{job_id}: HTTP {r.status_code}')
        return _json(r, f'GET /figures/{kind}/{job_id}')

    def jobs(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        params = {'client_id': self.client_id}
        if kind:
            params['kind'] = kind
        if status:
            params['status'] = status
        r = self.http.get(f'{self.base}/figures/jobs', params=params, timeout=30)
        if r.status_code != 200:
            raise FigureServerError(f'GET /figures/jobs: HTTP {r.status_code}')
        data = _json(r, 'GET /figures/jobs')
        if isinstance(data, list):
            return data
        return data.get('items') or data.get('jobs') or []     # wrapper 0.3.x: {"items": [...], "worker": {...}}

    def resume(self, kind: str, job_id: str, retry_errors: bool = False) -> dict:
        r = self.http.post(f'{self.base}/figures/{kind}/{job_id}/resume',
                           params={'retry_errors': 'true' if retry_errors else 'false'}, timeout=30)
        return _json(r, 'resume')

    def wait(self, kind: str, job_id: str, poll_seconds: float = 20.0, timeout_seconds: float | None = None,
             on_progress: Callable[[dict], None] | None = None) -> dict:
        """Poll until the job is terminal. A paused worker (login, usage limit)
        is reported through `on_progress` and waited out — it is not a failure
        of this job, and the queue keeps its place."""
        started = time.monotonic()
        last_signature = None
        while True:
            job = self.job(kind, job_id)
            signature = (job.get('status'), job.get('done'), job.get('failed'),
                         (job.get('worker') or {}).get('state'), (job.get('worker') or {}).get('paused_reason'))
            if on_progress and signature != last_signature:
                on_progress(job)
                last_signature = signature
            if job.get('status') in TERMINAL:
                return job
            if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                raise FigureServerError(f'{kind} job {job_id}: still {job.get("status")} after {timeout_seconds:.0f}s')
            time.sleep(poll_seconds)


def from_preferences() -> FigureClient:
    from .preferences import get_client_id, get_pref
    return FigureClient(get_pref('ocr_pod_url', ''), get_client_id())
