#!/usr/bin/env python3
"""Diagnose the ocrserver Qwen LLM endpoint latency (P11 timeout triage).

Sends increasingly large requests and times each, so we can tell whether the
references timeout is a cold start, a slow/contended GPU, or just batch size.

Run it a few times — the FIRST call may be a cold model load (slow), later
calls warm. Run it while OCR is idle vs busy to see contention.

    python scripts/probe_qwen.py                 # tiny → small → medium
    python scripts/probe_qwen.py --timeout 600   # give a cold start room
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.preferences import get_pref


def probe(url, label, prompt, max_tokens, timeout):
    import requests
    full = f'{url.rstrip("/")}/llm/v1/chat/completions'
    t0 = time.monotonic()
    try:
        resp = requests.post(full, json={
            'model': 'qwen',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': 0.1,
            'chat_template_kwargs': {'enable_thinking': False},
        }, timeout=(10, timeout))
    except Exception as exc:
        dt = time.monotonic() - t0
        print(f'  {label:<22} FAILED after {dt:6.1f}s: {type(exc).__name__}: {str(exc)[:80]}')
        return None
    dt = time.monotonic() - t0
    if resp.status_code != 200:
        print(f'  {label:<22} HTTP {resp.status_code} in {dt:6.1f}s: {resp.text[:120]}')
        return dt
    out = resp.json()['choices'][0]['message']['content']
    # rough output token estimate
    toks = max(1, len(out) // 4)
    rate = toks / dt if dt else 0
    print(f'  {label:<22} {dt:6.1f}s  (~{toks} out tok, ~{rate:.1f} tok/s)')
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='', help='Override server URL (else from preferences)')
    ap.add_argument('--timeout', type=int, default=300, help='Per-request read timeout (s)')
    args = ap.parse_args()

    url = args.url or get_pref('ocr_pod_url', '')
    if not url:
        print('No server URL (set ocr_pod_url in Preferences or pass --url).')
        return
    print(f'Probing LLM at {url}  (read timeout {args.timeout}s)\n')

    one_ref = (
        'Parse this reference into a JSON array with fields raw, authors, year, '
        'title, container, volume, issue, pages, doi, type. Output ONLY JSON.\n\n'
        'Smith, J. A. 2004. On trilobite eyes. Journal of Paleontology 41(2), 123-145.'
    )
    five_refs = one_ref + '\n' + '\n'.join(
        f'Doe, J{i}. {2000+i}. Title number {i}. Journal {i}, {i}-{i+10}.'
        for i in range(4))

    probe(url, 'trivial (hi, 8 tok)', 'Reply with just: ok', 8, args.timeout)
    probe(url, '1 reference', one_ref, 512, args.timeout)
    probe(url, '5 references', five_refs, 1500, args.timeout)
    print('\nIf even the trivial call is slow/fails → the model is cold or the '
          'GPU is busy (e.g. OCR running), not a batch-size problem.')


if __name__ == '__main__':
    main()
