# 067 — passage_fts external-content 전환 구현 (P13, 옵션 A2/B1)

> 계획 [P13](20260626_P13_FTS_External_Content_Migration.md) 구현. 결정: **A2**
> (저자·제목 recall 보존용 `paper_fts` 동반), **B1**(전용 마이그레이션 스크립트,
> Windows 수동). OCR 본문 중복(`passage_fts_content` 1.75GB) 제거 → **DB 4.3GB →
> 2.3GB (스냅샷 기준 –47%)**.

## 변경 요약

### `papermeister/database.py`
- `passage_fts`를 **external-content(text-only)** 로 재정의:
  `fts5(text, content='passage', content_rowid='id')`. 원문 사본 미보유.
- **`paper_fts`** 신설: `fts5(title, authors)` standalone(논문 1행, ~수백 KB).
- **동기화 트리거 9종**(`_FTS_TRIGGERS`): passage→passage_fts(ai/ad/au, external은
  삭제 시 old값 replay), paper/author→paper_fts(ai/ad/au, standalone은 일반 DELETE/UPDATE).
- `create_fts(db)`(fresh DB용), `_FTS_POPULATE`(rebuild+paper_fts 채우기),
  `_require_external_fts(db)`(구 스키마 감지 시 RuntimeError로 차단 → 마이그레이션 유도).
- `init_db`: 구 인라인 CREATE 제거 → `_require_external_fts` + `create_fts` 호출.

### `papermeister/text_extract.py`
- 재처리 시 수동 `DELETE/INSERT passage_fts` 제거. `Passage.delete()/create()`가
  트리거로 동기화. 죽은 `authors_str` 계산 제거(저자는 author_fts 트리거가 처리).

### `papermeister/ingestion.py`
- orphan 삭제·purge의 수동 `DELETE FROM passage_fts`(2곳) 제거 — `delete_instance`
  의 row 삭제(또는 FK cascade)가 트리거 발화. merge의 `UPDATE passage_fts`(paper_id/
  title/authors) 제거 — paper_id는 검색 JOIN으로, text 불변이라 재색인 불필요.

### `papermeister/search.py`
- `_run_body`: `passage_fts JOIN passage p ON p.id=passage_fts.rowid`,
  `snippet(...,0,...)`(text=0번), `bm25(passage_fts)`(단일 컬럼).
- `_run_meta`: `paper_fts` 매치(제목·저자) → 본문에 없는 제목어/저자명 recall 보존.
- 본문 결과 dedup 후 paper_fts-only 논문을 matches=[]로 합류. 정렬 키를
  `x['matches'][0]['rank']` → 엔트리 레벨 `x['rank']`로(meta-only는 snippet 없음).
  `_title_tier` 3단 부스트 유지. (desktop `search_service`는 빈 matches 이미 안전 처리.)

### `scripts/migrate_fts_external_content.py` (신규, B1)
dry-run 기본 + `--execute`. 절차: 무결성 검사 → **자동 백업(`VACUUM INTO
*.pre-p13-backup*`, 덮어쓰기 거부)** → DROP 구 FTS → 새 스키마+트리거 생성 →
`rebuild`+paper_fts populate → 무결성 재검 → `VACUUM`(파일 축소). `--no-backup`,
`--no-vacuum` 플래그. **Windows에서 추출 중단 후 실행**(라이브 DB 동시접근 금지).

## 검증 (복구 스냅샷 4.3GB 사본에서 실측)

- 마이그레이션 SQL 실행 2m10s(passage 45만 rebuild), `integrity_check=ok`.
- 트리거: passage insert/update/delete, paper title update, author insert,
  paper delete(cascade 포함) 모두 FTS 반영 확인. **FK cascade도 트리거 발화** 확인.
- 검색: 본문(`passage_fts` JOIN)·제목(`paper_fts`)·**저자-only(`Kobayashi`)** 모두
  정상 — 저자/제목-only recall 보존 입증.
- **VACUUM 후 4.3GB → 2.3GB**. `passage_fts_content`(1.75GB) 소멸, `passage_fts_data`
  0.83→0.61GB(rebuild 압축). 본문 `passage`(1.6GB)가 단일 사본으로 남음.
- 변경 5파일 `py_compile` 통과, dead import 없음.

## ⚠️ recall 변화 (A2로 완화됨)
text-only 색인이라 본문에 없는 어휘는 passage_fts에서 안 잡히지만, `paper_fts`가
제목·저자를 문서 단위로 색인해 그 recall을 복원. 단 paper_fts는 제목+저자만이라,
"제목·저자·본문 어디에도 없는데 매치되길 기대"하는 케이스는 없음(정상).

## 적용 순서 (사용자, Windows)
1. 추출 배치 완전 종료 확인.
2. `python scripts\migrate_fts_external_content.py` (dry-run 미리보기).
3. `python scripts\migrate_fts_external_content.py --execute` (자동 백업 포함).
4. 앱에서 본문·제목·저자 검색 sanity. 문제 없으면 `*.pre-p13-backup` 보관 후 정리.
- 미변환 DB에 새 코드가 닿으면 `init_db`가 명확한 에러로 차단(안전).
