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

# Verify TLS against the OS trust store: the lab network re-signs with its own
# root CA, which certifi does not carry. Must run before any pyzotero call.
from papermeister.nettls import install_system_trust

install_system_trust()

from papermeister.database import init_db
from papermeister.ingestion import hash_file
from papermeister.models import Paper, PaperFile
from papermeister.paths import OCR_JSON_DIR
from papermeister.preferences import get_pref
from papermeister.text_extract import ocr_json_filename
from papermeister.zotero_client import ZoteroClient

OCR_JSON_DIR = OCR_JSON_DIR

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
        json_name = ocr_json_filename(pf)
        json_path = os.path.join(OCR_JSON_DIR, json_name)
        if not os.path.exists(json_path):
            continue
        PaperFile.create(
            paper=pf.paper,
            path=json_name,
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
    parser.add_argument('--execute', action='store_true',
                        help='실제 업로드. 기본은 dry-run 미리보기.')
    parser.add_argument('--sleep', type=float, default=0.1, help='업로드 간 sleep (초)')
    args = parser.parse_args()
    args.dry_run = not args.execute

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

    # 이미 매칭되는 JSON PaperFile이 있는 PDF 제외.
    # multi-PDF paper 지원: paper 단위가 아니라 (paper_id, expected_json_name) 쌍
    # 매칭으로 PDF #2/#3 처럼 JSON이 아직 안 올라간 sibling은 후보로 남게 함.
    existing_jsons = set()
    for jpf in PaperFile.select(PaperFile.paper, PaperFile.path).where(
        PaperFile.path.endswith('.json')
    ):
        existing_jsons.add((jpf.paper_id, jpf.path))

    todo = [
        pf for pf in candidates
        if (pf.paper_id, ocr_json_filename(pf)) not in existing_jsons
    ]
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
        json_name = ocr_json_filename(pf)
        json_path = os.path.join(OCR_JSON_DIR, json_name)
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
                path=json_name,
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

    log('\n=== 결과 ===')
    log(f'성공: {success}')
    log(f'standalone (skip): {standalone}')
    log(f'실패: {failed}')
    log(f'JSON 캐시 없음: {skipped}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
