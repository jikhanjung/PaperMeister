#!/usr/bin/env python3
"""Zotero storage에서 PDF hash를 계산하고, OCR 캐시 존재 여부로 상태를 업데이트합니다.

1) PaperFile.zotero_key로 storage 디렉토리에서 PDF 찾기
2) SHA256 hash 계산 → PaperFile.hash 저장
3) ~/.papermeister/ocr_json/{hash}.json 존재하면 status='processed'
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import PaperFile, db

STORAGE_DIR = '/nas/JikhanJung/1. Large Data/storage'
OCR_JSON_DIR = os.path.expanduser('~/.papermeister/ocr_json')


def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(131072), b''):
            h.update(chunk)
    return h.hexdigest()


def find_pdf(zotero_key):
    """Find PDF file in storage directory by zotero_key."""
    dir_path = os.path.join(STORAGE_DIR, zotero_key)
    if not os.path.isdir(dir_path):
        return None
    for fname in os.listdir(dir_path):
        if fname.lower().endswith('.pdf'):
            return os.path.join(dir_path, fname)
    return None


def log(msg):
    print(msg, flush=True)


def main():
    init_db()

    paperfiles = list(
        PaperFile.select().where(PaperFile.zotero_key != '')
    )
    log(f'총 PaperFile: {len(paperfiles)}개')

    found = 0
    not_found = 0
    hash_updated = 0
    ocr_exists = 0
    already_processed = 0
    errors = 0

    batch = []
    batch_size = 500

    for i, pf in enumerate(paperfiles):
        if (i + 1) % 1000 == 0:
            log(f'  [{i + 1}/{len(paperfiles)}] found={found} hash={hash_updated} ocr={ocr_exists}')

        pdf_path = find_pdf(pf.zotero_key)
        if not pdf_path:
            not_found += 1
            continue

        found += 1

        try:
            file_hash = sha256_file(pdf_path)
        except Exception as e:
            errors += 1
            log(f'  ERROR hashing {pf.zotero_key}: {e}')
            continue

        changed = False

        # Update hash
        if pf.hash != file_hash:
            pf.hash = file_hash
            hash_updated += 1
            changed = True

        # Check OCR cache
        ocr_path = os.path.join(OCR_JSON_DIR, f'{file_hash}.json')
        if os.path.exists(ocr_path):
            ocr_exists += 1
            if pf.status != 'processed':
                pf.status = 'processed'
                changed = True
            else:
                already_processed += 1
        else:
            if pf.status == 'processed':
                # OCR 캐시 없는데 processed면 pending으로
                pf.status = 'pending'
                changed = True

        if changed:
            batch.append(pf)

        if len(batch) >= batch_size:
            with db.atomic():
                for p in batch:
                    p.save()
            batch.clear()

    # Flush remaining
    if batch:
        with db.atomic():
            for p in batch:
                p.save()

    log(f'\n=== 결과 ===')
    log(f'총 PaperFile:     {len(paperfiles)}')
    log(f'PDF 찾음:         {found}')
    log(f'PDF 못 찾음:      {not_found}')
    log(f'Hash 업데이트:    {hash_updated}')
    log(f'OCR 캐시 있음:    {ocr_exists}')
    log(f'에러:             {errors}')

    # Status summary
    from peewee import fn
    status_counts = (
        PaperFile.select(PaperFile.status, fn.COUNT(PaperFile.id))
        .group_by(PaperFile.status)
        .tuples()
    )
    log(f'\n=== PaperFile 상태 ===')
    for status, count in status_counts:
        log(f'  {status}: {count}')


if __name__ == '__main__':
    main()
