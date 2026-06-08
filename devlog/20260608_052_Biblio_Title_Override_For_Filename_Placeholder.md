# 052 — biblio write-back: 파일명 placeholder 제목을 추출 제목으로 덮어쓰기

> 세션 43 (2026-06-08).

## 증상

원래 standalone PDF였다가 auto-promote된 항목(부모 title = PDF 파일명)에 Extract Biblio를
돌리면 authors/year/journal은 자동 반영되는데 **제목은 추출된 진짜 제목이 있어도 파일명
("Temple1980.pdf") 그대로** 남음.

## 원인

write-back 경로 `zotero_writeback._compute_patch`의 title 규칙이 **"현재 Zotero title이
비어있을 때만 채움"**(empty-slot rule):

```python
if not (data.get('title') or '').strip() and (biblio.title or '').strip():
    patch['title'] = biblio.title.strip()
```

promoted standalone은 title=파일명(비어있지 않음)이라 영영 제외. year/journal/authors는 빈
슬롯이라 채워지므로, evaluate는 `any_fill`→auto_commit으로 정상 진입하지만 patch에 title만
빠지는 비대칭.

## 수정

파일명 placeholder는 **기술적으론 non-empty지만 서지정보가 없으므로** 추출 제목이 대체해야 함.

- `_title_is_filename_placeholder(paper, current_title)` 신설: 현재 title이 그 paper의 PDF
  PaperFile 파일명(확장자 포함 base 또는 제거한 stem)과 정확히 일치하면 True. 실제 curated
  제목은 절대 매칭 안 되므로 안전.
- `_compute_patch(..., title_overridable=False)` 파라미터 추가. title 조건을
  `new_title and new_title != cur_title and (not cur_title or title_overridable)`로 변경.
- `writeback_biblio`가 fresh Zotero `data['title']` 기준으로 placeholder 판정해 전달.

empty-slot 정책(다른 필드)은 그대로. force_override(creator shortfall)와도 독립.

## 효과

promoted standalone에 Extract Biblio → authors/year/journal **+ 제목**까지 한 번에 auto_commit.
파일명 placeholder가 아닌 일반 curated 제목은 종전대로 보존(덮어쓰기 안 함).

## 범위 메모

- 수정은 Zotero write-back 경로(`_compute_patch`)에 한정. 사용자 케이스(Zotero-sourced +
  write-back ON)가 여기로 흐름. 로컬 전용 `_local_apply`는 동일 개념이나 별도(미적용).
- 흔한 흐름(빈 year/journal/authors 존재)에선 한 번의 auto_commit으로 제목까지 해결. "제목만
  placeholder이고 나머지는 이미 채워진" 희귀 케이스는 evaluate가 override_conflict→needs_review로
  보냄(비교 UI에서 수동 적용 가능) — 의도적 보수 처리.
