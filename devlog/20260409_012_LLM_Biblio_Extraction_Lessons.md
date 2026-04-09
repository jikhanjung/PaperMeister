# LLM 서지정보 추출 — 작업하면서 배운 것들

P04/P05 계획에 따라 LLM(Haiku/Sonnet/Opus)으로 OCR JSON에서 서지정보를 추출하고, 일부는 Zotero에 parent item으로 push하는 작업을 진행하면서 발견한 것들 정리.

## 1. 모델 선택

### 1.1 세 모델 사실상 동률
공통 105편 평가셋에서:

| Model | overall |
|---|---:|
| Haiku 4.5 | 0.921 |
| Sonnet 4.6 | 0.924 |
| Opus 4.6 | 0.924 |

→ **차이 0.003 이내**. 비용/속도 5~10배 차이를 정확도 1%p로 정당화 못 함. **서지 추출은 Haiku로 충분**.

### 1.2 약점 항목 (모두 비슷)
title/authors는 0.93+로 우수. year ~0.88, journal ~0.76, doi ~0.79는 모두 모델 무관하게 약함. 즉 **본문에 명시된 정도의 한계**이지 모델 능력 한계가 아님.

### 1.3 Haiku의 CJK 번역 경향
- Haiku는 한국어/일본어 제목을 영어로 번역하거나 한자를 한글/로마자로 변환하는 경향이 있음
  - 예: "불국사 조산운동…" → "Geochemical evolution of the dyke swarm…"
- Sonnet/Opus는 원본 표기를 보존
- 프롬프트에 "Preserve the original script and language exactly as printed" 명시 필요

## 2. 메트릭 함정

### 2.1 한자 ↔ 한글 ↔ 영어 표기 차이
같은 논문이 다른 표기로 저장되어 있으면 string distance metric이 0에 가까운 점수를 줌.
- Zotero GT: `남극 King George Island 조사`
- LLM 추출: `Korean Antarctic Search Expedition 1985/1986`
- → 같은 논문이지만 score=0.18

평가셋의 CJK 케이스 20편을 비CJK 180편과 분리하면:
- 비CJK overall: **0.913**
- CJK overall: 0.579

LLM 자체는 정확한데 metric이 문제. **성능 평가 시 CJK는 별도 트랙으로 보거나 ground truth를 normalized 형태로 받아야 함.**

### 2.2 저자 이름 형식 다양성
Zotero에서 author를 어떻게 join하느냐에 따라 `'Last First'`(콤마 없음), `'First Last'`, `'Last, First'`, 이니셜 등이 섞임. 단순 split으로는 매칭 실패가 많음. 해결: token set intersection (length≥3) — 순서 무관, 형식 무관.

### 2.3 GT가 비어있을 때 0점 처리 함정
GT DOI가 없는데 LLM도 안 뽑은 경우 → 사실은 '페널티 없음'이 맞는데 metric이 0점 처리해서 평균 깎임. 수정: `not gt and not pred` → 1.0 (매칭으로 간주).

## 3. 비파괴 데이터 모델

### 3.1 PaperBiblio 별도 테이블
LLM 추출 결과를 `Paper`에 직접 덮어쓰지 않고 `PaperBiblio`로 보관:
- 여러 모델/버전(`source` 필드: `llm-haiku`, `llm-haiku-v2`, `llm-sonnet-vision`)을 동시 보관
- 비교/재처리 가능
- 사용자 검토 후 promote하는 워크플로
- 잘못 추출된 케이스 발견 시 원본 `Paper` 손상 없음

이 결정이 작업 후반부에 매우 유용했음 — 1-30 (A5) 컬렉션 misclassification을 vision pass로 재시도할 때 PaperBiblio에 두 결과를 동시에 두고 비교 가능했음.

## 4. Vision Pass와 한계

### 4.1 텍스트 only가 놓치는 케이스
일부 PDF는 시각적 구조가 본질적인 정보를 담고 있음:
- **journal issue 표지**: 잡지명(상단) + TOC(중앙) + 호수/연월(하단). OCR이 텍스트로 펼치면 layout이 사라지고 첫 article 정보만 LLM에 전달되어 잘못 분류됨
- **표지/제목 페이지가 다음 장**에 있는 경우
- **표지+학회 안내문**처럼 메타데이터가 분산된 경우

`1-30 (A5)` 컬렉션 28편이 모두 「化石」 학술지의 제1호~제30호인 journal issue였는데 텍스트 추출 후 article로 잘못 분류된 사례.

### 4.2 needs_visual_review 자가보고 한계
프롬프트에 `needs_visual_review` 필드를 추가해 LLM이 스스로 vision 필요 케이스를 신호하도록 했지만, OCR 결과가 깨끗하면 LLM은 잘못된 경우에도 `confidence=high, needs_visual_review=false`라고 자신 있게 답함. 즉 **LLM이 모르는 것을 모를 때**가 진짜 문제.

15편 테스트에서 5편(pid 250,251,253,254,255)이 잘못된 high confidence를 줬는데 모두 실제로는 issue 표지였음.

### 4.3 더 신뢰성 있는 검출 신호
- **파일명 패턴**: `^\d+\.pdf$`, `^\d+-\d+\.pdf$` 등의 numeric 패턴 + 같은 컬렉션의 sibling 분포 → "issue collection" 강한 신호
- **컬렉션 단위 메타데이터**: 사용자가 "이 컬렉션은 journal issue 모음" 마킹
- **PyMuPDF 메타데이터**: 페이지 수 분포, 폰트 다양성 등

자동 검출은 본질적으로 어렵고, **사용자 도움(도메인 지식)이 가장 강력**.

### 4.4 CJK는 Sonnet vision 필수
같은 페이지를 Haiku vision과 Sonnet vision으로 비교:
- Haiku vision: 일본어 OCR이 약함, TOC 환각, 연도 불일치 (1984 ↔ 1978)
- Sonnet vision: 일본어 정확 인식, TOC 정확, 영문 발행정보까지 cross-validate

vision은 **Sonnet/Opus 권장**, Haiku vision은 영문 위주 페이지에만.

## 5. claude -p 운영 노트

### 5.1 시스템 프롬프트 캐시 비용
`claude -p`는 매 호출이 새 세션이라 시스템 프롬프트(~28k tokens) 캐시가 호출 간 재활용되지 않음. 호출당 ~$0.035(Haiku) 베이스라인이 거의 시스템 프롬프트 cost. 평가셋 200편 = ~$7 환산.

Max 플랜 사용 시에는 사용량이 빠르게 차감되므로, 동시에 여러 평가를 돌리지 않는 게 좋음 (Sonnet+Opus 동시 실행하다가 한도 가까워져서 Opus 중단한 경험).

### 5.2 출력 버퍼링
파이썬 subprocess의 print는 비-tty 환경에서 강하게 버퍼링됨. `flush=True` 또는 `python -u` 필수. 백그라운드 실행 시 output 파일이 한참 비어있어 보여도 실제로는 잘 돌아가고 있는 경우가 많음 → DB나 결과 파일을 직접 보는 게 더 정확.

### 5.3 이미지 입력
`claude -p`는 image 인자를 직접 받지 않지만 **Read 도구를 통해 파일 경로로 이미지를 읽을 수 있음**. PyMuPDF로 페이지를 PNG로 렌더 → 임시 파일 → prompt에 경로 기재 → `--allowed-tools Read`로 접근 허용. 작동 확인됨.

### 5.4 토큰화/JSON 파싱
LLM 응답이 가끔 ```json fence로 감싸지거나 prose가 끼므로, regex로 첫 `{...}` 블록만 뽑는 fallback 필요. envelope JSON(claude -p의 result wrapper) → inner result text → JSON 두 단계 파싱.

## 6. Zotero API 운영 노트

### 6.1 itemType 변경 시 템플릿 재사용
기존 item의 itemType을 다른 타입으로 바꾸면, 이전 타입의 필드가 남아있어서 update가 거부됨 (예: `'institution' is not a valid field for type 'document'`). 해결: `zot.item_template(new_type)`으로 빈 템플릿 받고, key/version/parentItem/collections만 보존해서 새로 채움.

### 6.2 journalIssue itemType이 없음
Zotero schema에 journal issue 전용 타입이 없음. 차선책: `document` 타입 + title에 "雑誌名 第N号" + publisher 필드에 학회명 + extra에 `Type: journalIssue`.

### 6.3 standalone PDF는 attachment를 child로 가질 수 없음
attachment item은 leaf — 다른 attachment의 부모가 될 수 없음. OCR JSON을 sibling으로 attach하려면 PDF에 parent item이 있어야 함. standalone PDF는 (a) parent를 새로 만들고 (b) PDF를 그 child로 옮긴 다음에야 JSON sibling 가능.

### 6.4 비-PDF attachment sync 누락 (수정함)
`get_collection_items()`가 `contentType == 'application/pdf'`만 골라서 JSON 첨부는 무시되고 있었음. JSON이 PaperFile로 들어가는 건 우리가 직접 `PaperFile.create()`한 덕분. DB를 처음부터 재생성하면 JSON 관계가 누락됐을 것. 현재는 모든 attachment를 picking하도록 수정 + 파생(JSON)은 status='processed'로 자동 설정.

### 6.5 write API quota
이전에 800편 단위로 OCR JSON sibling을 일괄 업로드할 때 후반부에 갑자기 'itemType not provided' 400 에러가 폭증. 정확한 원인은 미상이지만 시간/요청수 제한 가능성. 호출 간 sleep 1초로 안정됨. **bulk write는 천천히**.

## 7. 저자 이름 처리

CJK 단일 토큰 이름의 분리 휴리스틱 (Zotero firstName/lastName 분리):
- **4글자 한자**: 앞 2 = surname, 뒤 2 = given (일본/중국 일반)
- **3글자 한글/한자**: 앞 1 = surname, 뒤 2 = given (한국 일반)
- 그 외 단일 토큰: 통째로 lastName

이건 정확하진 않지만 (예: 김씨 두 글자 성도 존재) 데이터 대부분에 잘 맞음. 잘못된 케이스는 후처리로 수정.

## 8. 작업 구조

### 8.1 단계별 분리가 효과적
P05의 7-step 단계 (목록 → 추출 모듈 → 메트릭 → 평가셋 → baseline → LLM 1차 → 결정)가 잘 작동했음. 각 단계마다 명확한 산출물(대상 수, 함수, 파일, 점수)이 나와서 의사결정 근거가 됨.

### 8.2 Dry-run 우선
`promote_standalone.py`, `update_promoted_items.py` 모두 default가 dry-run, `--apply` 명시해야 실제 쓰기. 처음 1편만 `--apply --limit 1`로 검증하고 이상 없으면 전체 적용. 한 번도 실수로 데이터 망가뜨리지 않은 이유.

### 8.3 멱등성
`PaperBiblio.create()`는 새 row 추가만 하므로 재실행 안전. `promote_standalone`의 `Paper.zotero_key == PaperFile.zotero_key` 조건도 promoted 후 자동으로 빠짐 → 재실행해도 중복 없음. 매 스크립트 설계 시 멱등성을 우선 고려한 게 도움됨.

## 9. 데이터 발견

작업 과정에서 발견한 데이터 특징:
- 1-30 (A5), 31-71 (B5) 컬렉션은 사용자가 일본 학술지 「化石」을 호별로 스캔해 모은 아카이브. 일반 article 컬렉션과 다르게 다뤄야 함
- 1960s 컬렉션은 226편이 standalone (parent item 없음) — 대량의 메타데이터 빈약 PDF가 묻혀 있었음
- standalone PDF 파일명은 `21.pdf`, `mines-...-boyce.pdf` 등 일관성 없음. 파일명만으로는 분류 불가

## 10. 다음에 필요한 것

- **컬렉션-수준 메타데이터**: "이 컬렉션은 issue 모음" 같은 마킹 → 자동으로 vision pass로 라우팅
- **검토 UI**: PaperBiblio 결과를 사용자에게 보여주고 수동 승인/수정. 현재는 CLI preview만 있음
- **Zotero → DB pull sync**: 사용자가 Zotero 클라이언트에서 수정한 메타데이터를 DB로 가져오기
- **저자 이름 정규화**: GT 측 정규화로 metric 노이즈 줄이기
- **PyMuPDF 메타데이터 활용**: 페이지 수/폰트/embedded thumbnail 등 cheap signal로 vision 트리거 보강
