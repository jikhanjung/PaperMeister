# P05: 서지정보 추출 — 단계별 실행 계획

P04의 Phase A~C(평가/측정 단계)를 작은 작업 단위로 쪼갠 실행 계획.

## Step 1 — 평가 셋 후보 쿼리

**목적**: 평가에 사용할 수 있는 "신뢰 가능한 메타데이터를 가진 OCR 완료 논문"이 몇 편이나 되는지 확인.

**조건**:
- Zotero 출처
- PDF PaperFile이 `processed`
- `Paper.title`, authors, year 모두 채워져 있음
- OCR JSON 파일이 디스크에 존재 (`~/.papermeister/ocr_json/{hash}.json`)

**산출물**: 후보 수, 언어/연도/저널 분포 간단 통계

## Step 2 — `papermeister/biblio.py` 골격

**목적**: LLM 호출 전까지의 입력 준비 인프라.

- `load_ocr_pages(hash) -> list[str]`: OCR JSON에서 페이지별 markdown 리스트
- `extract_first_pages(pages, max_chars=6000) -> str`: 첫 1~3페이지 합쳐서 자르기 (너무 짧으면 다음 페이지 포함)
- `BiblioResult` dataclass: title/authors/year/journal/doi/abstract/doc_type/language/confidence/notes

**LLM 호출은 아직 X**.

## Step 3 — `papermeister/biblio_eval.py` 메트릭

**목적**: ground truth와 추출 결과를 비교하는 함수들.

- `normalize_title(s)`: 소문자, 공백 정규화, 구두점 제거
- `title_similarity(a, b) -> float`: Levenshtein 기반 0~1
- `authors_score(gt, pred) -> float`: 순서 보존 + 이름 매칭
- `year_match(gt, pred) -> bool`
- `journal_score(gt, pred) -> float`: fuzzy
- `doi_match(gt, pred) -> bool`
- `overall_score(gt, pred) -> dict`: 항목별 + 가중 평균

**단위 테스트**: 정상/공백/대소문자/약어/순서 변경 등 케이스 5~10개.

## Step 4 — `scripts/build_eval_set.py`

**목적**: 평가셋 paper_id 리스트를 고정.

- Step 1의 쿼리 + 무작위 추출 (시드 고정)
- 크기 옵션 (`--size 200`)
- 출력: `~/.papermeister/eval_set.json` `{"seed": 42, "paper_ids": [...]}`
- 재현 가능 — 같은 시드는 같은 결과

## Step 5 — Baseline (정규식/휴리스틱)

**목적**: LLM 없이도 얼마나 추출되는지 기준선.

- DOI 정규식: `10\.\d{4,9}/[-._;()/:A-Z0-9]+`
- 연도 정규식: `(19|20)\d{2}` (첫 페이지에서 가장 빈도 높은 것)
- title은 첫 markdown 헤더 시도
- authors는 휴리스틱 어렵 → 빈 값
- 평가셋에 돌리고 항목별 점수 산출

## Step 6 — Haiku 1회 실험

**목적**: 첫 LLM 결과 측정.

- `scripts/eval_models.py --model haiku`
- structured output 사용 (Anthropic tools)
- 평가셋 200편 처리, 결과를 `PaperBiblio` 테이블에 저장 (source='llm-haiku')
- 메트릭 산출 → baseline과 비교
- **실패 케이스 상위 10개 수동 확인** (어떤 패턴에서 약한지)

## Step 7 — 결정 포인트

다음 중 선택:
- **A. Haiku로 충분** → P04 Phase D (본격 추출) 진행
- **B. 프롬프트 개선 필요** → Step 6 재실행
- **C. 더 강한 모델 필요** → Sonnet 비교 또는 2단계 전략 (Haiku → low confidence만 Sonnet)
- **D. 케이스별 분기** → 책/논문/한국어 등 doc_type별 별도 프롬프트

---

## 진행 순서

1. Step 1 (지금)
2. Step 2 + Step 3 (코드 작성, 작은 단위)
3. Step 4 → 평가셋 고정
4. Step 5 → baseline 점수
5. Step 6 → Haiku 점수
6. Step 7 → 다음 결정
