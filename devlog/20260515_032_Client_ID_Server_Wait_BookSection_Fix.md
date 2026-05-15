# 20260515_032 — OCR wrapper client_id, server-load wait, bookSection 400 fix

## 컨텍스트

세션 17 마치고 사용자가 `Antarctic archaeocyath` 컬렉션으로 라이브 검증 들어감. 두 가지가 연쇄로 드러남:

1. **sibling JSON pre-fetch 작동 안 함** (wrapper 모드) — 세션 17의 hook이 `text_extract.process_paper_file`에만 있었고 wrapper 파이프라인은 `process_window._prepare_file`에서 자체 cache 체크 후 곧장 wrapper queue로 가서 발동 기회 없었음. 사용자가 로그로 잡아줌
2. **paper 4315 (Geyer 2019, bookSection)에서 400 `'publicationTitle' is not a valid field for type 'bookSection'`** — Zotero PATCH가 itemType별로 다른 container-title 필드명을 요구하는데 코드는 무조건 `publicationTitle`로 송신

추가로 두 가지 개선 요청:
- "서버에 다른 사람 잡 돌고 있으면 미리 기다리기" — 서버 부하 검토
- "클라이언트 ID 같은 거" — 서버 dedup 풀 활용 + wait discrimination

## 변경 사항

### 1. sibling JSON fetch — 두 가지 픽스

#### dict vs bytes 분기

pyzotero `_zot.file(key)`는 attachment의 content-type을 sniff해서 JSON이면 이미 파싱된 dict를 반환. 우리는 raw bytes 가정으로 `decode → json.loads` 해서 `'dict' object has no attribute 'decode'`로 터졌음.

```python
content = client._zot.file(sibling.zotero_key)
if isinstance(content, dict):
    raw_result = content
elif isinstance(content, bytes):
    raw_result = json.loads(content.decode('utf-8'))
else:
    raw_result = json.loads(content)
```

#### wrapper 파이프라인에도 적용

`_prepare_file`은 OCR 진입점이지만 세션 17에서 빠뜨림. `_load_ocr_json` 직후 `_try_fetch_sibling_json` 호출 추가.

### 2. `papermeister_meta` — OCR JSON 안에 biblio 상태 임베드

머신 A→B sync 시나리오: A에서 biblio apply 끝났는데 B에서 OCR JSON sibling-fetch 후 다시 LLM 추출해 버리는 낭비를 막기 위해, JSON 안에 작은 메타 박아서 상태 전달.

```json
{
  "pages": [...],
  "papermeister_meta": {
    "schema_version": 1,
    "biblio_state": "applied" | "auto_committed",
    "biblio_source": "llm-sonnet" | "llm-haiku" | "llm-qwen" | ...,
    "biblio_applied_at": "2026-05-15T03:51:18+00:00"
  }
}
```

**쓰기 측** — `text_extract.record_biblio_applied(biblio)` 헬퍼. `PaperBiblio.status`가 `applied`/`auto_committed`로 넘어가는 5군데에서 one-line 호출:

| 경로 | 시점 |
|---|---|
| `biblio_reflect.apply_single()` | 수동 단건 Apply Biblio |
| `biblio_reflect.apply()` (Zotero branch) | 배치 reflect, Zotero-sourced |
| `biblio_reflect._local_apply()` | 배치 reflect, local-only |
| `biblio_service._apply_merged_zotero()` | 비교 UI Apply, Zotero-sourced |
| `biblio_service._apply_merged_local()` | 비교 UI Apply, local-only |

본문을 5번 복붙하는 대신 헬퍼 + 5콜로 통일. "여기서 status가 terminal로 넘어갔다"가 호출 사이트에서 명시적으로 보임.

**Zotero in-place file replace**:

처음엔 delete+re-upload 생각했는데 사용자가 "key는 그대로야?" 물어줌 → 깨끗하게 in-place 가능한 길 있음을 확인. pyzotero `upload_attachments`에 `[{'key': existing_key, 'filename': ..., 'md5': current_md5}]` 전달하면:
- `_create_prelim`이 key 존재 감지 → skip
- `_get_auth`가 `If-Match: md5`로 진입 → 새 auth params 반환
- `_upload_file` → S3 PUT으로 content만 교체
- **attachment key, item version chain 모두 보존**

`zotero_client.replace_attachment_file(key, path)` → returns `'updated'` | `'unchanged'` | `None`.

PaperFile.hash도 재계산해서 sibling row에 반영 (이전엔 빈 문자열로 들어와 있었음 — `update_hashes.py`가 PDF만 다루고 JSON sibling은 안 건드림). 새 파일 content의 hash를 `hash_file()`로 계산 → `sibling.save()`.

**읽기 측** — `biblio.load_ocr_meta(file_hash)` + `class BiblioAlreadyApplied(Exception)`. `extract_biblio_llm()` 진입에서:

```python
meta = load_ocr_meta(file_hash)
if meta and meta.get('biblio_state') in ('applied', 'auto_committed'):
    raise BiblioAlreadyApplied(meta)
```

desktop의 두 캘러는 `try/except BiblioAlreadyApplied`로 catch → `{'skipped': True, 'meta': ...}` 시그널 → `_on_biblio_extracted`가 skip 분기로 빠져서 status bar `"Biblio already applied on Zotero (llm-sonnet) — skipped LLM for paper N"` + pill `done`.

#### Cross-machine 시나리오

머신 A:
1. OCR → biblio 추출 → apply
2. `record_biblio_applied`가 JSON에 meta 박고 Zotero in-place replace

머신 B (DB 비어있음, OCR 캐시 없음):
1. Zotero pull sync로 Paper/PaperFile/PaperFolder rows 재구성 (JSON sibling 포함)
2. Process Folder → OCR 단계에서 sibling-fetch로 Zotero JSON 받음 (meta 포함)
3. 자동 큐가 biblio 추출 시도 → `extract_biblio_llm`이 meta 보고 raise → **LLM 호출 0**
4. status bar에 `"Biblio already applied on Zotero — skipped LLM"` + pill `done`

OCR API + LLM API 호출 0회로 sync 완성.

### 3. bookSection 400 — `ITEM_TYPE_JOURNAL_FIELD` map

paper 4315 (`The earliest known West Gondwanan trilobites...`, Zotero key `ZVFPZI9B`)에서 PATCH 400 발생. Zotero는 itemType마다 "journal-like" container title 필드명이 다름:

| itemType | container field |
|---|---|
| journalArticle, magazineArticle, newspaperArticle | publicationTitle |
| bookSection | bookTitle |
| conferencePaper | proceedingsTitle |
| encyclopediaArticle | encyclopediaTitle |
| dictionaryEntry | dictionaryTitle |
| book, thesis, report, ... | (없음 — title 자체가 container) |

`_compute_patch` + `_compute_override_patch` 둘 다 `_journal_field_for(item_type)`로 분기. 매핑 없으면 journal 쓰기 skip.

추가로 pyzotero `UnsupportedParams`를 `ZoteroPatchRejected(RuntimeError)` 래퍼로 잡아서 UI에 raw traceback 안 새도록. `_on_biblio_extracted`에 try/except 추가.

### 4. OCR wrapper `client_id`

서버가 이미 native 지원 (docs/WRAPPER_API.md 명세 확인):
- `POST /ocr`이 `client_id` form 필드 또는 `X-Client-ID` 헤더 받음
- response에 `cached: true` (server-side dedup `(file_hash, client_id)`)
- `GET /ocr` 응답에 `client_id` 필드
- `GET /ocr?client_id=...` 필터

**옵션 A vs B** — 사용자와 협의:
- A: 고정 `"papermeister"` → cross-machine dedup 풀 활용, 단 동시 실행 시 wait 작동 안 함
- B: per-install `papermeister-{8 hex}` → wait 정확, cross-machine dedup은 sibling-fetch가 이미 해줘서 손실 적음

옵션 B 채택. `preferences.get_client_id()` 헬퍼 — UUID hex 8자리, lazy 생성, `preferences.json` 영속.

- `wrapper_submit`이 form data로 `client_id` 동봉. `cached=true` response는 로그
- 두 책임 명확히 분리: **sibling-fetch = cross-machine 캐시 (Zotero가 매개), server dedup = within-install 캐시 (app 재시작/재시도 보호)**

### 5. Server-load wait

wrapper 파이프라인 시작 직전 (seed 제출 전):

```python
my_cid = get_client_id()
while not self._cancelled:
    jobs = wrapper_list_jobs()
    others = [
        j for j in jobs
        if j.get('status') in {'queued', 'processing'}
           and j.get('client_id') != my_cid
    ]
    if not others:
        break
    pages_ahead = sum(... for j in others)
    self.progress.emit(f'Waiting for server: {len(others)} external...')
    time.sleep(15)
```

- 다른 client_id의 active 잡만 wait 대상
- 자기 자신의 이전 세션 잡(같은 client_id, 활성)은 wait 안 함 — 어차피 우리 잡이니 큐에 더 쌓는 게 합리적
- `ocr_wait_for_others` pref로 토글 (기본 ON)
- Cancel 누르면 즉시 빠짐
- `wrapper_list_jobs` 실패 시 `[]` 반환 → idle로 간주 → 즉시 진행 (죽은 서버에서 hang 방지)

### 6. About 섹션

별도 메뉴 안 만들고 PreferencesDialog 하단에 `About` 헤더 + read-only `Client ID` QLineEdit. 사용자 의견. 사용자가 자연스럽게 보게 됨.

## 운영 검증 메모

세션 종료 시점 paper 활동 (24h 윈도우):
- 48편 status='extracted' (LLM 끝났는데 apply 못함)
- 15편 'applied'

48편의 분포:
- 일부: evaluate가 `needs_review`로 분류한 정상 케이스 (low_confidence, override_conflict, …)
- 일부: bookSection 400으로 `apply_single`이 중단된 케이스

세션 18 픽스 후 같은 폴더 재처리 시 후자는 자동 해소. 전자는 그대로 needs_review로 사용자 검토 대상.

paper 4315 (트리거 케이스) — itemType=bookSection이라고 추정. 다음 Process에서 `bookTitle` 필드로 patch 전송 시도 → 성공해야 정상.

## 파일

```
papermeister/preferences.py        — get_client_id()
papermeister/ocr.py                — wrapper_submit에 client_id form, wrapper_list_jobs 신설, cached 로그
papermeister/biblio.py             — load_ocr_meta, BiblioAlreadyApplied, extract_biblio_llm 진입 체크
papermeister/text_extract.py       — _try_fetch_sibling_json (dict 분기), record_biblio_applied, PaperFile.hash 재계산
papermeister/biblio_reflect.py     — apply() / _local_apply() / apply_single()에서 record_biblio_applied 호출
papermeister/zotero_client.py      — replace_attachment_file (in-place file replace)
papermeister/zotero_writeback.py   — ITEM_TYPE_JOURNAL_FIELD 매핑, _journal_field_for(), ZoteroPatchRejected, UnsupportedParams 변환
papermeister/ui/preferences_dialog.py — About 섹션 (read-only Client ID)
papermeister/ui/process_window.py  — _prepare_file에 sibling fetch, pre-flight server-load wait 루프
desktop/services/biblio_service.py — _apply_merged_zotero/local에서 record_biblio_applied 호출
desktop/windows/main_window.py     — BiblioAlreadyApplied catch, ZoteroPatchRejected catch
docs/ENDPOINTS.md, WRAPPER_API.md  — client_id form/header + cached + ?client_id= 필터 문서화
```

## 미정

- 라이브 검증 한 사이클 더 — 같은 폴더 (Antarctic archaeocyath 등) 재처리해서 (a) bookSection 픽스 후 PATCH 성공 (b) papermeister_meta가 JSON에 박혔는지 (c) 다른 머신에서 sibling-fetch 후 LLM 스킵까지 — 셋을 한 번에 확인
- `extract_biblio.py` CLI는 별도 entry — 세션 17/18 어느 쪽도 동일 패턴 적용 안 함. CLI 사용자가 늘면 처리 필요
- `ocr_wait_for_others` Preferences UI 토글 안 만들었음 — 필요해지면 체크박스 추가
