#!/usr/bin/env python3
"""모든 OCR JSON을 Zotero PDF의 sibling attachment로 업로드.

대상: status='processed' + hash != '' + zotero_key != '' 인 PaperFile 중,
      같은 Paper에 .json sibling PaperFile이 아직 없는 것.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import Paper, PaperFile, db
from papermeister.preferences import get_pref
from papermeister.ingestion import hash_file
from papermeister.zotero_client import ZoteroClient

OCR_JSON_DIR = os.path.expanduser('~/.papermeister/ocr_json')

# 이전에 수동 업로드한 항목들 (PDF zotero_key → JSON zotero_key)
MANUAL_BACKFILL = {
    'IWENPCSB': 'GA96HPB5',
    'YEHHZHAD': 'Q9XFDK8B',
    'DYRPEV6E': '3QJXCQKP',
}


def log(msg):
    print(msg, flush=True)


def backfill_manual(paperfiles_by_key):
    """이전에 수동 업로드한 3개에 대해 PaperFile 행 생성."""
    created = 0
    for pdf_key, json_key in MANUAL_BACKFILL.items():
        pf = paperfiles_by_key.get(pdf_key)
        if not pf or not pf.hash:
            continue
        # 이미 sibling JSON PaperFile 있으면 skip
        existing = (
            PaperFile.select()
            .where((PaperFile.paper == pf.paper) & (PaperFile.path.endswith('.json')))
            .first()
        )
        if existing:
            continue
        json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
        if not os.path.exists(json_path):
            continue
        PaperFile.create(
            paper=pf.paper,
            path=os.path.basename(json_path),
            hash=hash_file(json_path),
            status='processed',
            zotero_key=json_key,
        )
        created += 1
        log(f'  backfill: {pdf_key} → JSON PaperFile created (key={json_key})')
    return created


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='0 = 전체')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--sleep', type=float, default=0.1, help='업로드 간 sleep (초)')
    args = parser.parse_args()

    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        log('Error: Zotero credentials not configured.')
        return 1

    client = ZoteroClient(user_id, api_key)

    # processed PDF PaperFiles (zotero_key + hash 있음)
    candidates = list(
        PaperFile.select(PaperFile, Paper)
        .join(Paper)
        .where(
            (PaperFile.status == 'processed')
            & (PaperFile.hash != '')
            & (PaperFile.zotero_key != '')
            & (~PaperFile.path.endswith('.json'))  # PDF만
        )
    )
    log(f'전체 후보 PaperFile (PDF, processed): {len(candidates)}')

    # Backfill manual uploads
    by_key = {pf.zotero_key: pf for pf in candidates}
    backfilled = backfill_manual(by_key)
    if backfilled:
        log(f'  → {backfilled}개 백필 완료')

    # 같은 paper에 이미 JSON sibling PaperFile 있는 것 제외
    paper_ids_with_json = set(
        pf.paper_id for pf in PaperFile.select(PaperFile.paper).where(
            PaperFile.path.endswith('.json')
        )
    )

    todo = [pf for pf in candidates if pf.paper_id not in paper_ids_with_json]
    log(f'업로드 대상: {len(todo)}')

    if args.limit > 0:
        todo = todo[:args.limit]
        log(f'  --limit {args.limit} 적용 → {len(todo)}')

    if args.dry_run:
        log('[DRY-RUN] 종료')
        return 0

    success = 0
    skipped = 0
    standalone = 0
    failed = 0

    for i, pf in enumerate(todo, 1):
        json_path = os.path.join(OCR_JSON_DIR, f'{pf.hash}.json')
        if not os.path.exists(json_path):
            skipped += 1
            continue

        try:
            new_key = client.upload_sibling_attachment(pf.zotero_key, json_path)
            if not new_key:
                failed += 1
                log(f'[{i}/{len(todo)}] FAIL (no key returned): {pf.paper.title[:60]}')
                continue

            PaperFile.create(
                paper=pf.paper,
                path=os.path.basename(json_path),
                hash=hash_file(json_path),
                status='processed',
                zotero_key=new_key,
            )
            success += 1
            if i % 50 == 0 or i <= 5:
                log(f'[{i}/{len(todo)}] ✓ {pf.paper.title[:60]} (json={new_key})')
        except RuntimeError as e:
            # standalone PDF (no parent) — skip, do not create new top-level item
            if 'standalone' in str(e):
                standalone += 1
                log(f'[{i}/{len(todo)}] SKIP standalone: {pf.paper.title[:60]}')
            else:
                failed += 1
                log(f'[{i}/{len(todo)}] ERROR: {pf.paper.title[:50]} — {e}')
        except Exception as e:
            failed += 1
            log(f'[{i}/{len(todo)}] ERROR: {pf.paper.title[:50]} — {e}')

        if args.sleep > 0:
            time.sleep(args.sleep)

    log(f'\n=== 결과 ===')
    log(f'성공: {success}')
    log(f'standalone (skip): {standalone}')
    log(f'실패: {failed}')
    log(f'JSON 캐시 없음: {skipped}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
