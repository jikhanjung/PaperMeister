# CLI 컬렉션 테이블 페이지네이션

**날짜:** 2026-04-01
**유형:** 구현 기록

## 목표

컬렉션 수가 많을 때 터미널 출력이 넘치는 문제 해결. 테이블에 페이지네이션 도입.

## 구현 내용

### 1. `_collection_table()` 페이지네이션 지원

- `page`, `page_size` 파라미터 추가 (기본값: page=1, page_size=20)
- 전체 rows를 계산 후 현재 페이지 범위만 출력
- 2페이지 이상일 때 `Page X/Y (showing N-M of Total)` 표시
- 반환값 변경: `rows` → `(rows, page, total_pages)`

### 2. `zotero collections` 서브커맨드

- `--page` 옵션 추가 (기본값: 1)
- `--page-size` 옵션 추가 (기본값: 20)

```bash
python cli.py zotero collections --page 2 --page-size 10
```

### 3. 인터랙티브 모드 페이지 탐색

- `current_page`, `page_size` 상태 변수 추가
- `n` 키: 다음 페이지
- `b` 키: 이전 페이지
- 2페이지 이상일 때만 n/b 명령 안내 표시

## 변경 파일

| 파일 | 변경 |
|------|------|
| `cli.py` | `_collection_table()` 페이지네이션, interactive 모드 n/b 명령, `zotero collections` --page/--page-size 옵션 |
