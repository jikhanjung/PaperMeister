# 058 — OCR 재처리 견고화: force 재OCR, 빈 결과 failed, 레거시 캐시 rename

> 세션 44 (2026-06-09). 전체 라이브러리 biblio 운영 준비 중 "OCR이 된 줄 알았는데
> biblio가 'No OCR pages found'로 실패"하는 케이스들을 추적하면서 나온 픽스 모음.

## 1. 빈 OCR 결과를 'processed'가 아닌 'failed'로 (commit `d73f221`)

**문제**: OCR 서버가 0페이지/텍스트 없음(파싱 불가 또는 이미지 전용 PDF)을 반환해도
`process_paper_file`이 'processed'로 마킹 → 0페이지 캐시 + passage 없음. 나중에 biblio
추출이 "No OCR pages found"로 실패하는데 겉보기엔 OCR 완료 논문.

**수정**: 결과에 non-empty page text가 하나도 없으면 `status='failed'`
(failure_reason=`ocr_empty`). 기존 적체 4편은 `scripts/reset_empty_ocr.py`(빈 캐시
삭제 + pending 리셋, dry-run 기본)로 정리 후 재OCR.

## 2. failed PDF 재OCR 시 `force=true` (commit `09e233d`)

서버 wrapper가 `force=true` 폼 옵션(해시에 대한 기존 JSON이 있어도 재OCR)을 지원하게
된 것에 맞춰 클라이언트 전 경로에 force 플래그 배선:

- `wrapper_submit(force)` → POST form에 `force=true`
- `ocr_pdf` / `_wrapper_ocr_pdf` 통과
- `process_paper_file(force)` → 로컬 캐시 + Zotero sibling JSON shortcut 모두 무시
- `ProcessWorker.force_ids` 셋 (wrapper 파이프라인 `_prepare_file`에서도 캐시 재사용
  차단) → `ProcessWindow.start`로 전달

**적용 정책**: desktop 우클릭 "Retry OCR"(단건) + Process Folder의 `failed_ids`만
force. 일반 pending Process는 기존대로 캐시 사용. 1의 `ocr_empty` failed들이 빈 캐시를
다시 쓰는 루프를 막는 짝 픽스.

## 3. 레거시 `{sha256}.json` 캐시 잔존분 rename (commit `1a827bf`)

1970s 논문 5편(캐시 파일 8개)이 옛 `{sha256}.json` 캐시명을 유지하고 있었음.
**원인**: 세션 42 파일명 마이그레이션(`rename_ocr_json.py`)은 JSON PaperFile row를
PDF와 짝지어 처리하는데, 이들은 OCR JSON이 Zotero에 업로드된 적이 없어 JSON sibling이
없음 → 스킵됨. `load_ocr_pages`는 `*.{hash8}.json` glob이라 이들을 못 찾음 → biblio
추출이 "No OCR pages found"로 실패.

`scripts/rename_legacy_cache.py` 신설 — 캐시 디렉토리만 스캔해 새 규약
`{pdf_basename}.{hash8}.json`으로 rename (cache-only, idempotent, dry-run 기본).

## 메모

- 1·3 둘 다 증상은 같은 "No OCR pages found"였지만 원인은 다름(빈 캐시 vs 파일명
  미스매치). biblio 실패 메시지가 진행창에 표면화된 것(devlog 057 §3)이 진단 시작점.
- force 재OCR은 서버 쪽 `force` 핸들링이 전제 — 서버 리포에 이미 반영됨.
