# 065 — references 추출: 저널 합본(multi-article) 오검출 수정 + 로그 귀속

> 세션 (2026-06-25). P11 references 추출 배치 로그를 보다가 발견한 두 가지:
> (1) 에러 로그가 "어느 논문에서 무엇을 하다 났는지" 안 보임, (2) `化石 第34호`가
> 참고문헌 2454개로 폭주. 후자를 파다가 **저널 한 권 통째 PDF(여러 논문 합본)**에서
> references 섹션 검출이 무너지는 구조적 문제를 찾아 일괄 수정.

## 배경 — 무엇이 잘못됐나

`化石`(Fossils) 저널은 **한 호(號)가 여러 편의 논문을 묶은 합본 PDF**로 OCR되어 있다.
즉 한 문서 안에 `引用文献`/`文 献` 섹션이 **여러 개**(논문마다 하나) 존재한다.
기존 코드는 "1 문서 = 1 references 섹션" 가정 위에 있었다.

### 증상 1 — `化石 第34号`(paper 31): 70% / 2454 entries 폭주

`_extract_refs_markdown`이 **마지막** 헤딩만 취하고 거기서 **EOF까지** 쓸어담았다.
STOP 헤딩(`謝辞`/appendix 등)이 마지막 섹션 뒤에 없으면 그대로 문서 끝까지 →
본문 산문, 표 셀, 책 광고, 표지/목차까지 전부 "참고문헌"으로 흡수.
→ block이 전체의 70%, split 결과 2454개.

### 증상 2 — `化石 48/42/47`(paper 20/22/17): low-conf fallback로 광고가 들어감

이쪽은 헤딩이 `文 献`처럼 **두 글자 사이에 공백**으로 OCR됨. `_REF_HEADING_RE`는
`re.escape('文献')`이라 인접한 두 글자만 매치 → **헤딩 0개 검출** → 마지막 2페이지
fallback → **뒤표지 "化石 バックナンバー在庫"(재고 광고 목록)**을 참고문헌으로 저장.
기존에 저장돼 있던 각 ~40개 refs가 이 광고 fragment였다.

## 수정 (`papermeister/biblio.py`)

### 1. CJK/Hangul 헤딩의 OCR 공백 허용

`_heading_word_pattern(w)`: 단어에 CJK/카나/한글 글자가 있으면 각 글자 사이에 `\s*`를
끼워 패턴 생성(`文 献`, `참 고 문 헌` 매치). Latin 단어는 공백이 의미 있는 경계이므로
`re.escape` 그대로. `_REF_HEADING_RE` 빌드 시 이 헬퍼 사용.
→ paper 20/22/17의 `文 献` 섹션이 비로소 검출되어 fallback 탈출.

### 2. 다중 섹션 검출 (multi-article)

`_extract_refs_markdown`을 분기:
- **헤딩 1개** → 기존 동작 유지(헤딩→STOP/EOF). 검증된 단일 논문 경로라 **무회귀**.
- **헤딩 2개+** → 합본으로 보고 **섹션마다** `_capture_refs_section`으로 경계 산정 후
  모두 이어붙임.

### 3. `_capture_refs_section` — 내용 밀도로 섹션 경계 잡기

핵심 난점: Chandra OCR이 **참고문헌 1개를 5~7줄로 쪼갬**(저자-연도 head, 그 다음
이탤릭 저널명·권·페이지가 각각 별도 줄). 따라서 "head 사이 간격"만으로는 못 자른다.

채택한 규칙:
- **citation head** = 줄 앞쪽(~55자) 안에 연도 + 구분자(`:` `,` `.`). 괄호형 서양식
  `Smith, J. (2001).`도 포함(`_CITATION_HEAD_RE`).
- head를 만나면 keep 갱신·gap=0. head가 아닌 줄은 gap++.
  `gap <= _REFS_MAX_CONT(8)`이고 body가 아니면 continuation으로 keep 연장.
- `gap >= _REFS_GAP_STOP(12)`면 references 종료로 보고 중단 → 본문 산문/숫자 표
  (`1*`,`2*`…)/그림 블록이 흡수되는 것을 차단.
- `_is_body_line`: `。` 포함, 120자 초과, 또는 `指名討論/はじめに/abstract/…` 같은
  섹션 헤딩 → 본문 신호.
- 섹션에 author-year head가 `_REFS_MIN_HEADS(2)` 미만이면 **거짓 헤딩**으로 기각
  (예: 투고규정 안의 `6. 引用文献` "引用文献は…論文末に一括する" 문장).

### 4. 에러 로그 귀속 (증상과 별개로 함께 처리)

`_call_qwen(label=...)` + 타임아웃/shrink 로그에 `label`(논문 태그) 주입. 이제
`[34 化石 第31号] refs 13/72: timeout at batch 20 → shrink to 10, retrying`처럼
**어느 논문 / 진행 위치**가 찍힌다. floor에서 포기할 때 "giving up" 라인도 추가.

## 검증

### 대상 4개 저널 합본 (모두 conf=high로 전환)

| paper | 이전 | 이후 |
|-------|------|------|
| 31 化石34 | 70% / 2454 (폭주) | 8 섹션 / **347** |
| 20 化石48 | fallback 광고 | 3 섹션 / **177** |
| 22 化石42 | fallback 광고 | 3 섹션 / **115** |
| 17 化石47 | fallback 광고 | 4 섹션 / **233** |

### 전체 캐시 before/after diff (OCR JSON 9,829개, git stash로 구/신 코드 각각 sweep)

- 변경 **394개** = 감소 210 + 증가 184.
- **감소**: 폭주 교정. 예) 행동생태학 교재 5702→8, Brusatte 5391→8(이들은 참고문헌이
  표 형태라 양쪽 다 깔끔히 안 잡히지만, 신 코드는 수천 개 쓰레기 row를 안 만듦).
- **증가**: 멀티-챕터 단행본이 마지막 챕터만이 아니라 **전 챕터** 참고문헌을 잡음
  (Stoddart *Coral reefs research methods* 1484→4482, 45챕터·섹션당 head 비례·폭주 0).
  공백 헤딩의 CJK/한글 문서가 fallback 탈출(`한국의 화성활동` 7→299).
- 단일 헤딩·HTML OCR 논문은 **무변화**(예: Hwang 2019 = 25 유지).

## 남은 이슈 (이번 범위 밖, 선검토 후 보류)

- **fragmentation ~2~3배 인플레**: 한 reference가 head+저널+권+페이지로 쪼개져 각각
  별도 entry가 됨(`Copeia` 한 줄이 1개 entry). detection이 아니라 `split_reference_entries`
  쪽 문제 — continuation 재결합을 별도 작업으로 고려.
- **표 형식 참고문헌 단행본**(Krebs&Davies 등): head 검출이 근본적으로 모호 → 과소 검출.
  과거엔 과대(쓰레기), 지금은 과소. 양쪽 다 "정답 없음" 영역.

## 적용 메모

- 실제 재추출은 **Windows 쪽**(라이브 DB/OCR 캐시)에서 `extract_references.py` 재실행 시
  반영. paper 31/20/22/17은 `references_checked`가 아직 0이거나 광고 fragment 상태이므로
  `--reextract`로 다시 돌리면 위 결과로 갱신됨.
