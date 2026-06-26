# P13 — passage_fts external-content 전환 (옵션 1b)

> 계획 문서. DB 4.56 GB 중 OCR 본문이 **두 벌**(`passage.text` 1.61 GB +
> `passage_fts_content` 1.75 GB)로 저장되는 걸 제거. `passage_fts`를
> **external-content(text-only)** FTS5로 바꿔 본문 사본을 없애고, 제목 가중치는
> devlog 063의 Python 재랭킹으로 대체. 목표: **4.56 GB → ~2.7 GB (–40%)**.
> ⚠️ 추출 배치가 끝난 뒤 Windows에서 적용. 라이브 DB 동시 접근 금지.

## 0. 현재 구조 (변경 전)

```sql
CREATE VIRTUAL TABLE passage_fts USING fts5(
    title, authors, text,
    paper_id UNINDEXED, page UNINDEXED, passage_id UNINDEXED,
    tokenize='unicode61'
);
```
- shadow: `_data`(역색인 0.83 GB), `_content`(원본 사본 1.75 GB), `_docsize`/`_idx`(~22 MB).
- 동기화는 **수동**: `text_extract.py`가 passage마다 `INSERT INTO passage_fts(...)`,
  `text_extract.py`/`ingestion.py`가 `DELETE FROM passage_fts WHERE paper_id=?`,
  merge 시 `UPDATE passage_fts SET paper_id,title,authors`.
- 검색(`search.py`): `bm25(passage_fts,10,5,1)`(title×10/authors×5/text×1),
  `snippet(passage_fts,2,…)`(col 2=text), `paper_id/page/passage_id`는 UNINDEXED 컬럼에서.

## 1. 새 스키마 (변경 후)

```sql
CREATE VIRTUAL TABLE passage_fts USING fts5(
    text,
    content='passage',
    content_rowid='id',
    tokenize='unicode61'
);
```
- `passage_fts_content`(1.75 GB) **소멸**. 역색인만 유지. 원문이 필요할 때(`snippet`)
  FTS5가 `passage.id`로 `passage` 테이블에서 읽음.
- `title/authors/paper_id/page/passage_id` 컬럼 제거 → **검색 시 `passage` JOIN으로 획득**
  (rowid = passage.id, paper_id/page는 passage에서, passage_id = rowid).

## 2. 동기화: 수동 → 트리거

passage에 트리거를 걸어 자동 동기화. `AFTER UPDATE OF text`로 좁혀 merge 시
paper_id 재지정(텍스트 불변)에는 안 걸리게.

```sql
CREATE TRIGGER passage_fts_ai AFTER INSERT ON passage BEGIN
  INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER passage_fts_ad AFTER DELETE ON passage BEGIN
  INSERT INTO passage_fts(passage_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER passage_fts_au AFTER UPDATE OF text ON passage BEGIN
  INSERT INTO passage_fts(passage_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text);
END;
```
(external-content FTS5의 삭제는 원본 값을 함께 줘야 하므로 `'delete'` 특수 구문 사용.)

## 3. 코드 변경 (파일별)

### `papermeister/database.py`
- `init_db`의 `CREATE VIRTUAL TABLE` → 위 새 스키마. 직후 트리거 3개 생성(IF NOT EXISTS).
- `_migrate(db)`: **구 스키마 자동 감지 후 1회 변환** (아래 §6 절차를 인라인으로).
  감지: `PRAGMA table_info(passage_fts)` 또는 `sqlite_master`의 CREATE문에 `title` 포함 여부.
  변환은 멱등(변환 후 새 스키마라 다음 기동엔 skip). VACUUM은 제외(수동/스크립트).

### `papermeister/text_extract.py` (재처리 경로 476–512)
- `DELETE FROM passage_fts WHERE paper_id=?` (478) **삭제** — `Passage.delete()`(479)가
  AD 트리거를 발화.
- per-passage `INSERT INTO passage_fts(...)` (508–512) **삭제** — `Passage.create()`(503)가
  AI 트리거를 발화. (title/authors 더 이상 FTS에 안 들어가므로 authors_str 계산은
  메타 용도로만 남김 — Author 레코드는 그대로.)

### `papermeister/ingestion.py`
- `DELETE FROM passage_fts WHERE paper_id=?` (158, 367) **삭제** — paper/passage
  삭제(`delete_instance(recursive=True)`)가 AD 트리거 발화.
- merge의 `UPDATE passage_fts SET paper_id,title,authors` (329–333) **삭제** — FTS엔
  paper_id/title/authors가 없고 text는 불변. paper_id는 검색 시 JOIN으로 해결.
  (단 `Passage.update(paper=new)`가 `text` 컬럼을 안 건드리므로 AU 트리거도 미발화 — 의도대로.)

### `papermeister/search.py` (쿼리 재작성)
```sql
SELECT p.paper_id, p.page, p.id AS passage_id,
       snippet(passage_fts, 0, '**', '**', '...', 32) AS snippet,
       bm25(passage_fts) AS rank
FROM passage_fts
JOIN passage p ON p.id = passage_fts.rowid
WHERE passage_fts MATCH ?
ORDER BY rank LIMIT ?;
```
- `snippet(...,0,...)`: text가 유일/0번 컬럼.
- `bm25(passage_fts)`: 단일 컬럼(가중치 인자 제거).
- title×10/authors×5 가중치 소멸 → **제목은 기존 `_title_tier` 3단 Python 재랭킹이 담당**
  (devlog 063, 이미 존재). authors 가중치는 대체 없음(§4 참고).

## 4. ⚠️ 검색 recall 영향 (반드시 인지)

text-only 색인이므로 **본문에 등장하지 않는 제목어/저자명은 매치되지 않음**:
- **제목-only**: 검색어가 제목에만 있고 본문엔 없으면 후보에서 탈락. `_title_tier`는
  "이미 매치된 후보"의 순위만 올리므로 **구제 불가**. 다만 학술 논문은 제목어가 보통
  본문/초록에도 나와 실제 손실은 작음.
- **저자-only**: 저자명이 본문에 없으면 매치 안 됨 → **저자 풀텍스트 검색 사실상 상실**.
  (저자 탐색은 메타데이터/리스트 뷰로는 여전히 가능.)

### 완화책(선택) — 문서 단위 `paper_fts` 추가
저자/제목 recall을 완전히 보존하려면 **논문 1행짜리** 작은 FTS를 둔다(≈500행, 수백 KB로
무시 가능):
```sql
CREATE VIRTUAL TABLE paper_fts USING fts5(
    title, authors, content='paper', content_rowid='id', tokenize='unicode61');
```
검색을 `passage_fts`(본문) ∪ `paper_fts`(제목·저자) 병합으로 바꾸면 recall 완전 보존 +
문서 단위 제목 부스트가 더 깔끔해짐. **권장**: 1b 본체와 함께 넣거나, 우선 1b만 적용 후
저자 검색 수요를 보고 추가. (이 문서는 1b 본체 기준; paper_fts는 add-on으로 분리 가능.)

## 5. 마이그레이션 스크립트 (`scripts/migrate_fts_external_content.py`, 1회성)

관례대로 dry-run 기본 + `--execute`. **Windows에서** 추출 종료 후 실행.
```
1. PRAGMA integrity_check → 'ok' 확인 (아니면 중단, REINDEX 먼저).
2. 권장: VACUUM INTO 'papermeister.db.pre-fts-migration' 로 백업 스냅샷.
3. BEGIN
4. DROP TABLE passage_fts;                      -- 구 shadow 전부 제거
5. CREATE VIRTUAL TABLE passage_fts USING fts5(text, content='passage',
        content_rowid='id', tokenize='unicode61');
6. INSERT INTO passage_fts(passage_fts) VALUES('rebuild');   -- passage 전체 색인(수십초~수분)
7. CREATE TRIGGER passage_fts_ai / _ad / _au;
8. COMMIT
9. PRAGMA integrity_check → 'ok'
10. 샘플 검색 1~2건으로 결과 sanity 확인
```
파일 크기 실제 축소는 별도 `VACUUM;`(또는 6번 백업 스냅샷으로 교체). VACUUM은 ~2x 임시
공간 + DB 잠금 필요하므로 한가할 때.

## 6. `_migrate()` 자동 변환 (구 DB 안전망)

새 코드가 구 스키마 DB에 닿으면 search.py가 깨지므로, `_migrate`가 기동 시 1회 변환:
- 감지: `passage_fts` CREATE문에 `title` 컬럼 존재 → 구 스키마.
- 변환: §5의 4–7단계(드롭→생성→rebuild→트리거) 한 트랜잭션. 변환 후 새 스키마라 재기동 시 skip.
- VACUUM은 자동 변환에 **포함하지 않음**(기동마다 느려지면 안 됨) — 스크립트/수동.
- 비용: 최초 1회 rebuild로 기동이 수십초~수분 느림(로그로 안내). 멱등.

## 7. 롤아웃 순서 / 검증 / 롤백

1. 추출 배치(`--scope all`) **완전 종료** 확인.
2. (선호) Windows에서 `scripts/migrate_fts_external_content.py --execute` 실행.
   - 또는 코드만 배포 후 첫 `python -m desktop`/`cli.py` 기동의 `_migrate`가 자동 변환.
3. 검증: `integrity_check=ok`, 본문 검색 정상, 제목어 검색이 `_title_tier`로 상위 노출,
   (paper_fts 미적용 시) 저자-only 검색 손실 인지.
4. `VACUUM`으로 파일 축소(선택, 백업 후).
5. **롤백**: §5-2 백업 스냅샷으로 파일 교체. 코드도 이 커밋 revert. (구 스키마는 자기완결적
   이라 구 코드로 즉시 복귀 가능.)

## 8. 용량 추정

| | 변경 전 | 변경 후 |
|---|--------|--------|
| `passage` (본문 원본) | 1.61 GB | 1.61 GB (유지) |
| `passage_fts_content` | 1.75 GB | **0** |
| `passage_fts_data` (역색인) | 0.83 GB | ≈0.83 GB |
| 기타 | ~0.37 GB | ~0.37 GB |
| **합계(파일, VACUUM 후)** | **4.56 GB** | **≈2.7 GB** |

`detail='none'/'column'`로 역색인(0.83 GB)을 더 줄이는 건 phrase 검색 정밀도 트레이드오프라
별도 검토(이 문서 범위 밖).

## 9. 결정 필요 사항

- **(A)** 1b 본체만(저자-only 풀텍스트 검색 손실 감수) vs **(B)** `paper_fts` add-on 동반(저자·제목
  recall 완전 보존, 권장).
- **(C)** 구 DB 변환을 `_migrate` 자동 vs 전용 스크립트 수동(Windows). → 안전상 **스크립트 수동**
  먼저, `_migrate`는 "구 스키마 감지 시 명확한 에러+안내"만 두는 보수적 방식도 가능.
```
