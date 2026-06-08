# 053 — write-back itemType 자동 승격 + volume/issue/pages 추출

> 세션 43 (2026-06-08), [052](./20260608_052_Biblio_Title_Override_For_Filename_Placeholder.md) 후속.

## 동기

052에서 placeholder 제목을 고쳤지만, 사용자 지적: promoted standalone(itemType=`document`)에
Extract Biblio를 돌리면 **journal 이름이 추출되는데도 Zotero에 안 들어감**. 원인: `document`
타입은 journal-like 필드가 없어서(`_journal_field_for('document')`=None) `_compute_patch`가
journal을 skip. → **itemType을 실제 타입으로 승격해야 journal/volume/issue/pages가 유효**해짐.

추가 요청: journal article이면 **volume/issue/pages도 추출** (프롬프트 변경 포함).

## 변경 A — itemType 자동 승격 (write-back)

`zotero_writeback.writeback_biblio`에 승격 분기 추가:

- `DOC_TYPE_TO_ITEM_TYPE` (article→journalArticle, book→book, chapter→bookSection,
  thesis→thesis, report→report). journal_issue/unknown은 부재 = 승격 안 함.
- 게이트: 현재 itemType이 `document` **AND** 제목이 파일명 placeholder(또는 빈 제목) AND
  doc_type이 실제 타입으로 매핑. → 사용자가 의도적으로 만든 curated `document`는 안 건드림.
- `_build_type_upgrade_payload`: `zot.item_template(target_type)`로 새 타입 템플릿을 받아
  key/version/collections/parentItem/tags/relations 보존 + biblio 필드 채움. **template에
  있는 필드만 set**(`f in payload` 가드) → Zotero가 거부하는 필드 전송 방지. 검증된
  `update_promoted_items.build_update_payload` 패턴과 동일.
- `zot.update_item(payload)`로 전송(= itemType 변경 경로, 스크립트에서 검증됨). 이후 fresh
  re-fetch로 로컬 Paper 갱신.

이 승격 한 번으로 제목(placeholder→실제) + journal(publicationTitle 등) + volume/issue/pages가
한꺼번에 들어감.

## 변경 B — volume/issue/pages 추출·저장

- **모델**: `PaperBiblio`에 `volume`/`issue`/`pages` TextField. `database._migrate`로 컬럼 추가.
- **프롬프트**: `biblio.py::_BIBLIO_PROMPT`(desktop Extract Biblio가 쓰는 경로) 스키마에
  volume/issue/pages + 규칙("plain 숫자/범위, Vol./pp. 라벨 없이"). `extract_biblio.py`(Haiku
  배치), `extract_biblio_vision.py`(Sonnet vision)도 동일.
- **저장**: `pred` dict이 그대로 흐르므로 4개 `PaperBiblio.create` 지점(desktop 2 + script 2)에
  `volume/issue/pages` 추가. `BiblioResult` dataclass + from_dict도 갱신.
- **write-back(기존 타입)**: `_compute_patch`에 volume/issue/pages empty-slot fill 추가.
  **`f in data`를 유효성 체크로 활용** — Zotero는 itemType의 모든 유효 필드를 (빈 값이라도)
  반환하므로, data에 없는 필드는 그 타입에 무효 → 전송 안 함(400 방지). 단위 검증: journalArticle은
  3필드 다, book은 volume만(issue/pages는 필드 자체가 없어 자동 skip).

## 범위/주의

- 이미 추출돼 `auto_committed`인 biblio는 재적용 skip → volume/issue/pages·승격을 보려면 **재추출** 필요.
- 승격은 evaluate가 auto_commit으로 보낸 경우(고신뢰 + 빈 슬롯)에만 발동. "제목만 placeholder이고
  나머지 다 찬" 희귀 케이스는 needs_review로 감(비교 UI 수동).
- 비교 UI(needs_review 검토)엔 volume/issue/pages 필드 미노출 — 자동 경로만 처리(후속 과제).
- creators는 기존 자동 경로와 동일하게 single-field `name` 사용(override 경로의 first/last 분리와 별개).
