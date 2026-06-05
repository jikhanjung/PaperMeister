# 046 — OCR JSON 파일명을 `{pdf}.{hash[:8]}.json`으로 통일

날짜: 2026-06-05

## 동기

OCR 결과 cache + Zotero sibling attachment의 파일명이 64-char hex hash인 `{hash}.json` 형식이라 사람이 식별 불가. 9,700+ cache 파일 + 2,000+ Zotero attachment가 같은 패턴. Zotero GUI에서 attachment 목록 보면 부모 PDF가 어떤 paper인지 hash로 추론 불가.

사용자 요청: PDF 파일명과 동일하게 — `abcdef.pdf` 옆에 `abcdef.pdf.json`.

## 결정

| 항목 | 선택 | 근거 |
|---|---|---|
| 새 명명 규칙 | `{pdf_basename}.{hash[:8]}.json` | 사용자 예시(`abcdef.pdf.json`) + 충돌 방지 hash 8자 (BIRTHDAY 확률 9,700편에서 2×10⁻⁹) |
| Hash 길이 | 8자 | 사용자가 "동일한 파일이 여러 곳에 있을 가능성"을 짚었지만 그 경우 cache 통합돼도 내용 같아 무해. 8자도 사실상 안전 |
| 적용 범위 | 로컬 cache + Zotero sibling 둘 다 | Zotero GUI 가독성 + 로컬 검토 편의 |
| Legacy fallback | 없음 | 사용자 결정: "OCR이 거의 다 끝났으니 한 번에 마이그레이션". fallback 코드 안 만들고 새 규칙으로만 |
| Same-hash multi-paperfile | cache file 복제 (`shutil.copy`) | 207개 케이스. 1:1 매핑 보존, read 코드 단순 (fallback 검색 불필요) |
| 마이그레이션 | 일괄 script, dry-run/apply 모드 | 9,920건 처리 |

## 구현

### 헬퍼 함수 (단일 진실)

`papermeister/text_extract.py`:
```python
def ocr_json_filename(paper_file):
    """Format: '{pdf_basename}.{hash[:8]}.json'"""
    if not paper_file.hash:
        raise ValueError(f'PaperFile {paper_file.id} has no hash')
    pdf_name = os.path.basename(paper_file.path)
    return f'{pdf_name}.{paper_file.hash[:8]}.json'
```

cache file 명, Zotero sibling attachment filename, PaperFile.path 모두 이 한 함수가 결정.

### 코드 변경 (write 경로)

10개 hot spot:
- `text_extract._save_ocr_json`, `_load_ocr_json` — cache write/read
- `text_extract._record_biblio_applied_impl` — apply 시 papermeister_meta 박는 경로 (biblio.file_hash → PDF PaperFile 찾아서 ocr_json_filename)
- `text_extract._try_fetch_sibling_json` — Zotero sibling pre-fetch
- `text_extract._upload_ocr_json_to_zotero` — sibling upload + DB row
- `text_extract.process_paper_file` 안의 sibling existence check
- `scripts/upload_ocr_json.py` — bulk upload script
- `papermeister/ui/main_window.py` — frozen GUI의 reindex 경로 (일관성 위해)
- `desktop/windows/main_window.py` — 폴더 우클릭 upload

### Cache read 경로

`papermeister/biblio.py`:
```python
def _find_cache_by_hash(file_hash: str) -> str | None:
    """{*.HASH[:8].json} glob 검색. 시그니처 호환성 위해 hash만 받아도 동작."""
    suffix = f'.{file_hash[:8]}.json'
    for fname in os.listdir(OCR_JSON_DIR):
        if fname.endswith(suffix):
            return os.path.join(OCR_JSON_DIR, fname)
    return None
```

`load_ocr_pages(file_hash)` / `load_ocr_meta(file_hash)` 시그니처는 그대로 유지 — 호출자 (extract_biblio_llm 등) 영향 0. 내부 lookup만 glob으로.

### 마이그레이션 script

`scripts/rename_ocr_json.py` — 3-layer 처리:

1. **로컬 cache rename**: `~/.papermeister/ocr_json/{hash}.json` → `{new_name}` (atomic `os.replace`)
2. **DB PaperFile.path update** (peewee)
3. **Zotero attachment metadata PATCH**: `data.filename` + `data.title` 둘 다 새 이름으로

옵션:
- `--dry-run`: read-only, plan preview
- `--limit N`: 소량 테스트
- `--include-already-renamed`: 이전에 처리된 attachment도 다시 PATCH (안전망)
- `--skip-zotero`: 로컬만
- `--sleep`: PATCH 간 sleep (rate limit 보호)

진행 로그: `[i/total] "paper title" in [Collection › Path] → new_name [zotero_key]` 패턴. 100건마다 + 처음 10건.

### 1:N cache 처리

같은 hash가 multiple PaperFile에 매핑된 207개 케이스 (= 같은 PDF가 여러 Zotero parent에 import됨). cache file을 각 sibling PaperFile name으로 복제. 같은 PDF filename이면 자연스럽게 한 파일로 dedupe. 다른 filename이면 별도 cache 파일.

## 시행 착오

### pyzotero `update_item` payload shape

처음에 hand-rolled PATCH body 던졌더니 "Invalid keys present in item 1: data" 에러. pyzotero는 `client._zot.item(key)`로 받은 full item dict 통째로 받아서 `data.filename`만 수정 후 update_item에 넘기는 방식.

```python
# 잘못된 방식
client._zot.update_item({'key': key, 'version': v, 'data': {'filename': new}})

# 올바른 방식
item = client._zot.item(key)
item['data']['filename'] = new_name
client._zot.update_item(item)
```

### `data.title`도 같이 박아야 GUI에서 보임

처음엔 `data.filename`만 박았는데 Zotero GUI items list엔 `data.title`이 표시됨. `filename`은 실제 파일 다운로드 시의 이름. 둘 다 박아야 일관.

### Zotero 7+ 정책 (TODO로 분리)

Zotero 7부터 attachment title을 filename과 분리해서 generic label ("PDF", "EPUB" 등)로 박는 게 표준 ([공식 문서](https://www.zotero.org/support/kb/attachment_title_vs_filename)). 사용자가 마이그레이션 결과 확인 후 알려줘서 발견. 지금은 title=filename으로 박힌 상태 그대로 두고, 필요 시 별도 정규화 작업으로 HANDOFF.md에 등록.

### Idempotency / skip 로직

`--include-already-renamed`로 처리한 attachment를 다시 처리해도 `data.title`/`filename` 비교 후 같으면 PATCH skip (fetch는 어차피 필요, 추가 round-trip 0). `zotero_unchanged` counter 추가.

### WSL/NTFS WAL 충돌

peewee의 init_db가 WAL pragma 박는데 WSL에서 Windows NTFS에 있는 DB로 connect 시 `disk I/O error`. 사용자가 Windows native Python(Anaconda)에서 직접 script 실행. dry-run은 `/tmp` 사본으로 검증.

## 검증

dry-run 결과 (사용자 실 DB 9,888 papers / 19,983 paperfiles):
```
candidates needing rename: 9920
already in new form:       7  (사용자 손으로 박은 것 — 안 건드림)
no matching PDF sibling:   8  (orphan JSON, skip)
unique PDF hashes:         9700
hashes with 1:N cache:     204
```

`--limit 10` 두 번 (첫 번째: payload shape 버그 — Zotero PATCH 0건 / cache rename 10건만, 두 번째: 수정 후 retitle 10건 정상). Zotero GUI에서 filename + title 둘 다 새 form으로 박힘 확인.

전체 apply 진행 중 (작성 시점 1000/9910). 30~60분 예상.

## 후속

HANDOFF TODO 등록:
- **OCR JSON sibling attachment title 정규화** — Zotero 7+ 정책 따라 title을 `"OCR JSON"` 같은 generic label로 일괄 변경. `rename_ocr_json.py`에 `--retitle-generic` 옵션 추가 또는 Zotero 8 GUI 활용

마이그레이션 끝나면 검증 dry-run + 결과 카운트만 별도 commit 예정.
