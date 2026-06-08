# 051 — Phantom 부모 promote 복구 (demote → 재promote)

> 세션 43 (2026-06-08), [050](./20260608_050_Permanent_Deletion_Empty_Trash_Sync.md) 후속.

## 발견 (Zotero 9892 vs PaperMeister 9889 추적)

사용자가 Zotero 전체 항목(9892)과 PaperMeister(9889)의 차이를 물어 추적. **데이터 누락이
아니라 standalone auto-promote(세션 36) 드리프트**였음:

- PM은 standalone PDF를 OCR 후 auto-promote — Zotero에 parent "document" 항목을 만들고
  PDF를 child로. PM 구조 = `parent paper + child PDF` (서로 다른 Zotero key).
- Temple1980 / Holloway1981 두 편은 **그 parent 항목(82WUVHJC / Q6WWUAX4)이 Zotero에서
  삭제됨** (사용자가 auto-생성 래퍼를 지웠고, 삭제가 너무 오래돼 `/deleted` 로그 보존창에서
  이미 pruned → 050의 영구삭제 미러로도 못 잡힘). PDF는 다시 standalone으로 환원.
- 결과: PM은 phantom parent(82.../Q6...)를, Zotero는 standalone PDF(W88.../DLH...)를
  top-level로 세어 카운트가 어긋나 보임. **standalone sync 누락이 아님** —
  `_classify_raw_items`/`_build_results`는 standalone을 정상 처리.

`Paper.zotero_key != PDF child key`는 정상 parented paper도 다 해당(9836편)이라 판별 불가.
유일한 신호 = **`Paper.zotero_key`가 Zotero에 실재하지 않음**.

## 복구: `scripts/refix_promoted_standalones.py`

phantom을 zotero.sqlite의 실재 key 집합으로 탐지(API로 수천 편 확인은 느림) 후 paper별:

1. **demote** — `Paper.zotero_key`를 PDF 첨부 key로 되돌림 (Zotero의 standalone 현실과 일치,
   promote의 전제 `Paper.zotero_key == PaperFile.zotero_key` 충족).
2. **재promote** — `promote_standalone_with_filename()`로 **새 Zotero parent 생성** + PDF 재parent.
3. **JSON sibling 재parent** — 같은 새 부모 아래로 (단 Zotero에 실재할 때만).

부분 실패해도 안전: demote까지만 되면 Zotero standalone 상태와 일치하는 유효 상태.

## 결과

탐지 정확히 2편 → `--execute`:
- paper 8590 Temple1980: phantom `82WUVHJC` → demote `W88UYCLR` → 새 부모 **`4WWSF34U`**
- paper 8591 Holloway1981: phantom `Q6WWUAX4` → demote `DLHSYVW4` → 새 부모 **`DMGQHSKW`**

검증: PM paper 8590/8591에 새 부모 key 반영, phantom key 완전 제거, PDF child 유지.

## 메모

- **JSON sibling 0 reparented → 별도 재업로드로 해결**: 옛 OCR-JSON 첨부(77MGXAWW / JDGQ4W6S)는
  phantom 부모와 함께 Zotero에서 이미 삭제돼 재parent 대상이 없었음. 로컬 PaperFile 행은 dangling으로
  남고, 이 행 때문에 `upload_ocr_json.py`/폴더 우클릭 Upload가 `(paper_id, json_name)` dedup으로
  **SKIP**(이미 있다고 오판). → `scripts/reupload_missing_ocr_json.py` 신설: Zotero에 없는 key를 가진
  JSON PaperFile + 로컬 캐시 존재 + PDF 부모 보유인 것을 찾아, 캐시를 `upload_sibling_attachment`으로
  새 부모 sibling으로 재업로드하고 행의 zotero_key를 갱신(OCR 재실행 없음). 2편 적용:
  77MGXAWW→B5FWTTJ4, JDGQ4W6S→DT555IHV. 최종 구조 = 부모 + PDF + JSON sibling 정합.
- 새 부모는 Zotero **서버**에 생성됨 — Zotero desktop이 sync해야 zotero.sqlite에도 반영.
  PM 다음 sync에선 정합되게 보임.
- 일반화된 사각지대: "`/deleted` 보존창보다 오래된 Zotero 삭제"는 영구삭제 미러(050)로 못 잡음.
  promote parent가 그 케이스에 걸린 것. 더 넓게 막으려면 sync 때 promote된 parent key 실재
  검증 후 자동 demote/refix하는 상시 경로가 필요(현재는 one-off 스크립트로 충분).
