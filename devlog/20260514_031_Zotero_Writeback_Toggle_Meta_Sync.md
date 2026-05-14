# 20260514_031 — Zotero write-back 토글, evaluate 버그 픽스, OCR JSON cross-machine sync

## 컨텍스트

세션 16 끝나고 어제 폴더 일괄 처리(`Antarctic archaeocyath` 등)를 돌리던 중 두 가지 문제가 드러남:

1. **403 Forbidden**: read-only API 키로 Zotero PATCH 시도하다 raw traceback이 UI까지 새어 나옴
2. **paper 2243(Rode et al 2003) override_conflict 오판**: UI 비교 패널은 모든 필드가 동일하게 보이는데 evaluate는 needs_review로 떨궈버림

추가로 사용자가 머신 간 작업 이어가기를 원함 → 다른 머신에서 OCR/biblio 다시 돌리지 않게 Zotero가 source of truth 역할 하도록 보강.

## 변경 사항

### 1. Zotero write-back 토글 + 403 핸들링

- `papermeister/preferences.py`에 새 pref `zotero_writeback_enabled` (기본 OFF) + `zotero_upload_ocr_json` UI 노출
- `preferences_dialog.py`에 두 체크박스 추가
- `biblio_reflect.apply()` + `biblio_service.apply_merged()`: `paper.zotero_key`가 있어도 토글 OFF면 local-only 경로로 우회
- `zotero_writeback._update_item()` 래퍼 신설 — pyzotero `UserNotAuthorised`를 `ZoteroWriteAccessDenied(PermissionError)`로 변환하면서 "키 권한 새로 발급하거나 토글 OFF" 안내 메시지 동봉
- desktop `_on_biblio_extracted`에서 `ZoteroWriteAccessDenied` catch → status bar에 친절 메시지

### 2. evaluate() 버그 두 건 픽스

#### Bug A — `_normalize_name` 비대칭

```
"Smith, John"  → "smith john"   (콤마 경로만 풀어줬음)
"John Smith"   → "john smith"   (공백 경로는 그대로)
```

같은 사람이 다른 정규화 결과를 내서 evaluate가 mismatch로 판정 → override_conflict. UI의 `format_author_display`가 양쪽을 모두 `"Smith, John"`으로 렌더했기 때문에 "UI 동일한데 evaluate는 conflict"의 비대칭 발생.

수정: 공백 구분 케이스도 마지막 토큰을 surname으로 보고 `"last first"` 순서로 정규화. `Rode, Alycia L.` ↔ `Alycia L. Rode` 모두 `"rode alycia l."`.

#### Bug B — empty biblio field = no conflict

evaluate의 `all_match`는 단순 동치(`biblio.x == paper.x`)였음. biblio가 추출 못 한 필드(빈 값)와 paper의 값이 mismatch로 잡혔음:

```python
# Before
all_match = (biblio.title == paper.title) and ...  # 빈 biblio가 paper 값과 충돌
```

```python
# After
def _no_conflict(paper_val, biblio_val):
    bv = (biblio_val or '').strip()
    return not bv or bv == (paper_val or '').strip()
```

"biblio가 해당 필드에 할 말 없음 = 충돌 아님" 의미론 정착. year/authors도 동일 패턴.

### 3. OCR 직전 sibling JSON 선조회

OCR API 호출 전에 `~/.papermeister/ocr_json/{pdf_hash}.json` 캐시 miss이면 → 같은 paper에 `{hash}.json` 이름의 sibling PaperFile이 있는지 DB 조회 → 있으면 Zotero에서 받아 캐시에 atomic write → OCR 우회.

진입점은 두 곳이라 둘 다 hook:
- `text_extract.process_paper_file` (serverless/pod 모드)
- `process_window._prepare_file` (wrapper 모드) — 첫 시도에서 누락돼 사용자가 지적해줌

pyzotero `_zot.file(key)`가 JSON attachment에 대해서는 raw bytes가 아니라 이미 파싱된 dict를 반환. `decode → json.loads` 경로가 `'dict' object has no attribute 'decode'`로 터졌고 `isinstance(content, dict)` 분기 추가로 해결.

### 4. `papermeister_meta` — OCR JSON에 biblio 상태 임베드

다른 머신에서 OCR + biblio 재실행을 피하기 위해 JSON 안에 작은 메타 섹션을 박아넣음:

```json
{
  "pages": [...],
  "papermeister_meta": {
    "schema_version": 1,
    "biblio_state": "applied" | "auto_committed",
    "biblio_source": "llm-sonnet" | "llm-haiku" | "llm-qwen" | ...,
    "biblio_applied_at": "2026-05-14T20:57:18+00:00"
  }
}
```

**쓰기 측** — `text_extract.record_biblio_applied(biblio)` 헬퍼 신설. `PaperBiblio.status`가 `applied`/`auto_committed`로 넘어가는 모든 경로(5군데)에서 one-line으로 호출:

- `biblio_reflect.apply()` (Zotero branch)
- `biblio_reflect._local_apply()`
- `biblio_reflect.apply_single()`
- `desktop/services/biblio_service._apply_merged_zotero()`
- `desktop/services/biblio_service._apply_merged_local()`

내부 흐름: local JSON 갱신 → `zotero_upload_ocr_json` ON이면 → `zotero_client.replace_attachment_file()` 호출.

**Zotero in-place file replace** — attachment key를 보존하면서 file content만 교체. pyzotero `upload_attachments`에 기존 key + 현재 md5(If-Match) 넘기면 `_create_prelim`이 skip되고 `_get_auth` → S3 PUT 경로로 진입. delete+upload보다 깨끗 (Zotero history 보존, PaperFile.zotero_key 그대로).

대신 file content가 바뀌었으니 `PaperFile.hash`는 재계산해서 sibling row에 반영.

**읽기 측** — `biblio.load_ocr_meta()` + `class BiblioAlreadyApplied(Exception)`. `extract_biblio_llm()` 진입에서 meta 체크:

```python
meta = load_ocr_meta(file_hash)
if meta and meta.get('biblio_state') in ('applied', 'auto_committed'):
    raise BiblioAlreadyApplied(meta)
```

desktop의 두 캘러는 catch해서 `{'skipped': True, 'meta': ...}` 시그널 → `_on_biblio_extracted`가 skip 분기로 빠져서 status bar에 `"Biblio already applied on Zotero (llm-sonnet) — skipped LLM for paper N"` 표시 + pill `done`으로 갱신.

## Cross-machine 시나리오

머신 A:
1. OCR → biblio 추출 → apply
2. `record_biblio_applied`가 JSON에 meta 박고 in-place로 Zotero에 푸시

머신 B (DB 비어있음, OCR 캐시 없음):
1. Zotero pull sync → Paper/PaperFile/PaperFolder rows 재구성 (JSON sibling 포함)
2. Process Folder → OCR 단계에서 sibling-fetch로 Zotero JSON 받음 (meta 포함)
3. 자동 큐가 biblio 추출 시도 → `extract_biblio_llm`이 meta 보고 `BiblioAlreadyApplied` raise → LLM 호출 0
4. status bar: `"Biblio already applied on Zotero — skipped LLM"` + pill `done`

OCR API + LLM API 호출 0회로 cross-machine sync 완성.

## 운영상 발견

- **403 → ZoteroWriteAccessDenied**: pyzotero `UserNotAuthorised`는 메시지가 wall-of-text라 UI에 그대로 새면 안 됨. 래퍼로 한 번 걸러 "키 갱신 vs 토글 OFF" 안내까지 동봉
- **author shortfall 잘못 트리거됐던 paper 2243**: bug A 픽스로 evaluate가 `already_complete` skip으로 정상 분류
- **wrapper 파이프라인이 별도 cache 체크를 가짐**: `text_extract`만 고치고 끝낸 줄 알았는데 wrapper mode는 `process_window._prepare_file`이 자체 캐시 체크 + 곧장 wrapper queue로 보냄. 사용자가 `Antarctic archaeocyath` 테스트 로그로 잡아줌

## 파일

```
papermeister/preferences.py             — (no change, just new pref keys)
papermeister/ui/preferences_dialog.py   — write-back / upload JSON 체크박스
papermeister/biblio_reflect.py          — pref gating, _normalize_name fix, evaluate _no_conflict, record_biblio_applied hooks (×3)
papermeister/biblio.py                  — load_ocr_meta, BiblioAlreadyApplied, extract_biblio_llm early-skip
papermeister/zotero_writeback.py        — ZoteroWriteAccessDenied wrapper
papermeister/zotero_client.py           — replace_attachment_file
papermeister/text_extract.py            — _try_fetch_sibling_json, record_biblio_applied, PaperFile.hash refresh
papermeister/ui/process_window.py       — sibling fetch in _prepare_file (wrapper mode)
desktop/services/biblio_service.py      — pref gating, record_biblio_applied hooks (×2)
desktop/windows/main_window.py          — BiblioAlreadyApplied catch, ZoteroWriteAccessDenied catch, skip branch
```

## 미정

- `extract_biblio.py` CLI는 별도 entry point가 있지만 `extract_biblio_llm()`를 직접 안 쓰는 듯 (오늘 짧게 확인). 다음에 확인 + 동일 캐치 패턴 적용 필요할 수 있음
- 머신 B에서 PaperBiblio row가 없는 상태로 끝남 (skip이라 row 안 만듦). "이 paper는 처리 끝났다"가 JSON meta에만 살아있고 local DB에는 indicator 없음. 필요해지면 placeholder PaperBiblio 도입 검토
- 라이브 검증: write-access 키로 갱신했고 sibling-fetch + JSON in-place replace까지 한 흐름은 테스트 진행 중. paper 2243 already_complete 동작은 단위로 확인됨
