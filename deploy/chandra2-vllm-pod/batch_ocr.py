#!/usr/bin/env python3
"""Batch OCR processor for Chandra2-vLLM Pod.

Scans /workspace/pdfs/ for PDF files, renders pages to JPEG,
sends to local vLLM server, saves results as JSON.

Usage:
    python3 batch_ocr.py [--input-dir /workspace/pdfs] [--output-dir /workspace/ocr_json]
                         [--dpi 150] [--batch-size 1] [--vllm-url http://localhost:8000]
                         [--resume]

Output: {sha256_hash}.json per PDF, same format as PaperMeister's ocr_json.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import requests
from PIL import Image


def sha256_file(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(131072), b''):
            h.update(chunk)
    return h.hexdigest()


def render_page(doc, page_idx, dpi=150, quality=85):
    """Render a single PDF page to base64 JPEG."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = doc[page_idx].get_pixmap(matrix=mat)
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def ocr_page(image_b64, vllm_url, timeout=120):
    """Send one page image to vLLM and return markdown text."""
    resp = requests.post(
        f'{vllm_url}/v1/chat/completions',
        json={
            'model': 'chandra',
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {
                    'url': f'data:image/jpeg;base64,{image_b64}',
                }},
            ]}],
            'max_tokens': 12384,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get('choices', [])
    if choices:
        return choices[0].get('message', {}).get('content', '')
    return ''


def wait_for_vllm(vllm_url, timeout=300):
    """Wait for vLLM server to become ready."""
    print(f'[INIT] Waiting for vLLM server at {vllm_url} ...', flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f'{vllm_url}/health', timeout=5)
            if resp.status_code == 200:
                print(f'[INIT] vLLM server ready ({time.time() - start:.1f}s)', flush=True)
                return True
        except Exception:
            pass
        time.sleep(5)
    print(f'[INIT] ERROR: vLLM not ready after {timeout}s', flush=True)
    return False


def find_pdfs(input_dir):
    """Recursively find all PDF files."""
    pdfs = []
    for root, dirs, files in os.walk(input_dir):
        for f in sorted(files):
            if f.lower().endswith('.pdf'):
                pdfs.append(os.path.join(root, f))
    return pdfs


def process_pdf(pdf_path, output_dir, vllm_url, dpi=150, file_idx=0, total_files=0):
    """Process a single PDF: render all pages, OCR each, save JSON."""
    prefix = f'[{file_idx}/{total_files}]' if total_files else ''
    filename = os.path.basename(pdf_path)

    # Compute hash
    file_hash = sha256_file(pdf_path)
    out_path = os.path.join(output_dir, f'{file_hash}.json')

    print(f'{prefix} {filename}', flush=True)
    print(f'{prefix}   hash: {file_hash[:16]}...', flush=True)

    # Open PDF
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f'{prefix}   ERROR opening PDF: {e}', flush=True)
        return None, str(e)

    total_pages = doc.page_count
    print(f'{prefix}   pages: {total_pages}', flush=True)

    raw_pages = []
    failed_pages = 0
    t0 = time.time()

    for page_idx in range(total_pages):
        page_t0 = time.time()
        try:
            image_b64 = render_page(doc, page_idx, dpi)
            text = ocr_page(image_b64, vllm_url)
            page_elapsed = time.time() - page_t0
            raw_pages.append({
                'page': page_idx,
                'markdown': text.strip(),
                'duration_ms': int(page_elapsed * 1000),
            })
            if (page_idx + 1) % 10 == 0 or page_idx == 0:
                print(f'{prefix}   page {page_idx + 1}/{total_pages} ({page_elapsed:.1f}s)', flush=True)
        except Exception as e:
            failed_pages += 1
            print(f'{prefix}   page {page_idx + 1} ERROR: {e}', flush=True)
            raw_pages.append({
                'page': page_idx,
                'markdown': '',
                'error': str(e),
            })

    doc.close()
    elapsed = time.time() - t0

    # Build result (same format as PaperMeister ocr_json)
    result = {
        'pdf': filename,
        'hash': file_hash,
        'processed_at': datetime.now().isoformat(),
        'total_pages': total_pages,
        'done_pages': total_pages - failed_pages,
        'failed_pages': failed_pages,
        'elapsed_seconds': round(elapsed, 1),
        'pages': sorted(raw_pages, key=lambda p: p['page']),
    }

    # Save
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    pages_per_sec = total_pages / elapsed if elapsed > 0 else 0
    print(f'{prefix}   done: {total_pages - failed_pages}/{total_pages} pages, '
          f'{elapsed:.1f}s ({pages_per_sec:.2f} pages/s) → {os.path.basename(out_path)}',
          flush=True)

    return file_hash, None


def main():
    parser = argparse.ArgumentParser(description='Batch OCR for Chandra2-vLLM Pod')
    parser.add_argument('--input-dir', default='/workspace/pdfs', help='Directory with PDF files')
    parser.add_argument('--output-dir', default='/workspace/ocr_json', help='Output directory for JSON results')
    parser.add_argument('--vllm-url', default='http://localhost:8000', help='vLLM server URL')
    parser.add_argument('--dpi', type=int, default=150)
    parser.add_argument('--resume', action='store_true', help='Skip PDFs that already have output JSON')
    parser.add_argument('--limit', type=int, default=0, help='Process at most N files (0=all)')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Wait for vLLM
    if not wait_for_vllm(args.vllm_url):
        return 1

    # Find PDFs
    pdfs = find_pdfs(args.input_dir)
    print(f'\n[SCAN] Found {len(pdfs)} PDF files in {args.input_dir}', flush=True)

    if not pdfs:
        print('[SCAN] Nothing to process.', flush=True)
        return 0

    # Resume: skip already processed
    if args.resume:
        existing_hashes = set()
        for f in os.listdir(args.output_dir):
            if f.endswith('.json'):
                existing_hashes.add(f[:-5])  # remove .json

        before = len(pdfs)
        filtered = []
        for pdf_path in pdfs:
            h = sha256_file(pdf_path)
            if h not in existing_hashes:
                filtered.append(pdf_path)
        pdfs = filtered
        print(f'[SCAN] Resume: {before - len(pdfs)} already done, {len(pdfs)} remaining', flush=True)

    if args.limit > 0:
        pdfs = pdfs[:args.limit]
        print(f'[SCAN] --limit {args.limit} applied', flush=True)

    # Process
    total = len(pdfs)
    ok = 0
    failed = 0
    total_pages = 0
    global_t0 = time.time()

    print(f'\n{"="*60}', flush=True)
    print(f'[START] Processing {total} PDFs', flush=True)
    print(f'{"="*60}\n', flush=True)

    for i, pdf_path in enumerate(pdfs, 1):
        file_hash, err = process_pdf(
            pdf_path, args.output_dir, args.vllm_url,
            dpi=args.dpi, file_idx=i, total_files=total,
        )
        if err:
            failed += 1
        else:
            ok += 1
            # Count pages from the output
            json_path = os.path.join(args.output_dir, f'{file_hash}.json')
            try:
                with open(json_path) as f:
                    data = json.load(f)
                total_pages += data.get('done_pages', 0)
            except Exception:
                pass
        print('', flush=True)

    global_elapsed = time.time() - global_t0

    print(f'{"="*60}', flush=True)
    print(f'[DONE]', flush=True)
    print(f'  Files:  {ok} ok, {failed} failed, {total} total', flush=True)
    print(f'  Pages:  {total_pages}', flush=True)
    print(f'  Time:   {global_elapsed:.1f}s ({global_elapsed/60:.1f}m)', flush=True)
    if total_pages > 0:
        print(f'  Speed:  {total_pages/global_elapsed:.2f} pages/s', flush=True)
        print(f'  Cost:   ~${global_elapsed/3600 * 0.39:.2f} (A40 @ $0.39/hr)', flush=True)
    print(f'  Output: {args.output_dir}', flush=True)
    print(f'{"="*60}', flush=True)


if __name__ == '__main__':
    sys.exit(main() or 0)
