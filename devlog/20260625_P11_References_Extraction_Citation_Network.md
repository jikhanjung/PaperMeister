# P11 — References 섹션 파싱 + 인용 네트워크 (Phase 1)

작성일: 2026-06-25
상태: **계획** (구현 전 설계)
관련: [[P08]] biblio reflection, `papermeister/biblio.py` (LLM 추출 패턴), `papermeister/search.py` (FTS5)

---

## 1. 목표

논문 본문(OCR JSON/마크다운) 맨 뒤의 **references 섹션을 파싱**해서 각 인용 엔트리를 구조화하고,
이를 **내가 보유한 Paper와 매칭**해서 인용 네트워크의 토대를 만든다.

핵심 구분: **PDF를 확보해 보유 중인 논문(held)** vs **단순히 인용만 된 논문(cited-only/external)**.

### 프레이밍 — references는 "파생 레이어"

PaperMeister의 "Store first, understand later" 원칙 그대로다. OCR JSON이 source of truth이고,
references 파싱 결과는 **언제든 재생성 가능한 derived layer**다.

→ PaperBiblio처럼 "모든 모델 버전을 영구 보관"할 필요는 없다. **raw 문자열만 보존**하면
   더 좋은 모델로 자유롭게 재파싱할 수 있다. 재추출은 delete-and-replace(멱등).

### 범위 결정 (2026-06-25 사용자 확정)

- **Phase 1만 먼저**: `Reference` 테이블 + DOI/FTS 해소. intra-library(내 논문↔내 논문)
  네트워크를 즉시 확보. 외부 논문 dedup(여러 논문이 같은 외부 논문 인용 → 한 노드)은
  Phase 2(`CitedWork`)로 분리, 본 계획서 범위 밖.
- **파싱 엔진: ocrserver Qwen3 32B 단독** (`_call_qwen` 재사용). 무료, CJK 강건, 흐름 일관.
- 실행: Windows 데스크톱/스크립트가 ocrserver에 접근 (claude -p 불가).

---

## 2. 작업 분리 (extract ↔ resolve)

기존 `extract_biblio` → `reflect_biblio` 분리 철학과 동일하게 두 패스로 나눈다.

| 패스 | 스크립트 | 역할 |
|------|----------|------|
| **Extract** | `scripts/extract_references.py` | references 섹션 찾기 + 엔트리별 구조화 → `Reference` 행 생성 |
| **Resolve** | `scripts/resolve_references.py` | 파싱된 `Reference`를 보유 Paper에 매칭 (`resolved_paper` 채움) |

둘 다 `--execute` 컨벤션(플래그 없으면 dry-run). desktop 우클릭 "Extract References" 액션도 추가.

---

## 3. 추출(Extract) 상세

### 3a. References 섹션 위치 잡기 — 휴리스틱 (LLM 불필요)

`biblio.load_ocr_pages(file_hash)`로 페이지 마크다운 리스트를 받아 **뒤에서부터** 헤딩 탐색:

```
^#+\s*(references|bibliography|literature cited|works cited|references cited|
       참고문헌|引用文献|参考文献|參考文獻|文献)\b      (case-insensitive)
```

- 헤딩부터 문서 끝까지 잘라냄.
- 단 뒤에 Appendix/Acknowledgments/Supplementary 헤딩이 또 나오면 거기서 끊기.
- **헤딩을 못 찾으면** fallback: 마지막 1~2페이지 전체를 넘기고 `parse_confidence=low`.

→ `biblio.py`에 `extract_references_block(pages) -> str` 신설 (`extract_first_pages` 대칭).

> 주의: 1960s 스캔본·2단 조판은 OCR이 컬럼을 interleave할 수 있음 → 헤딩 미발견 fallback으로 흡수.

### 3b. 엔트리 분할

- **번호형** (`[1]`, `1.`, `1)`): 정규식으로 **결정적 분할** (가장 견고). 분할 후 배치로 LLM 전달.
- **비번호형** (hanging indent / 빈 줄 구분): 분할이 어려우니 **LLM이 분할+파싱 동시에**.

### 3c. LLM 파싱 — `_call_qwen` 재사용

엔트리 묶음(~20–30개)을 청크로 보내 **JSON 배열**로 받음. 각 엔트리 스키마:

```json
{"raw": "원문 그대로", "authors": [{"family":"Smith","given":"J."}],
 "year": 2004, "title": "...", "container": "Ameghiniana",
 "volume": "41", "issue": "", "pages": "123-145", "doi": "10...", "type": "article"}
```

구현 메모:
- `raw`를 **LLM이 그대로 되돌려주게** 강제 → store-first 보존 + audit 가능.
- 없는 필드는 null. **환각 금지** 프롬프트 명시.
- 현재 `_call_qwen`의 `max_tokens: 2048`는 references엔 부족 → 본 호출 전용으로 상향 + 청킹.
- `_parse_llm_json`의 `<think>` 스트립 로직 재사용 (배열 반환용 변형 필요).

> **대안 검토 (기각)**: GROBID는 PDF 레이아웃 분석 기반이라 OCR 마크다운만 가진 구조와 안 맞음.
> AnyStyle(CRF)은 비-CJK엔 좋지만 Ruby 의존 추가 + CJK 약함. 무료 Qwen3 32B가 이미 있고
> 노이즈·CJK에 더 강건 → **LLM-first가 정답**. AnyStyle은 향후 비-CJK cross-check 용도로만 보류.

---

## 4. 저장 — 데이터 모델 (Phase 1)

`PaperBiblio` 비파괴 패턴을 따른다. **`Reference` 테이블 하나만** 추가.

```python
class Reference(BaseModel):
    """citing paper의 references 섹션에서 파싱한 엔트리 1건. 비파괴 derived layer."""
    citing_paper = ForeignKeyField(Paper, backref='references', on_delete='CASCADE')
    order_index  = IntegerField(default=0)      # 서지목록 내 위치 / [n] 번호
    raw_text     = TextField()                   # 원문 — source of truth

    # parsed (Qwen)
    authors_json = TextField(default='[]')       # [{"family","given"}, ...]
    year         = IntegerField(null=True)
    title        = TextField(default='')
    container    = TextField(default='')         # journal/book title
    volume       = TextField(default='')
    issue        = TextField(default='')
    pages        = TextField(default='')
    doi          = TextField(default='')
    ref_type     = TextField(default='unknown')  # article|book|chapter|thesis|...

    # resolution (패스 2에서 채움)
    resolved_paper = ForeignKeyField(Paper, null=True, backref='cited_by',
                                     on_delete='SET NULL')
    match_method   = TextField(default='')       # doi|title|none
    match_score    = FloatField(null=True)

    # provenance
    source         = TextField(default='')       # 'llm-qwen'
    model_version  = TextField(default='')       # 'qwen3-32b'
    parse_confidence = TextField(default='')     # high|medium|low
    extracted_at   = DateTimeField(default=datetime.datetime.now)
```

- `database.py::_migrate()`에 테이블 생성 추가.
- 재추출은 `(citing_paper, source)` 단위 delete-and-replace로 멱등 처리.

### held vs cited 구분 (사용자 핵심 요구)

별도 플래그 불필요 — **"Paper에 연결됐는가"가 곧 구분**:

| 노드 종류 | 판정 |
|-----------|------|
| **held** (PDF 보유) | `Reference.resolved_paper IS NOT NULL` |
| **cited-only** (외부) | `resolved_paper IS NULL` |

(PaperFile.status까지 보면 "보유하지만 OCR 안 된" 것도 추가 구분 가능.)

---

## 5. 해소(Resolve) 상세

각 `Reference`에 대해:

1. **DOI 정확 일치** (최강): 정규화된 DOI를 `Paper.doi` / `PaperBiblio.doi`와 매칭.
2. DOI 없으면 **기존 FTS5 재활용**: 파싱된 title 토큰으로 `passage_fts`(또는 title) 후보 검색
   → year 일치 + 1저자 성(姓) 유사도로 스코어링 → 임계값 넘으면 link, 아니면 external.

- `match_method`(`doi`/`title`/`none`), `match_score` 기록 → 임계값 audit·튜닝 가능.
- 추출과 분리된 재실행 가능 패스 (모델/임계값 바뀌면 재해소만 돌림).

---

## 6. 네트워크 활용 (Phase 1에서 바로 나오는 것)

- **intra-library 인용 그래프**: held → held 엣지 (Gephi용 GEXF/CSV export 또는 in-app)
- **most-cited external works**: 미보유인데 내 컬렉션이 많이 인용 → **"다음에 확보할 논문" 추천**
- **co-citation / bibliographic coupling**: 분류학이면 분류군 클러스터 발견에 유용

### 향후 (범위 밖, Phase 2+)
- **`CitedWork` 정규화 노드**: 외부 논문 dedup → "외부 논문 X를 내 논문 5편이 인용"을 한 노드로.
  most-cited-external·co-citation 분석 정밀화. `Reference.resolved_work` FK 추가.
- **Level 3 citation context**: 본문 in-text `[12]` 마커 ↔ Reference 연결 (Passage 데이터 활용,
  문장 단위 인용 맥락).

---

## 7. 구현 체크리스트 (Phase 1)

- [x] `models.py`: `Reference` 테이블 + `database.py ALL_TABLES` 등록 (create_tables 멱등 생성)
- [x] `biblio.py`: `extract_references_block(pages)` 휴리스틱 (헤딩 탐색 + fallback)
- [x] `biblio.py`: 엔트리 분할(번호형 정규식) + Qwen 배열 파싱 (max_tokens 상향, 청킹, `<think>` 스트립)
- [x] `papermeister/references.py`: `save_references` 공용 저장 헬퍼 (멱등)
- [x] `scripts/extract_references.py` (`--scope`/`--paper-ids`/`--reextract`, `--execute`)
- [x] `scripts/resolve_references.py` (DOI → 토큰 후보 → 스코어, `--threshold`/`--reresolve`, `--execute`)
- [x] desktop 우클릭 "Extract References" — Paper/폴더/My Library 세 레벨 (전용 큐 + `ReferencesWindow`)
- [ ] 검증: 번호형/비번호형/CJK references 각각 소수 샘플로 파싱 품질 확인 (라이브)
- [ ] 검증: DOI 매칭 + title 매칭 정확도, 임계값 튜닝 (라이브)
- [ ] 네트워크 export(GEXF/CSV) 또는 간단 통계(`db_stats.py`에 cited 카운트)

## 7b. 구현 메모 (2026-06-25)

- **저장 헬퍼 분리**: extraction(`biblio.py::extract_references_llm`)과 persistence
  (`references.py::save_references`)를 분리. 스크립트·데스크톱이 같은 매핑 공유.
- **데스크톱 큐는 biblio와 별도**(`_refs_queue`/`_refs_task`/`_refs_window`): references는
  (a) 다른 LLM 호출, (b) Zotero apply 없음(단순 Reference row 저장)이라 biblio 큐
  (`_on_biblio_extracted`의 reflect/apply 로직)와 섞을 수 없음. 진행창 UX는 동일 패턴.
- **백엔드 자동 선택**: `_refs_backend()` — `ocr_pod_url` pref 있으면 qwen, 없으면 claude.
- **UI 트리거 3레벨**: PaperList(`extract_references`, processed/review/done) /
  SourceNav 폴더(`extract_references_folder`) / SourceNav 루트(`extract_references_source`).

### 7c. references 없는 paper 마킹 (사용자 요청, 2026-06-25)

처음엔 "Reference row 존재 여부"로 타겟을 골라서, references 섹션이 없는 paper(0 row)는
매 batch 재파싱 후보로 영원히 재등장하는 문제가 있었음. → **`Paper.references_checked`
(BooleanField) 체크 필드 추가**로 해결.

- **의미**: 추출을 한 번이라도 시도했으면 True (references 있든 없든). Reference row 존재
  여부가 "has refs vs checked-none"를 구분.
- **마이그레이션**: `database.py::_migrate()`가 컬럼 추가 + **이미 Reference row가 있는
  paper를 백필**(첫 run에서 불필요한 재파싱 방지). create_tables가 reference 테이블을 먼저
  만들기 때문에 백필 SELECT 안전.
- **타겟 선정**: `_refs_targets`(desktop) / `fetch_targets`(script) 모두 `references_checked
  == False`인 processed PDF만. `--paper-ids`/`--reextract`는 우회.
- **"no references section"을 실패가 아닌 checked-empty로 처리**: `extract_references_llm`이
  block 미발견 시 ValueError 대신 `[]` 반환(LLM 호출도 생략). ValueError는 OCR 자체가
  없을 때만(진짜 에러 → 재시도). 성공(0건 포함) 시 `references_checked=True` stamp.

### 7d. references 헤딩 다양성 보강 (사용자 지적, 2026-06-25)

references 섹션 제목이 저널·시대·언어마다 천차만별 → 헤딩 목록을 대폭 확장.

- **다국어**: EN(References/Bibliography/Literature Cited/Works Cited/Reference List/
  Selected Bibliography/Cited References/Citations …) + FR(Bibliographie/Références) +
  DE(Literaturverzeichnis/Literatur) + ES(Referencias/Bibliografía) + IT/PT + CJK(참고문헌/
  인용문헌/引用文献/参考文献/參考文獻/参考资料/主要参考文献/文献 …).
- **변형 흡수**: 선행 번호(`5.`/`IV.`), 후행 콜론/마침표, "and Notes"/"and Further Reading"
  접미사. `#{0,6}`로 plain(해시 없는) 라인도 매치(OCR 헤딩은 bold/plain인 경우 많음).
- **오탐 방지**: 줄 전체 앵커(`$`)로 "Literature Review"/"Funding Sources"/"see references
  therein" 등은 거부. 검증: 35종 헤딩 매치 + 8종 비-헤딩 거부.
- **이중 안전망**: 헤딩 미검출 시에도 마지막 2페이지를 LLM에 넘겨(`parse_confidence=low`)
  파싱 시도 → 헤딩 목록이 놓친 케이스도 흡수.

### 7e. ⚠️ 실데이터 검증 → OCR이 HTML-flavored임을 발견 (2026-06-25)

라이브 캐시(`/mnt/c/.../ocr_json`, 9,832개)로 read-only 테스트하다 **OCR `markdown`
필드가 깨끗한 마크다운이 아니라 Chandra2의 HTML(레이아웃 bbox + 시맨틱 레이블)** 임을 발견.
단순 문서는 plain markdown, 복잡 레이아웃은 HTML로 혼재.

```
<div data-bbox="38 273 179 285" data-label="Section-Header"><p>REFERENCES CITED</p></div>
<div data-bbox="38 285 325 825" data-label="Bibliography">
  <p>Balthasar, U., 2004. Shell structure...</p>     ← 레퍼런스 1개 = <p> 1개
  <p>Paterson, J.R., and Brock, G.A., 2007...</p>
</div>
```

→ 초기 마크다운-헤딩 정규식은 실데이터에서 **15편 중 1편만** 잡음(14편 fallback). 수정:
- **`data-label` 시맨틱 레이블 활용**(텍스트 매칭보다 훨씬 신뢰도 높음):
  - `Section-Header` div 텍스트가 references 헤딩 → 그 지점부터
  - `Bibliography` / `List-Group` div = 레퍼런스 영역, **각 `<p>` = 엔트리 1개**(번호 없는
    서지도 완벽 분할). `Bibliography` 레이블은 헤딩 없어도 단독 신뢰.
  - 다음 (non-refs) `Section-Header`에서 종료.
- `_html_to_text`로 태그 제거 + 엔티티 언이스케이프. plain-markdown 경로는 기존 라인 스캔 유지.
  fallback(마지막 2p)도 HTML 제거.
- `split_reference_entries`에 **blank-line 분할** 전략 추가(HTML `<p>`를 `\n\n`로 조인 →
  재분할; 번호형 우선).
- **재검증(30편 랜덤)**: high-confidence **25/30**, fallback 5(그래도 HTML 제거되어 LLM
  투입), 총 2,937 엔트리 추출. 영·불·독·중(尹恭正、李善姬)·한·러 전부 깨끗.
- 코드: `_HTML_HINT_RE`/`_DIV_RE`/`_P_RE`/`_html_to_text`/`_div_entries`/`_extract_refs_html`/
  `_extract_refs_markdown` + `extract_references_block` 디스패치.

### 7f. 라이브 타임아웃 수정 — 청크를 엔트리 개수로 (2026-06-25)

라이브 첫 실행에서 paper 4595(refs 175개)가 `Read timed out (180s)`. 원인: `_chunk_entries`가
**입력 9000자 기준**이라 한 청크에 ~50+ 레퍼런스 → 한 번의 Qwen 호출이 max_tokens(8192)에
가깝게 생성하며 180초 초과.

- `_chunk_entries`에 **`max_entries=15` 추가**(+ max_chars 4500). 호출당 출력 JSON을 ~15개로
  제한 → 175 refs면 12개 청크, 각 호출은 수천 토큰만 생성해 빠르게 반환.
- refs 호출 `max_tokens` 8192→**4096**(15개엔 충분), `_call_qwen`에 connect/read 타임아웃 분리
  `(10, 180)` + **timeout/connection 1회 재시도**(OCR로 서버가 잠깐 바쁠 때 대비).

### 7g. adaptive 배치(slow-start) — 1개부터 측정하며 증감 (2026-06-25, 사용자 제안)

고정 15개 대신 **응답 지연을 측정해 배치 크기를 자가 조정**(TCP slow-start 식). 사용자가
원한 "레퍼런스 1개씩 먼저 보내(1/175, 2/175…) 잘 되는지+시간 보고 늘리기".

- `_AdaptiveBatcher`(MIN 1, MAX 24, 목표대역 20–75s): **size 1로 시작** → 응답 <20s면
  ×2 증가(1→2→4→8→16→24), >75s면 ÷2, 대역 내면 +1. 상태는 **프로세스 전역으로 지속**(CLI·
  데스크톱 모두 refs 추출이 직렬이라 락 불필요) → 워밍업 후 안정 크기로 수렴.
- `extract_references_llm`이 청크 일괄 분할 대신 **루프에서 현재 size만큼 잘라 호출+계측**.
  `max_tokens`도 배치 크기에 비례(`len*256+512`, ≤8192).
- **타임아웃 자가복구**: 호출이 timeout이면 `_call_qwen(retries=0)` → 배처 `shrink()` 후
  **같은 refs를 더 작게 재시도**(MIN에서도 실패하면 진짜 에러). `_call_qwen` 내부 재시도는 0으로
  (큰 size로 2×180s 낭비 방지, 축소가 더 똑똑).
- 진행 로그 `refs N/total: K in T.Ts → next batch B` (스크립트가 INFO 로깅 on).
- 검증: fast→`[1,2,4,8,15]`로 30개 전부, timeout 주입→`[8,4,8,4,4]`로 축소-재시도하며 12개 전부.

### 7h. 20 tok/s 실측 반영 — `raw` 에코 제거 + 튜닝 (2026-06-25)

라이브 실측: **LLM ~20 tok/s**, 호출당 **고정 오버헤드 ~20s**(1 ref 6.7s, 2 ref 24s, 3 ref
25s — 거의 평탄). 의미: (a) 출력 토큰이 비싸다(15 ref가 raw 에코로 ~4500 tok=225s>180s
타임아웃), (b) 고정 오버헤드가 커서 **배치가 클수록 효율적**.

- **`raw` 에코 제거**: 프롬프트에서 `raw` 필드 삭제(원문 통째 재출력 → 출력 ~2배였음). 엔트리는
  우리가 직접 쪼개 보내므로, 응답 객체 수가 입력 수와 같으면 **위치로 `batch[k]`를 `raw`에 매핑**
  (store-first 유지, LLM이 echo할 필요 없음). 불일치 시 필드는 그대로, raw만 빈값(드묾).
  프롬프트에 "원문 echo 금지 / 입력 순서대로 1엔트리=1객체 / 비-레퍼런스도 drop 말고 type unknown".
- **배처 재튜닝**: MAX 24→20, TARGET 25–130s, in-band 증가 +1→**+2**(오버헤드 분산), refs
  read timeout 180→**240s**. → raw 없으면 ~80–130 tok/entry라 20 ref≈2–3k tok≈100–150s로
  240s 안에 안전, 호출당 더 많이 처리해 전체 시간 단축.
- 진단 스크립트 `scripts/probe_qwen.py`: trivial→1ref→5ref 호출 시간 측정(콜드/웜·OCR 경합 구분).

---

## 8. 운영 메모

- 실제 추출은 **Windows native Python(Anaconda) + ocrserver(Qwen3 32B)** 에서 실행.
  WSL/claude는 코드 작성만, 라이브 DB는 read-only 조회.
- 변경 스크립트는 모두 `--execute` (없으면 dry-run).
- Qwen 응답 robustness: `_call_qwen` 호출에 transient 재시도 고려 (biblio 배치의 `_zotero_retry` 참고).
