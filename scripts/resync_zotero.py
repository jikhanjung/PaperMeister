#!/usr/bin/env python3
"""Zotero DB를 초기화하고 처음부터 전체 동기화를 수행합니다.

1) Zotero source에 속한 Paper, PaperFile, Author, Passage, Folder 삭제
2) 컬렉션 전체 동기화
3) 모든 컬렉션의 아이템 fetch (Paper + PaperFile 생성)

OCR 결과 JSON 캐시(~/.papermeister/ocr_json/)는 보존됩니다.
processed 상태 복원은 별도 스크립트(restore_processed.py 등)로 처리하세요.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papermeister.database import init_db
from papermeister.models import (
    Author, Folder, Paper, PaperFile, Passage, Source, db,
)
from papermeister.preferences import get_pref, set_pref
from papermeister.ingestion import (
    fetch_zotero_collection_items,
    get_or_create_zotero_source,
    sync_zotero_collections,
)
from papermeister.zotero_client import ZoteroClient


def main():
    init_db()

    user_id = get_pref('zotero_user_id', '')
    api_key = get_pref('zotero_api_key', '')
    if not user_id or not api_key:
        print('Error: Zotero credentials not configured.', file=sys.stderr)
        return 1

    # Find Zotero source
    source = Source.select().where(
        Source.source_type == 'zotero',
        Source.path == str(user_id),
    ).first()

    if source:
        # Count existing records
        zotero_folders = list(Folder.select().where(Folder.source == source))
        folder_ids = [f.id for f in zotero_folders]

        paper_count = Paper.select().where(Paper.folder_id.in_(folder_ids)).count() if folder_ids else 0
        pf_count = (PaperFile.select()
                    .join(Paper)
                    .where(Paper.folder_id.in_(folder_ids))
                    .count()) if folder_ids else 0

        print(f'현재 Zotero 데이터: {len(zotero_folders)} folders, {paper_count} papers, {pf_count} paperfiles')
        answer = input('모두 삭제하고 처음부터 동기화합니까? [y/N]: ').strip().lower()
        if answer != 'y':
            print('취소.')
            return 0

        # Delete in order: Passage → Author → PaperFile → Paper → Folder
        print('Zotero 데이터 삭제 중...')
        with db.atomic():
            if folder_ids:
                papers = list(Paper.select(Paper.id).where(Paper.folder_id.in_(folder_ids)))
                paper_ids = [p.id for p in papers]

                if paper_ids:
                    # Batch delete in chunks to avoid SQLite variable limit
                    chunk_size = 500
                    for i in range(0, len(paper_ids), chunk_size):
                        chunk = paper_ids[i:i + chunk_size]
                        Passage.delete().where(Passage.paper_id.in_(chunk)).execute()
                        Author.delete().where(Author.paper_id.in_(chunk)).execute()
                        PaperFile.delete().where(PaperFile.paper_id.in_(chunk)).execute()
                        Paper.delete().where(Paper.id.in_(chunk)).execute()

                Folder.delete().where(Folder.source == source).execute()

        # Reset library version to force full sync
        set_pref('zotero_library_version', None)

        print('삭제 완료.')
    else:
        print('기존 Zotero source 없음. 새로 생성합니다.')

    # Step 1: Sync collections
    print('\n=== Step 1: 컬렉션 동기화 ===')
    client = ZoteroClient(user_id, api_key)
    source = get_or_create_zotero_source(user_id)
    collections = client.get_collections()
    sync_zotero_collections(client, source, collections)
    print(f'  {len(collections)}개 컬렉션 동기화 완료.')

    # Step 2: Fetch items for all collections
    print('\n=== Step 2: 아이템 fetch ===')
    folders = list(Folder.select().where(
        Folder.source == source,
        Folder.zotero_key != '',
    ).order_by(Folder.name))

    total_new = 0
    for i, folder in enumerate(folders):
        new = fetch_zotero_collection_items(
            client, source, folder,
            progress_callback=None,
        )
        total_new += new
        status = f'  [{i + 1}/{len(folders)}] {folder.name}: {new} new'
        print(status)

    print(f'\n완료! 총 {total_new}개 Paper 생성.')

    # Summary
    folder_ids = [f.id for f in folders]
    paper_count = Paper.select().where(Paper.folder_id.in_(folder_ids)).count() if folder_ids else 0
    pf_count = (PaperFile.select()
                .join(Paper)
                .where(Paper.folder_id.in_(folder_ids))
                .count()) if folder_ids else 0
    print(f'결과: {len(folders)} folders, {paper_count} papers, {pf_count} paperfiles')

    return 0


if __name__ == '__main__':
    sys.exit(main())
