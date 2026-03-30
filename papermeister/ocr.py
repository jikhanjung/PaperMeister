"""
RunPod OCR client for PaperMeister.

Sends PDF pages as base64 JPEG images to a Chandra2-vllm endpoint
on RunPod serverless, polls for results, and returns extracted text.

Environment variables (or .env in project root):
    RUNPOD_ENDPOINT_ID=...
    RUNPOD_API_KEY=...
"""

import base64
import io
import os
import time
from datetime import datetime
from pathlib import Path

import fitz
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

_BASE_URL = None
_HEADERS = None


class PayloadTooLarge(Exception):
    pass


def _ensure_config():
    global _BASE_URL, _HEADERS
    if _BASE_URL is not None:
        return
    endpoint_id = os.environ.get('RUNPOD_ENDPOINT_ID')
    api_key = os.environ.get('RUNPOD_API_KEY')
    if not endpoint_id or not api_key:
        raise RuntimeError(
            'RUNPOD_ENDPOINT_ID and RUNPOD_API_KEY must be set '
            '(environment variables or .env file)'
        )
    _BASE_URL = f'https://api.runpod.ai/v2/{endpoint_id}'
    _HEADERS = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }


# ── Page rendering ───────────────────────────────────────────

def render_page(pdf_path: str, page_idx: int, dpi: int = 150, quality: int = 85) -> str:
    """Render a single PDF page to base64 JPEG."""
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = doc[page_idx].get_pixmap(matrix=mat)
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    doc.close()

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def render_pages(pdf_path: str, page_indices: list[int], dpi: int = 150) -> list[str]:
    """Render multiple pages to base64 JPEGs."""
    return [render_page(pdf_path, idx, dpi) for idx in page_indices]


# ── RunPod API ───────────────────────────────────────────────

def check_health() -> dict:
    _ensure_config()
    resp = requests.get(
        f'{_BASE_URL}/health',
        headers={'Authorization': _HEADERS['Authorization']},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def is_ready() -> bool:
    try:
        h = check_health()
        w = h.get('workers', {})
        return (w.get('idle', 0) + w.get('running', 0)) > 0
    except Exception:
        return False


_workers_confirmed = False


def ensure_workers_ready(timeout: int = 300):
    """Check workers once per session. Raises on failure."""
    global _workers_confirmed
    if _workers_confirmed:
        return
    if not wake_and_wait(timeout=timeout):
        raise RuntimeError(f'RunPod workers not ready after {timeout}s')
    _workers_confirmed = True


def wake_and_wait(timeout: int = 300, poll: float = 5.0) -> bool:
    """Wake up RunPod workers and wait until at least one is ready."""
    _ensure_config()
    if is_ready():
        return True

    # Send a minimal request to trigger cold start
    try:
        requests.post(
            f'{_BASE_URL}/run',
            json={'input': {'wake': True}},
            headers=_HEADERS,
            timeout=15,
        )
    except Exception:
        pass

    start = time.time()
    while time.time() - start < timeout:
        try:
            h = check_health()
            w = h.get('workers', {})
            if w.get('idle', 0) + w.get('running', 0) > 0:
                return True
        except Exception:
            pass
        time.sleep(poll)

    return False


def _submit_async(images_b64: list[str]) -> str:
    """Submit batch to /run, return job_id."""
    _ensure_config()
    resp = requests.post(
        f'{_BASE_URL}/run',
        json={'input': {'images_b64': images_b64}},
        headers=_HEADERS,
        timeout=30,
    )
    if resp.status_code == 400 and 'max body size' in resp.text:
        raise PayloadTooLarge(resp.text[:200])
    resp.raise_for_status()
    return resp.json()['id']


def _poll_job(job_id: str, timeout: float = 600) -> dict:
    """Poll /status/{job_id} until completed."""
    _ensure_config()
    start = time.time()
    interval = 2.0
    while time.time() - start < timeout:
        resp = requests.get(
            f'{_BASE_URL}/status/{job_id}',
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get('status')
        if status == 'COMPLETED':
            return data['output']
        if status == 'FAILED':
            raise RuntimeError(f"Job failed: {data.get('error', 'unknown')}")
        time.sleep(min(interval, 5.0))
        interval += 0.5

    raise TimeoutError(f'Job {job_id} timed out after {timeout}s')


def submit_and_wait(
    images_b64: list[str],
    timeout: float = 600,
    max_retries: int = 3,
) -> dict:
    """Submit a batch and wait for result, with retry + exponential backoff."""
    for attempt in range(max_retries):
        try:
            job_id = _submit_async(images_b64)
            return _poll_job(job_id, timeout)
        except requests.exceptions.HTTPError as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                if e.response is not None and e.response.status_code == 429:
                    time.sleep(wait)
                    continue
                time.sleep(wait)
            else:
                raise
        except PayloadTooLarge:
            raise
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise

    raise RuntimeError(f'Failed after {max_retries} attempts')


# ── High-level OCR ───────────────────────────────────────────

def ocr_pdf(
    pdf_path: str,
    dpi: int = 150,
    batch_size: int = 16,
    timeout: float = 600,
    max_retries: int = 3,
    progress_callback=None,
) -> list[dict]:
    """OCR an entire PDF via RunPod.

    Returns list of {'page': int (1-based), 'text': str} sorted by page.

    progress_callback(current_batch, total_batches, msg) is called per batch.
    """
    _ensure_config()
    ensure_workers_ready()

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    doc.close()

    all_page_indices = list(range(total_pages))
    raw_pages = {}  # page_idx -> raw page_data from RunPod

    # Process in batches
    batches = [
        all_page_indices[i:i + batch_size]
        for i in range(0, len(all_page_indices), batch_size)
    ]

    for batch_num, chunk_indices in enumerate(batches):
        if progress_callback:
            progress_callback(
                batch_num + 1,
                len(batches),
                f'OCR batch {batch_num + 1}/{len(batches)} '
                f'(pages {chunk_indices[0] + 1}-{chunk_indices[-1] + 1})',
            )

        images_b64 = render_pages(pdf_path, chunk_indices, dpi)

        try:
            output = submit_and_wait(images_b64, timeout, max_retries)
        except PayloadTooLarge:
            # Split batch in half and retry
            half = len(images_b64) // 2
            if half < 1:
                continue
            for sub_start in range(0, len(images_b64), half):
                sub_imgs = images_b64[sub_start:sub_start + half]
                sub_indices = chunk_indices[sub_start:sub_start + half]
                try:
                    sub_output = submit_and_wait(sub_imgs, timeout, max_retries)
                    for page_data, page_idx in zip(
                        sub_output.get('pages', []), sub_indices
                    ):
                        page_data['page'] = page_idx
                        raw_pages[page_idx] = page_data
                except Exception:
                    pass
            continue

        for page_data, page_idx in zip(output.get('pages', []), chunk_indices):
            page_data['page'] = page_idx
            raw_pages[page_idx] = page_data

    # Build results: text-only list + full raw data
    # Chandra2-vllm returns 'markdown' (full page text) and 'chunks' (structured blocks)
    results = []
    for idx in sorted(raw_pages.keys()):
        text = (
            raw_pages[idx].get('markdown')
            or raw_pages[idx].get('text')
            or ''
        ).strip()
        if text:
            results.append({'page': idx + 1, 'text': text})

    raw_result = {
        'pdf': os.path.basename(pdf_path),
        'processed_at': datetime.now().isoformat(),
        'total_pages': total_pages,
        'done_pages': len(raw_pages),
        'pages': sorted(raw_pages.values(), key=lambda p: p['page']),
    }

    return results, raw_result
