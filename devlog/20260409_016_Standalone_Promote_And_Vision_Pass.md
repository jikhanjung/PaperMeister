# Standalone PDF Promote + Vision Pass + Journal Issue 처리

## 작업 내용

### 1. Standalone PDF Promote (`scripts/promote_standalone.py`)

Standalone PDF(parent item 없는 Zotero attachment)에 대해:
1. Haiku로 서지정보 추출 → PaperBiblio
2. High confidence만 → Zotero에 새 parent item 생성
3. 기존 PDF attachment를 child로 이동
4. OCR JSON도 sibling child로 업로드
5. DB Paper 갱신 (zotero_key, title, year, journal, doi, authors)

Dry-run 기본 + `--apply`로 실행.

**결과**: 48편 중 high confidence 39편 promote 완료. 에러 0.

### 2. CJK 저자 이름 분리

Zotero creators는 firstName/lastName 분리 필요.
- "堀部純男" → firstName=純男, lastName=堀部 (4글자 한자: 2/2)
- "김진섭" → firstName=진섭, lastName=김 (3글자 한글: 1/2)
- "Smith, John" → firstName=John, lastName=Smith
- "John Smith" → firstName=John, lastName=Smith

pid=242의 4명 저자가 빈 firstName으로 들어간 것을 retroactively 수정.

### 3. needs_visual_review 프롬프트 추가

프롬프트에 `needs_visual_review: bool` 필드 추가.
"표지/TOC 등 시각적 구조가 핵심인 페이지면 true."

15편 테스트 결과:
- 10편 true (실제로 issue 표지 등)
- 5편 false (텍스트만으로 확실한 article)
- **단 5편 중 5편 모두 실제로는 journal issue** → LLM 자가 보고의 한계

### 4. Vision Pass (`scripts/extract_biblio_vision.py`)

1-30 (A5) 컬렉션이 모두 「化石」 학술지 호별 PDF라는 사실 발견.
기존에 article로 잘못 promote된 것을 vision pass로 재처리.

**구현**:
- PyMuPDF로 첫 페이지 + 마지막 페이지 PNG 렌더 (150 DPI)
- `claude -p --allowed-tools Read`로 이미지 경로 전달 → Claude vision
- doc_type에 `journal_issue` 추가
- issue, publication_date, table_of_contents 필드 추가

**Haiku vision vs Sonnet vision**:
- Haiku: 일본어 OCR 부정확, TOC 환각, 연도 불일치 (1984 ↔ 1978)
- Sonnet: 일본어 정확, TOC 완벽, 연도/날짜 정확

→ **CJK vision은 Sonnet 필수**

### 5. In-place Update (`scripts/update_promoted_items.py`)

잘못 promote된 item을 Zotero에서 in-place 수정:
- `zot.item_template(new_type)`으로 새 타입의 valid 필드 세트 확보 → 이전 타입 잔여 필드 제거
- key/version/collections/tags 보존
- attachment인 경우 (미promote) → 자동으로 promote 로직으로 fallback

**적용 결과**:
- 1-30 (A5): 28편 → 化石 第1号~第30号 journal_issue (document 타입)
- 31-71 (B5): 31편 → 化石 第31号~第71号 journal_issue

### 6. Zotero Sync 개선

`get_collection_items()`가 PDF attachment만 수집하던 것을 **모든 attachment 타입으로 확장**.
- JSON attachment도 이제 PaperFile로 들어옴 (status='processed')
- DB 재구성 시 JSON 관계 누락 문제 해결

## 산출물

| 파일 | 역할 |
|------|------|
| `scripts/promote_standalone.py` | Standalone → Zotero parent 생성 |
| `scripts/extract_biblio_vision.py` | Vision pass 서지 추출 |
| `scripts/update_promoted_items.py` | 기존 parent in-place 수정 |
| `scripts/preview_standalone_biblio.py` | 추출 결과 미리보기 |

## 교훈

- Zotero에 journalIssue itemType이 없음 → document 사용
- itemType 변경 시 `item_template()` 필수 (이전 타입 필드 잔류 → 400 에러)
- LLM의 needs_visual_review 자가보고는 부분적 — OCR 텍스트가 깨끗하면 wrong confidence=high 가능
- Vision pass는 비싸지만 journal issue 같은 예외적 케이스에서 유일한 해결책
- 파일명 패턴(숫자 시퀀스)이 issue collection의 가장 강한 사전 신호
