# Session 14: UI Pipeline Status, Context Menu, Ingestion Fixes

**Date:** 2026-04-14

## Summary

Desktop 앱 UX 개선 (파이프라인 상태 pill, 우클릭 컨텍스트 메뉴, PDF 뷰 탭)과 Zotero ingestion 버그 수정.

## Changes

### Paper List (가운데 패널)
- **Row padding 축소**: 8px → 2px, row height 32 → 26, 폰트 13 → 14px (공간 효율)
- **Status pill 재정의**: `wait`(pending), `OCR`(processed), `done`(biblio applied), `rev`(needs_review), `err`(failed), `—`(no PDF)
- **헤더 클릭 정렬**: `setSortingEnabled(True)`, 기본 Title 오름차순
- **우클릭 컨텍스트 메뉴**: status별 다음 액션 표시
  - pending → "Process OCR"
  - failed → "Retry OCR"
  - processed → "Extract Biblio" + "Open PDF"
  - review → "Review Biblio" + "Open PDF"
- **Extract Biblio**: 확인 다이얼로그 후 `claude -p --model claude-sonnet-4-6` 백그라운드 실행, 완료 시 auto-apply 시도
- **pill 실시간 갱신**: OCR 완료 시 `file_processed` 시그널로 해당 row만 업데이트

### Detail Panel (오른쪽 패널) 탭 재구성
- **Metadata 탭**: 기존 Metadata + File + Biblio 비교 카드 통합 (별도 Biblio 탭 제거)
- **PDF 탭** (신규): PyMuPDF로 PDF 페이지 이미지 렌더링, 로컬 없으면 Zotero 다운로드 버튼
- **Text 탭**: 기존 OCR 탭 이름 변경
- **PDF 캐시**: `~/.papermeister/pdf_cache/{zotero_key}/{filename}` — PaperFile.path 불변

### Process Window (OCR 처리 창)
- **Cancel 버튼**: `_cancelled` 플래그로 미시작 파일 skip, in-progress 완료 후 중단
- **서버 상태 폴링**: 하단 왼쪽에 RunPod worker 상태 5초 간격 표시 (QThread 기반)

### Ingestion 버그 수정

#### Title fallback 중복 매칭 (`ingestion.py`)
- **문제**: `fetch_zotero_collection_items`에서 zotero_key 매칭 실패 시 title로 fallback → 같은 제목의 다른 Zotero item에 attachment가 잘못 연결
- **수정**: title fallback에 `Paper.zotero_key == ''` 조건 추가 (이미 zotero_key가 있는 Paper는 별개 item)
- **데이터 복구**: 66개 misattached PaperFile을 올바른 Paper로 이동

#### Incremental sync attachment 누락 (`ingestion.py`)
- **문제**: incremental sync에서 parent item만 변경되면 attachment가 batch에 미포함 → Paper 생성되지만 PaperFile 없음
- **수정**: `sync_zotero_items`에 `zotero_client` 파라미터 추가, PaperFile 없으면 `zot.children()` API로 attachment 조회

#### Annotation 필터링 (`zotero_client.py`)
- **문제**: `_classify_raw_items`에서 `annotation` itemType을 필터링 안 함 → PDF 하이라이트/메모가 빈 Paper로 생성
- **수정**: `item_type not in ('note', 'annotation')` 조건으로 변경, 8개 annotation Paper 삭제

#### PDF-first file 선택 (`paper_service.py`)
- **문제**: `_row_from_paper`/`load_detail`이 ID 순으로 첫 파일 선택 → JSON sibling이 먼저면 primary가 됨
- **수정**: `_primary_file()` 헬퍼 — `.json`이 아닌 파일 우선 선택

## Files Modified

| File | Changes |
|------|---------|
| `desktop/views/paper_list.py` | context menu, status pill, sorting, row padding |
| `desktop/views/detail_panel.py` | tab restructure (Metadata+Biblio, PDF, Text), download panel |
| `desktop/windows/main_window.py` | context action handlers, biblio extraction, pill update |
| `desktop/services/paper_service.py` | `_primary_file()`, `done` status, `file_zotero_key` |
| `desktop/theme/qss.py` | PaperList font size, padding |
| `desktop/theme/tokens.py` | row height |
| `desktop/workers/zotero_sync.py` | pass `zotero_client` to sync |
| `papermeister/ingestion.py` | title fallback fix, children fetch |
| `papermeister/zotero_client.py` | annotation filter |
| `papermeister/ui/process_window.py` | cancel button, server status polling |
