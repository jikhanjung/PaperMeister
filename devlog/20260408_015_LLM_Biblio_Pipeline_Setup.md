# LLM 서지정보 추출 파이프라인 구축

## 작업 내용

P04/P05 계획을 실행하여 서지정보 추출 파이프라인 전체를 구축.

### Step 1: 평가셋 후보 조사

Zotero 출처 + OCR processed + title/year/authors 모두 있는 Paper → **1,661편** 후보.
연도 1900s~2020s 분포, 저널 다양성 (Nature, Science, J. Paleontology 등), CJK 제목 132편.

### Step 2: `papermeister/biblio.py`

- `load_ocr_pages(hash)`: OCR JSON에서 페이지별 markdown 로드
- `extract_first_pages(pages)`: 첫 1~3페이지 결합 (min 1500자, max 6000자)
- `BiblioResult` dataclass: title/authors/year/journal/doi/abstract/doc_type/language/confidence/notes

### Step 3: `papermeister/biblio_eval.py`

GT 대비 추출 결과 비교 메트릭:
- `title_similarity()`: normalize + Levenshtein 유사도
- `authors_score()`: presence(50%) + order(30%) + count(20%) 가중
- `year_match()`, `doi_match()`, `journal_score()`: exact / fuzzy
- `overall_score()`: 가중 평균 (title 35%, authors 30%, year 15%, journal 10%, doi 10%)

메트릭 버그 발견 및 수정:
- 저자 매칭: "Last First"(콤마 없음) 형식 → token set intersection(len≥3)으로 변경
- DOI: 양쪽 빈 값 → True (no penalty)

### Step 4: 평가셋 200편 (`scripts/build_eval_set.py`)

Stratified sampling (seed=42):
- with_journal: 130, no_journal: 30, CJK: 20, old(<1960): 20

### Step 5: Baseline (`scripts/run_baseline.py`)

정규식만으로:
- DOI: 37.5%, Year: 56%, Title: 0% (OCR에 markdown header 없음)
- **overall: 0.139** — LLM이 넘어야 할 바닥선

### Step 6: 모델 평가 (`scripts/run_haiku_eval.py`)

`claude -p --model {model} --output-format json`으로 호출.
200편 full 평가 + 공통 105편 apple-to-apple 비교.

최종 결과 (200편):

| Model | overall |
|---|---:|
| Haiku | 0.879 |
| Sonnet | 0.885 |
| Opus | 0.886 |

→ 세 모델 동률. Phase D는 **Haiku** 결정.

### Step 7: PaperBiblio 테이블

- `PaperBiblio` 모델 추가 (models.py)
- `database.py` 마이그레이션: `needs_visual_review` 컬럼 포함
- 비파괴 원칙: Paper 원본 안 건드림, source 필드로 모델/버전 구분

### Phase D 시작: `scripts/extract_biblio.py`

- `--scope` (all/standalone/directory/missing), `--paper-ids`, `--source-suffix` 옵션
- `--skip-existing` 기본 ON (멱등)
- 20편 smoke test 성공 (13.4s/paper, 에러 0)

## 산출물

| 파일 | 역할 |
|------|------|
| `papermeister/biblio.py` | OCR 로드 + BiblioResult |
| `papermeister/biblio_eval.py` | 메트릭 함수 |
| `scripts/build_eval_set.py` | 평가셋 구축 |
| `scripts/run_baseline.py` | baseline 평가 |
| `scripts/run_haiku_eval.py` | LLM 평가 (모델 지정 가능) |
| `scripts/extract_biblio.py` | 본격 추출 |
| `~/.papermeister/eval_set.json` | 평가셋 paper_ids |
| `~/.papermeister/eval_results_{model}.json` | 모델별 평가 결과 |
