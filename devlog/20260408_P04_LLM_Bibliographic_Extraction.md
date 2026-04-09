# P04: OCR JSON에서 LLM 기반 서지정보 추출

## 배경

OCR 결과(`~/.papermeister/ocr_json/{hash}.json`)의 첫 1~3페이지에는 제목, 저자, 연도, 저널 등의 서지정보가 들어 있다. 그러나 레이아웃이 정형적이지 않고 OCR 노이즈가 있어 정규식으로는 한계가 있다. LLM을 1차 추출기로 사용하되, **이미 정확한 서지정보가 있는 논문들을 ground truth로 활용해 정확도를 측정**하면서 점진적으로 개선한다.

## 핵심 아이디어: Ground Truth 활용

현재 DB에는 두 부류의 Paper가 있다:

| 구분 | 수 | 메타데이터 품질 |
|------|----:|--------------|
| Zotero parent item에서 import (정상) | ~9,500 | **신뢰 가능** (Zotero API에서 가져온 사용자 검수 데이터) |
| Zotero standalone PDF | ~50 | 거의 비어있음 (제목만) |
| Directory source | 3 | PDF 메타데이터만, 빈약 |

**전략**: Zotero에서 가져온 ~9,500편 중 OCR 완료된 것들을 **ground truth**로 사용해 LLM 추출 정확도를 평가한다. 이를 통해:

1. 어떤 LLM/프롬프트가 가장 정확한지 객관적 측정
2. 어떤 케이스(아시아 언어, 책, OCR 노이즈 심한 것 등)에서 약한지 파악
3. 프롬프트/모델 반복 개선
4. 정확도가 충분히 높아진 후 standalone PDF + directory source에 적용

## 단계별 계획

### Phase A: Ground Truth 평가 셋 구축

1. **평가 셋 선정**
   - Zotero 출처 + OCR 완료 + `Paper.title`, `authors`, `year` 모두 채워진 논문 중 무작위 200~300편
   - 다양성 확보: 영어/한국어/중국어, 학술지/책/리포트, OCR 품질 다양
   - `evaluation_set` 테이블 또는 별도 JSON 파일로 관리 (paper_id 리스트)

2. **메트릭 정의**
   - **Title**: normalized exact match (소문자, 공백 정규화) + Levenshtein 유사도
   - **Authors**: 저자 수 일치율 + 순서 보존 + 이름 매칭 (성/이름 분리 고려)
   - **Year**: exact match
   - **Journal**: fuzzy match (약어/풀네임 차이 허용)
   - **DOI**: exact match
   - 종합 점수: 항목별 가중 평균

3. **Baseline**: 정규식/휴리스틱으로 한 번 추출해 baseline 점수 산출

### Phase B: 추출 스키마 및 프롬프트

**스키마 (structured output 강제)**:
```python
{
  "title": str,
  "authors": [str],          # 순서 보존, "First Last" 형식 통일
  "year": int | None,
  "journal": str | None,     # 책이면 publisher
  "doi": str | None,
  "abstract": str | None,
  "doc_type": "article" | "book" | "chapter" | "thesis" | "report" | "unknown",
  "language": str,           # ISO 639-1
  "confidence": "high" | "medium" | "low",
  "notes": str | None        # LLM이 애매했던 점
}
```

**프롬프트 원칙**:
- "추측하지 말고 본문에 명시된 것만" 명시
- 저자 순서 보존 강조 (가장 자주 틀림)
- 책/논문/학위논문 등 doc_type 먼저 판단 후 추출
- 출력은 무조건 JSON tool call

### Phase C: LLM 비교 실험

평가 셋 200~300편에 대해 여러 모델을 돌려 점수 비교:

| 모델 | 예상 비용 (300편) | 강점 |
|------|------------------|------|
| Claude Haiku 4.5 | ~$0.25 | 빠르고 저렴 |
| Claude Sonnet 4.6 | ~$1.5 | 어려운 케이스 정확도 |
| GPT-4o-mini | ~$0.20 | 비교군 |
| (옵션) 로컬 Ollama | $0 | 오프라인 가능성 |

각 모델의 항목별 정확도 + 실패 케이스 분석. **2단계 전략 검증**: Haiku 1차 → confidence='low'만 Sonnet 2차.

### Phase D: 본격 추출

1. 가장 좋은 모델/프롬프트로 OCR 완료된 모든 Paper 처리
2. `asyncio` + Anthropic SDK 비동기 클라이언트, 동시 5~10 요청
3. 캐시: 동일 hash 재실행 방지
4. 재시도/rate limit 처리

### Phase E: 결과 활용

1. **standalone PDF / directory source**: LLM 결과로 `Paper` 필드 채움 (사용자 확인 후)
2. **Zotero 원본 보강**: 비어있는 DOI/journal/abstract만 추가
3. **불일치 리포트**: Zotero ground truth와 LLM 결과가 다른 케이스를 사용자에게 보여줌 → 둘 중 어느 쪽이 맞는지 판단 (Zotero 메타데이터 오류 발견 기회)
4. **검색 인덱스에 abstract 추가**: BM25 점수 개선

## DB 설계

**비파괴 원칙** — `Paper` 원본 필드는 안 건드리고 별도 테이블에 보관.

```python
class PaperBiblio(BaseModel):
    paper = ForeignKeyField(Paper, backref='biblio_extractions')
    title = TextField(default='')
    authors_json = TextField(default='[]')   # JSON list
    year = IntegerField(null=True)
    journal = TextField(default='')
    doi = TextField(default='')
    abstract = TextField(default='')
    doc_type = TextField(default='')
    language = TextField(default='')
    confidence = TextField(default='')
    notes = TextField(default='')
    source = TextField()                     # 'llm-haiku', 'llm-sonnet', 'baseline-regex' 등
    model_version = TextField(default='')
    raw_response = TextField(default='')
    extracted_at = DateTimeField(default=datetime.now)
```

평가 결과 저장용:
```python
class BiblioEvaluation(BaseModel):
    extraction = ForeignKeyField(PaperBiblio)
    title_score = FloatField()
    authors_score = FloatField()
    year_match = BooleanField()
    journal_score = FloatField()
    doi_match = BooleanField()
    overall_score = FloatField()
```

## 산출물

- `papermeister/biblio.py`: LLM 추출 모듈
- `papermeister/biblio_eval.py`: 평가/메트릭 모듈
- `scripts/build_eval_set.py`: 평가 셋 구축
- `scripts/eval_models.py`: 모델 비교 실험
- `scripts/extract_biblio.py`: 본격 추출
- `scripts/biblio_report.py`: 불일치/품질 리포트

## 미결정 사항

- **LLM 제공자**: Anthropic 단독? 로컬 Ollama 검토? → Phase C에서 실측 후 결정
- **평가 셋 크기**: 200 vs 500편 — 200으로 시작 후 부족하면 확장
- **저자 매칭 알고리즘**: 단순 normalize vs 더 정교한 name matching (NameParser 등)
- **Phase E의 사용자 확인 워크플로**: CLI? GUI 대화상자? → 일단 CLI로 시작

## 다음 단계

1. Phase A부터 시작: 평가 셋 200편 선정 + 메트릭 함수 작성
2. Baseline (정규식) 측정으로 비교 기준선 확보
3. Haiku 1회 돌려 첫 점수 확인
