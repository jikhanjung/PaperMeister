# 025: Detail Tabs + OCR Markdown + Search Wiring + FTS 버그 수정

[024](./20260412_024_Desktop_Shell_Polish_Rail_SourceNav_Chevrons.md)에서 데스크탑 앱 쉘을 Windows에서 처음 실행하고 기본 UI 버그들을 정리했다. 그 다음 단계로 **상세 패널을 탭 구조로 재작성**하고 **OCR 마크다운 렌더링**을 붙이고 **검색창을 실제로 동작**하게 만든 세션. 중간에 FTS5 limit 버그와 markdown 들여쓰기 폭주 버그 두 개가 덤으로 튀어나왔다.

## 1. DetailPanel 탭 구조로 재작성

### 동기

기존 `DetailPanel`은 `QScrollArea` 안에 카드 3개(Metadata / Extracted Biblio / File)를 세로로 쌓은 구조였다. 단순하지만 몇 가지 문제:

- 논문 본문(OCR 결과)을 보여줄 자리가 없다. 추가하면 다른 카드와 함께 같은 스크롤 컬럼에 들어가서 스크롤이 길어지고, 본문 보려고 매번 아래까지 내려야 한다.
- "서지 정보 보고 싶다" vs "본문 뒤져보고 싶다" vs "파일 상태 확인하고 싶다"가 서로 다른 사용 맥락인데 스크롤 한 컬럼에 뭉쳐 있으면 맥락 전환이 비쌈.
- Stub 배너가 스크롤 컨텐츠 내부에 있어서 아래로 스크롤하면 사라짐 — "이 논문이 stub이다"라는 경고가 맥락 놓치는 순간 사라지는 건 설계 실수.

### 구조

```
┌─ DetailPanel (QWidget) ─────────┐
│ [Stub banner] (optional, fixed) │
│ [Metadata | Biblio | OCR] (tabs)│  ← QTabWidget#DetailTabs
│ ┌────────────────────────────┐  │
│ │ tab content                │  │
│ │ (each tab has own          │  │
│ │  independent QScrollArea)  │  │
│ └────────────────────────────┘  │
└─────────────────────────────────┘
```

`DetailPanel`이 `QScrollArea`를 상속하던 걸 `QWidget`으로 바꾸고, 각 탭이 자기만의 scroll area를 감싸도록 했다. 이러면 탭별로 스크롤 위치가 독립적으로 유지된다 (Biblio 탭에서 아래까지 스크롤했다가 OCR 탭 갔다가 돌아와도 위치 보존).

### 세 탭의 역할

- **Metadata 탭** — 기존 METADATA + FILE 카드. 항상 채워짐.
- **Biblio 탭** — `PaperBiblio` 있으면 EXTRACTED BIBLIO 카드 + Apply 버튼. 없으면 *"No biblio extracted yet. Run scripts/extract_biblio.py for this paper."* empty state.
- **OCR 탭** — 논문 본문. 처리 상태에 따라 empty state 분기 (자세한 건 §2).

### 탭 상태 보존

`show_paper()`를 호출할 때 현재 선택된 탭 인덱스를 기록해두고, 새 논문 로드 후 같은 인덱스로 복원한다. 논문 목록에서 여러 논문을 클릭하며 OCR 본문을 비교할 때 매번 Metadata 탭으로 스냅백되지 않는다.

```python
current_idx = self._tabs.currentIndex() if self._tabs.count() > 0 else 0
self._tabs.clear()
# ... rebuild tabs ...
if 0 <= current_idx < self._tabs.count():
    self._tabs.setCurrentIndex(current_idx)
```

### Stub 배너

탭바 위에 고정 QLabel로 올렸다. `hide()/show()` 토글만으로 stub 여부를 반영하고, 탭 전환해도 경고가 사라지지 않는다. 이전처럼 스크롤되어 사라지지 않음.

### QSS

`#DetailTabs`의 탭바 스타일을 `#SourceTabs`와 같은 규칙으로 묶어서 Zed/Linear 스타일 2px accent blue 밑줄을 재사용. 코드 중복 대신 CSS 선택자에서 `,`로 연결:

```
#SourceTabs QTabBar::tab:selected, #DetailTabs QTabBar::tab:selected {
    color: {text.primary};
    border-bottom: 2px solid {accent.primary};
}
```

## 2. OCR 탭 — QTextBrowser.setMarkdown

### 데이터 소스

`papermeister/biblio.py::load_ocr_pages(file_hash)`가 이미 존재했다. `~/.papermeister/ocr_json/{hash}.json`을 읽어서 페이지별 markdown 문자열 리스트를 반환. biblio 추출 파이프라인에서 쓰고 있던 걸 그대로 재사용.

### 렌더러

`QTextBrowser.setMarkdown()` — Qt 5.14+에 내장된 markdown 파서. 헤딩/볼드/이탤릭/링크/수평선/리스트/테이블까지 기본 지원. 외부 라이브러리 불필요. 수식(LaTeX)/이미지는 지원 안 함이지만 OCR 본문 미리보기 용도로는 충분.

### 페이지 조립

원본은 페이지 배열 (`list[str]`). 한 논문 = 한 문서로 이어붙이되 페이지 경계를 시각적으로 보여야 한다. 선택:

```
*— page 1 —*

{page 1 content}

---

*— page 2 —*

{page 2 content}
```

`*— page N —*`는 이탤릭 마커, `---`는 수평선. 페이지 내부에 진짜 `#`/`##` 헤딩이 있어도 충돌 안 함 (같은 레벨 헤딩을 만들지 않으므로).

### Empty state 분기

처리 상태별로 서로 다른 메시지:

- `file_hash` 없음 → "No file hash on this paper. OCR cache is keyed by file hash."
- `file_status != 'processed'` → "This paper has not been OCR-processed yet (status: X). Run the Process action to OCR it."
- 캐시 파일 없거나 비어있음 → "OCR cache file missing or empty. Expected: ~/.papermeister/ocr_json/{hash[:16]}….json"

사용자가 OCR 탭 열었을 때 빈 화면이 나오면 "왜 안 보이지"가 되지만 구체적 이유가 나오면 바로 행동 지침이 된다.

## 3. OCR 마크다운 들여쓰기 폭주 버그 — 두 번의 시도

"OCR 탭에서 텍스트가 계속 오른쪽으로 붙는 경우가 있다"는 사용자 리포트. 원인 추적이 두 단계로 진행됐다.

### 3.1 첫 번째 원인 — numbered list cascade

20개 OCR JSON 파일을 스캔해 markdown 패턴 빈도를 조사:

```
leading_spaces_4plus     :   1310 hits
numbered_list            :    506 hits
bullet_dash              :     52 hits
bullet_star              :     30 hits
indented_numbered        :     52 hits
```

- **1,310줄이 4칸 이상 leading space로 시작** → markdown에서 indented code block으로 해석 → 왼쪽 여백 + monospace 폰트. OCR이 테이블/수식/컬럼 간격을 공백으로 표현하는 것들이 전부 코드 블록으로 변함.
- **506줄의 `숫자. text` 패턴** → `<ol><li>`. 논문은 plate caption, reference, abstract numbering으로 이런 줄이 수백 개. 이들이 전부 Qt의 markdown 렌더러에 들어가서 각각 `qt-list-indent` 속성이 붙은 `<ol>` 블록을 만듦.

첫 수정안: `_sanitize_ocr_markdown()` 헬퍼 신설. 두 가지를 함:

1. **모든 줄에 `lstrip()`** — leading whitespace 전부 제거. 코드 블록 해석 차단.
2. **`^(\d+)\.\s` 패턴을 backslash escape** (`1. foo` → `1\. foo`). Qt의 markdown 파서에서 `\.`는 literal period로 해석되어 리스트 마커 인식을 스킵. 렌더된 최종 텍스트엔 backslash가 보이지 않음.

그 외:
- Bullets (`- `, `* `)는 건드리지 않음 — Chandra2가 bullet-looking 줄을 잘 안 만들어서 false-positive 위험이 더 큼.
- 3+ 연속 blank line을 2로 collapse — 가독성.

검증:

```
raw       <ol>=34  <li>=74
clean     <ol>=0   <li>=12
```

34개 `<ol>` 블록이 0으로 줄었다. 남은 12개 `<li>`는 `<ul>` 안의 진짜 bullet들. 문제 해결된 것 같았다.

### 3.2 두 번째 원인 — 레퍼런스 섹션에서 `-qt-list-indent`가 1→4로 누적

사용자가 *"Life-History and the Evolution of Ontogeny in the Ostracode Genus"* 논문의 references에서 "계속 오른쪽으로 붙는다"고 구체적 리포트를 보냄. 이 논문을 찾아서 references 페이지를 렌더 전후 비교.

**수정 후에도 여전히** 해당 페이지에 `<ol>`이 8개 남아있었다. 그리고 결정적 — 각 `<ol>`의 `-qt-list-indent` 값이:

```
-qt-list-indent: 1   (첫 번째)
-qt-list-indent: 1
-qt-list-indent: 2   ← 올라감
-qt-list-indent: 3
-qt-list-indent: 3
-qt-list-indent: 4   ← 계속 올라감
```

Qt의 markdown 파서가 인접한 OL들을 **nesting**으로 해석하고 있었다. 그래서 시각적으로는 리스트가 계단식으로 밀리는 것처럼 보임. 이게 사용자가 본 "계속 오른쪽으로 붙음"의 실체.

무엇이 OL을 여전히 만들고 있는가? Sanitized 본문을 출력해봤다:

```
BODERGAT, A. M. 1983. Les ostracodes, témoins de leur environnement...

Documents du Laboratoire Géologique de Lyon

88.

BOLD, W. A. VAN DEN. 1963. Upper Miocene and Pliocene Ostracoda of Trinidad.

Micropaleontology

9:361-424.
```

볼륨 번호가 **단독으로 한 줄**에 있다 — `88.`, `158.` 등. 첫 수정의 regex `^(\d+)\.\s`는 trailing whitespace(`\s`)를 요구해서 `88.`처럼 **점 뒤에 아무것도 없는 줄은 매치 안 됨**. 그런데 CommonMark 스펙은 `88.` 단독으로도 `start=88`인 빈 ordered list로 파싱한다.

레퍼런스 섹션은 이런 `볼륨번호.` 줄이 10~20개 연달아 나오고, Qt가 이들을 nested로 해석하면서 indent가 누적됨.

두 번째 수정: regex 완화

```python
# before
ol_re = re.compile(r'^(\d+)\.\s')

# after
ol_re = re.compile(r'^(\d+)\.')
```

trailing whitespace 요구를 제거해서 **줄 시작의 모든 `숫자.` 패턴**을 escape 대상으로 만듦. `88.`, `1.`, `12-14.` 외의 모든 형식 포함. 시각 렌더는 동일 (`88\.` → `88.`), 파서가 리스트로 인식할 여지만 차단.

검증 재실행 — ostracode references 페이지:

```
<ol>=0   <li>=0   qt-list-indent=0
```

전부 0. 다른 논문들도 재검증:

| 페이퍼 | 수정 전 `<ol>` | 수정 후 `<ol>` |
|--------|---------------|---------------|
| Ostracode references (문제 페이지) | 8 (indent 1→4 누적) | 0 |
| Plate caption 논문 | 34 | 0 |
| 단순 numbered abstract | ~9 | 0 |

남은 `<li>`는 전부 `<ul>` 안의 bullet, 누적 indent 안 만듦.

## 4. 검색창 wiring + FTS5 limit 버그

### 4.1 wiring

기존 `SearchBar`는 placeholder만 달린 `QLineEdit`. 세 가지 시나리오를 연결:

1. **Enter (returnPressed)** — `query = text.strip()`; 비었으면 이전 nav 뷰 복원, 아니면 `paper_list.load_search(query)`.
2. **Clear (textChanged → empty)** — X 버튼 또는 backspace 전체 삭제. 이전 nav 뷰 자동 복원. "검색 취소하면 원래 보던 화면으로"를 자동화.
3. **Nav 클릭** — 좌측 탭에서 폴더/필터 클릭 시 search bar를 clear. `blockSignals`로 감싸서 textChanged 재진입(=library 이중 로드) 방지.

`_current_selection`을 트래킹하고 `_apply_current_selection()` 헬퍼로 세 nav 유형(library/source/folder)에 디스패치. Enter로 검색 → 결과 → 검색창 Clear 하면 원래 뷰로 돌아가는 사이클이 한 객체 상태(`_current_selection`)로 깔끔하게 관리됨.

### 4.2 `search_service.py`

`papermeister/search.py::search()`가 이미 존재하고 FTS5 BM25 (title ×10, authors ×5, text ×1) 가중치까지 구현돼 있었다. 얇은 어댑터만 만들어서 결과를 `PaperRow`로 변환:

```python
def search_papers(query: str, limit: int = 200) -> list[PaperRow]:
    if not (query := (query or '').strip()):
        return []
    results = core_search.search(query, limit=limit)
    rows: list[PaperRow] = []
    for entry in results[:limit]:
        paper = entry['paper']
        source_name = ''
        try:
            if paper.folder_id is not None and paper.folder is not None:
                src = paper.folder.source
                if src is not None:
                    source_name = src.name
        except Exception:
            source_name = ''
        rows.append(_row_from_paper(paper, source_name))
    return rows
```

`_row_from_paper`는 `paper_service.py`에서 재사용. 검색 결과가 library 뷰와 정확히 같은 `PaperRow` 타입으로 흘러가서 `PaperListView._populate()`가 분기 없이 공통 처리.

### 4.3 FTS5 limit 버그 — 4 vs 1031

End-to-end 테스트하다가 이상 발견: `trilobite` 검색에 결과가 **4편**. 전체 코퍼스는 고생물학 논문 9천 편, title에 "trilobite"가 들어간 논문만 1,281편. 4편은 말이 안 됨.

DB 진단:

```
PaperFile.status==processed:      4,494
Passage rows:                   858,249
passage_fts rows:             1,290,702
passage_fts distinct paper_ids:   2,252
passage_fts MATCH 'trilobite':    75,956 rows
  → distinct paper_ids:            1,031
Papers with 'trilobite' in title:  1,281
```

FTS는 75,956개 passage가 `trilobite`에 매치되고 그게 1,031편의 distinct paper를 커버하는 상태. 그런데 `search()`는 4편만 반환.

원인: `papermeister/search.py`의 SQL이 **LIMIT을 passage row 단위에 건다**.

```sql
SELECT paper_id, page, passage_id, snippet(...), bm25(...) as rank
FROM passage_fts WHERE passage_fts MATCH ?
ORDER BY rank LIMIT 50
```

`trilobite`같이 밀도 높은 키워드는 **상위 50 passage가 소수 논문에 clustering** — paper 1058 하나에 수십 개의 높은 점수 passage가 몰려 있으면 top 50 중 절반 이상을 차지해버린다. Python 레벨에서 paper_id로 dedupe하면 최종적으로 4편만 남음.

내 wrapper가 `limit=200`으로 올려도 같은 문제. 상위 200 passage도 clustering 성질은 그대로.

### 4.4 FTS5 bm25 aggregate 제약

첫 해결 시도: SQL에서 `GROUP BY paper_id` + `MIN(bm25(...))`.

```sql
SELECT paper_id, MIN(bm25(passage_fts, 10.0, 5.0, 1.0)) as best_rank
FROM passage_fts WHERE passage_fts MATCH ?
GROUP BY paper_id ORDER BY best_rank LIMIT ?
```

실행 → `OperationalError: unable to use function bm25 in the requested context`.

FTS5의 `bm25()`는 **auxiliary function**이고, aggregate 내부나 서브쿼리 아래 컨텍스트에서 호출 불가. CTE로 먼저 materialize 후 GROUP BY 시도해도 같은 에러. 이건 SQLite FTS5의 구조적 제약.

### 4.5 해결 — Python dedupe

그냥 모든 매치 passage를 BM25 순으로 페치해서 Python에서 dict dedupe. 벤치마크:

| 쿼리 | passage 행 | distinct 논문 | SQL+dedupe |
|------|-----------|---------------|-----------|
| `trilobite` | 75,956 | 1,031 | 0.18s |
| `carbon isotope` | 2,023 | 128 | 0.03s |
| `Ordovician` | 82,809 | 914 | 0.24s |

충분히 빠르다. 7만 행 페치가 0.17s면 UX에 문제 없음.

`papermeister/search.py` 수정:

1. **`limit` 파라미터 의미 변경**: "passage 행 수" → **"distinct paper 수"**. 주석에 명시해서 향후 혼동 방지.
2. **새 `max_passages=200_000` 파라미터**: 극단적 광역 쿼리의 안전 상한. 일반 쿼리는 이 한계 근처도 안 감.
3. **dedupe 로직**: 딕트 기반, 첫 등장 = best rank (결과는 이미 rank 정렬됨). `limit`개의 distinct paper를 모으면 새 paper 추가 중단, 기존 paper 스니펫은 계속 수집 (paper당 최대 5개).

수정 후 재테스트: `trilobite` → **200편** (limit). 의도한 결과.

### 4.6 BM25 tie-break 이슈 (별도 관찰)

수정 후 `trilobite` 상위 결과가 흥미로움:

```
rank=-5.842 Comparative analyses of animal-tracking data...
rank=-5.842 A practical implementation of the box counting algorithm
rank=-5.842 Studies on Trilobite Morphology, Part II...
```

세 paper가 동률. "Studies on Trilobite Morphology"는 제목 매치지만, "Comparative analyses of animal-tracking data"는 title에 trilobite가 없는데 top에 올라와 있다. 본문에 `trilobite`가 엄청 많이 나와서 BM25 점수가 높은 듯.

`passage_fts`가 **passage 단위 인덱스**라 필드 가중치(title ×10)가 한 passage 내부에서만 작용한다. "title에 정확히 나왔다"는 document-level boost를 이 구조로는 표현하지 못함. 제대로 구현하려면:

- `passage_fts` 외에 title/authors 전용 `paper_fts` 분리 → BM25 점수를 합산
- 또는 post-processing으로 title exact match boost를 Python에서 얹기

이건 Phase 5(hybrid search) 주제. 지금은 기록만 해두고 넘어감.

## 배운 점

### QTextDocument의 markdown 파서는 CommonMark-ish 하지만 공격적이다

OCR 본문처럼 **markdown으로 설계되지 않은 텍스트**를 넘기면 예상 못한 구조를 만들어낸다. 특히 ordered list는 매우 공격적으로 인식된다 — 줄 시작의 `숫자.`는 거의 무조건 list marker로 해석되고, 점 뒤에 내용이 없어도 (`88.`) 빈 item을 만들고, 인접한 list들이 특정 조건에서 nested가 된다.

교훈: **사용자가 작성한 markdown**이 아닌 **OCR/자동 추출 텍스트**를 `setMarkdown()`에 넘길 땐 sanitization layer가 필수. "그냥 markdown이니까 표시하면 되겠지"는 위험한 가정.

다음번에 구조화되지 않은 텍스트를 markdown 렌더에 넣을 일이 생기면:
1. 먼저 20개 샘플에 대해 패턴 빈도 조사 (`grep -E '^(\d+)\.'` 같은 것들)
2. 렌더 결과의 HTML을 dump해서 예상치 못한 tag가 나오는지 확인
3. **둘 중 하나라도 문제 있으면 sanitization 추가**

### 첫 수정은 종종 두 번째 수정을 부른다

OCR indentation 버그의 두 단계:

1. 첫 수정: `^(\d+)\.\s` — "공백 요구" → 가장 명백한 `1. text` 패턴 해결 → 34개 `<ol>`이 12개로 줄어듦 → "해결된 것처럼 보임"
2. 사용자 리포트로 **같은 증상의 다른 원인** 발견 → `88.` 같은 bare 볼륨 번호 → regex 완화 → 0으로 떨어짐

첫 수정 후 "다 고쳤다"고 완료 선언했으면 사용자가 구체 케이스(Ostracode references)를 알려주지 않았을 것이고 — 그래도 같은 증상이 계속 났을 것이다. 둘의 차이: 첫 번째는 *눈에 띄는 리스트* 를 없앤 거고, 두 번째는 *진짜 누적 버그* 를 없앤 거.

교훈: **"텍스트가 오른쪽으로 붙는다"** 같은 **시각 증상**은 복수 원인일 수 있다. "A를 고쳤으니 됐다"가 아니라 "A를 고친 후 증상이 *남아있는지* 재검증"이 맞다. Visual regression 테스트가 있으면 좋겠지만 지금은 사용자 피드백이 그 역할을 함.

그리고 "Life-History and the Evolution of Ontogeny in the Ostracode Genus"처럼 구체 논문 제목을 주는 사용자 리포트는 금이다 — "이런저런 논문에서 그런 경우가 있어"보다 10배 빠르게 원인에 도달하게 한다.

### FTS5 auxiliary function은 인라인에서만 쓸 수 있다

`bm25()`, `snippet()`, `highlight()` 같은 FTS5 auxiliary function은 **MATCH 절이 있는 바로 그 SELECT**에서만 호출 가능. aggregate(`MIN`, `MAX`, `AVG`) 안, 서브쿼리 바깥, CTE 뒤 — 전부 `unable to use function bm25 in the requested context` 에러.

우회 경로:
- **cursor iteration + Python dedupe** — 이번 선택. 간단하고 충분히 빠름.
- **Python UDF로 bm25 재구현** — FTS5 raw 통계 노출이 복잡, 권장 X.
- **별도 테이블에 rank 미리 저장** — 쿼리 대역이 방대할 때만 의미 있음.

"SQL로 깔끔하게 처리할 수 없는 건 그냥 Python에서 처리"는 이 경우 과소평가할 일이 아니다. SQLite는 7만 행 페치가 0.2s고 Python dict 연산은 마이크로초 단위라, 중간 복잡도의 데이터 변환은 Python이 거의 항상 승자.

### limit 파라미터의 의미는 문서화 해야 한다

기존 `search(query, limit=50)`의 `limit`이 **"passage row 개수"**였는데 사용자는 (그리고 나도) **"결과 논문 개수"**로 읽고 있었다. 함수 시그니처만 보면 해석의 여지가 있고, 실제로 밀도 차이에 따라 둘이 크게 달라질 수 있는 상황이었다.

이번 수정에서 docstring에 명시:

```python
def search(query, limit=50, max_passages=200_000):
    """...
    `limit` is the maximum number of **distinct papers** to return, not the
    number of passages. Prior to 2026-04-12 this was a passage-row limit,
    which meant dense queries (e.g., "trilobite" with ~75k hits) silently
    collapsed to a handful of papers because the top passages clustered on
    a few documents. ...
    """
```

향후 FTS 관련 함수를 수정하면서 이 docstring을 읽는 사람이 "왜 이렇게 복잡하게 처리하지"라고 의심하지 않게 **버그 배경을 날짜까지 적어서** 박아둠. 주석이 archaeology를 가능케 한다.

## 관련 문서

- [024 Desktop 쉘 손보기](./20260412_024_Desktop_Shell_Polish_Rail_SourceNav_Chevrons.md) — 오늘 오전, 같은 desktop 앱의 쉘 레벨 버그 수정
- [P09 Desktop UI 설계](./20260411_P09_New_Desktop_UI_Design.md) — 탭 구조와 카드 레이아웃의 근거
- [023 Phase 2 뒷정리](./20260411_023_Phase2_Cleanup_And_Needs_Review_Helper.md) — Biblio tab의 Apply 버튼이 가리키는 reflection runner
