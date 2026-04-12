# 027 — Biblio Comparison UI + Author Name Formatting

**Date:** 2026-04-12
**Status:** Completed

## Summary

Biblio 탭을 대조 비교 UI로 전면 개편하고, 저자 이름 표시/저장 형식을 정비했다.

## Changes

### 1. Biblio 탭 — 대조 비교 카드 (detail_panel.py, biblio_service.py)

기존의 "EXTRACTED BIBLIO" 카드(단순 나열)를 제거하고, Paper(Zotero) vs PaperBiblio(추출) 필드 비교 테이블로 교체.

- **5개 필드** (Title, Authors, Year, Journal, DOI) 를 나란히 비교
  - `match`: 양쪽 동일 → 한 칸으로 표시
  - `conflict`: 양쪽 다름 → 노란색(warn) 하이라이트
  - `fill`: Paper 비어있고 Biblio에만 값 → 녹색(ok) 하이라이트
- **라디오 버튼**: 각 diff 행마다 Paper/Biblio 중 선택 (conflict=Paper 기본, fill=Biblio 기본)
  - 선택됨: 초록색, 미선택: 어두운 회색 (`QRadioButton::indicator` QSS)
  - 라디오 버튼은 값 옆에 수평 배치 (가시성 개선)
- **편집 가능**: Biblio 쪽은 QLineEdit(Year, DOI) / QPlainTextEdit(Title, Authors, Journal)
- **× 클리어 버튼**: 각 편집 필드 오른쪽에 배치
- **Apply 버튼**: 라디오 선택 + 편집된 값을 수집하여 `apply_merged()` 호출

### 2. 저자 이름 "Lastname, Firstname" 표시 (biblio_service.py)

- `split_author_name(name)` — "Last, First" / "First Last" / CJK 4글자·3글자 분리
- `format_author_display(name)` → "Lastname, Firstname" 형태로 표시
- Authors 필드는 한 줄에 한 명씩 표시
- `_parse_display_authors()` — 편집된 "Last, First" 표시를 역변환하여 저장

### 3. Paper List 인용 스타일 저자 (paper_service.py, paper_list.py)

가운데 패널의 Authors 컬럼을 인용 스타일로 변경:
- Western: `Smith`, `Smith and Kim`, `Smith et al.`
- CJK (한국어/일본어/중국어): `정직한`, `정직한과 최덕근`, `정직한 외`
- 첫 번째 저자 기준으로 locale 결정

컬럼 순서 변경: `Status, Authors, Title, Year` → `Status, Authors, Year, Title`

### 4. Zotero 저자 이름 저장 형식 수정 (zotero_client.py, database.py, ingestion.py)

**문제**: Zotero API의 `firstName`/`lastName`을 `f"{lastName} {firstName}"` (공백 연결)로 합쳐 DB에 저장 → 나중에 성/이름 구분 불가. `split_author_name("Geyer Gerd")`가 "Gerd"를 성으로 오인식.

**수정**:
- `zotero_client.py`: `"Last, First"` (쉼표 구분)으로 저장하도록 변경
- `database.py` `_migrate()`: 기존 Zotero 저자 20k+건 일괄 마이그레이션 (`"Last First"` → `"Last, First"`)
  - `author_comma_migrated` pref 플래그로 1회만 실행
  - biblio apply로 들어온 저자(이미 Firstname Lastname 순서)는 별도 복원
- `ingestion.py`: 양쪽 sync 경로(incremental + collection)에서 기존 paper의 Authors도 갱신

### 5. 윈도우 크기 확대 (tokens.py, main_window.py)

- 초기 윈도우: 1300×820 → 1500×900
- 최소 윈도우: 1100×700 → 1280×760
- Detail panel 최소폭: 340 → 440, 기본폭: 420 → 540

### 6. P08 evaluate — already_complete skip (biblio_reflect.py)

값이 동일한 curated paper가 `override_conflict` → `needs_review`로 빠지는 문제 수정.
- `evaluate()`에서 빈 슬롯이 없을 때, 모든 필드(title/year/journal/doi/authors)를 비교
- 전부 동일하면 `skip/already_complete` 반환 → needs_review 목록에서 제외
- 기존 2건(한국어 논문) DB status를 `auto_committed`로 정리

### 7. apply_merged NameError 수정 (biblio_service.py)

리팩토링 과정에서 `biblio_fields_to_apply` → `fields_to_apply` 변수명 변경이 불완전하여 Apply 시 `NameError` 발생. 수정 완료.

## Files Changed

| File | Change |
|------|--------|
| `desktop/services/biblio_service.py` | FieldDiff, 비교 계산, apply_merged, 저자 이름 유틸 |
| `desktop/services/paper_service.py` | _author_cite (인용 스타일), _is_cjk_name |
| `desktop/views/detail_panel.py` | 비교 카드 UI, 라디오+편집+클리어 셀 |
| `desktop/views/paper_list.py` | 컬럼 순서 변경, Year 위치 이동 |
| `desktop/theme/qss.py` | ConflictValue, FillValue, ClearBtn, RadioButton 스타일 |
| `desktop/theme/tokens.py` | 윈도우/패널 크기 상수 |
| `desktop/windows/main_window.py` | 초기 윈도우 크기 |
| `papermeister/zotero_client.py` | firstName/lastName 합침 형식 수정 |
| `papermeister/database.py` | 저자 쉼표 마이그레이션 |
| `papermeister/ingestion.py` | sync 시 기존 paper Authors 갱신 |
