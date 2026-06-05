# 041 — Zotero sync: existing PaperFile 정보 갱신 + failed 자동 리셋

날짜: 2026-06-05

## 발견

`/mnt/c/Users/Jikhan Jung/.papermeister` 캐시 점검 중 OCR 진행률이 사실상 100% (9,923 / 9,933 PDF processed)였지만 failed 8 + pending 2의 잔존 12편을 살펴보니 분포가 깔끔하게 갈렸다:

- **HTTP 404 (Zotero web storage에 file blob 없음)**: 7편. attachment record는 존재하나 사용자가 PDF를 업로드 안 한 케이스. 재시도 무의미
- **로컬 경로 문제 1편 — CDTGJND5** (z-lib 책): 파일명에 en-dash + trailing double-space + 닫는 괄호 누락이 섞여 Windows에서 pdf_cache 디렉토리는 만들어지지만 다운로드 파일과 매칭이 안 되어 `[Errno 2]`로 영구 실패
- **Pending 2편**: trilobite taphonomy 관련, 단순 미실행

사용자가 Zotero에서 CDTGJND5의 parent title을 깨끗한 ASCII hyphen 버전으로, attachment filename도 `Fresco et al. - 2011 - Evolutionary Biology - ....pdf`로 rename했다. 우리 sync가 그 변경을 자동으로 반영하는지 물음.

## 코드 조사 결과

`papermeister/ingestion.py::sync_zotero_items`:

| 필드 | 기존 처리 |
|---|---|
| `Paper.title/date/year/journal/doi/authors` | ✅ diff 시 자동 update (line 247-275) |
| **`PaperFile.path`** | ❌ create-only. `existing_pf` 발견 시 `continue`로 skip |
| `Folder.name`, `Folder.parent` | ✅ `sync_zotero_collections`에서 처리 (line 127-129, 150-152) |

`grep` 결과 PaperFile.path를 update 하는 코드 사이트는 **전 repo에 0개**. 명시적 모델 결정이 아니라 의도하지 않은 빈틈으로 판단.

추가로 같은 종류의 sync 누락 정리:
- **PaperFolder remove** (컬렉션 멤버십 양방향): `get_or_create`만 하니 add-only
- **Trash / 삭제 핸들링** 없음
- **MD5 추적** 없음 (Zotero에서 PDF 교체 감지 불가)
- **`PaperFile.content_type` 컬럼 없음** — mime은 attachment dict 일회성 판정에만 씀
- **itemType 캐시 없음** — write-back에서 매번 fresh fetch

→ 이 fix는 가장 작은 정공법으로 **PaperFile.path 갱신**만 처리. 나머지는 HANDOFF.md의 "Zotero sync 양방향성 보강" TODO로 분리.

## 구현

`_refresh_existing_attachment(existing_pf, att)` 헬퍼 신설 (`ingestion.py:187`):

```python
def _refresh_existing_attachment(existing_pf, att):
    new_fname = att.get('filename', '')
    if not new_fname or existing_pf.path == new_fname:
        return
    existing_pf.path = new_fname
    if existing_pf.status == 'failed' and not existing_pf.hash:
        existing_pf.status = 'pending'
        existing_pf.failure_reason = ''
    existing_pf.save()
```

세 가지 hot path 모두 `continue` 직전에 헬퍼 호출 (메인 sync loop / orphan_attachments / backfill missing_file_papers).

**failed 자동 리셋 조건**: `status == 'failed' AND hash == ''`. hash가 비어있다는 건 한 번도 OCR을 시작하지 못했다는 뜻이므로 (다운로드/경로 단계에서 죽음), path가 새로 들어왔으면 다음 Process가 다시 시도할 가치가 있다. hash가 있는 failed (OCR 자체가 실패한 케이스)는 path 변경과 무관한 다른 원인이므로 자동 리셋 대상이 아니다.

stale-standalone merge가 일어난 경로에서도 `_refresh_existing_attachment` 직후 호출되도록 배치 — 새 parent로 옮긴 PaperFile에도 새 filename이 반영되어야 일관됨.

## 검증

라이브 검증 (CDTGJND5, paper 3711 / paperfile 4895):

1. desktop Sync → 헬퍼가 `_refresh_existing_attachment` 호출
2. `path`: `Evolutionary Biology – Concepts, Biodiversity, ... (z-lib.pdf` → `Fresco et al. - 2011 - Evolutionary Biology - Concepts, Biodiversity, Macroevolution and Genome Evolution.pdf`
3. `status`: `failed` → `pending` 자동 전환 (hash가 비어있었으므로)
4. `Paper.title`도 동시에 en-dash → ASCII hyphen으로 갱신 (기존 sync 로직)
5. PaperList에서 Process → 새 filename으로 Zotero 다운로드 → OCR 성공

사용자 보고: "Failed에 있다가 attachment 정보가 업데이트 돼서 pending으로 상태가 바뀌었어. 새로 OCR 돌리니 잘 되네."

## 후속

`HANDOFF.md` "Zotero sync 양방향성 보강" 섹션에 5개 TODO 추가:
- PaperFolder remove (양방향 멤버십 sync) — 정책 결정 필요
- Trash / 삭제 핸들링 — pyzotero `trash` endpoint 활용
- PaperFile MD5 추적 — Phase 2 sync-centric 모델 개정과 함께
- `PaperFile.content_type` 컬럼 추가
- itemType 캐시

`scripts/` 신설 없음. 같은 트리거(filename rename)가 이미 9,800편 corpus 전체에서 또 발생했을 수 있지만, 다음 incremental sync가 자연스럽게 흘러들면서 처리하므로 backfill 스크립트 불필요.
