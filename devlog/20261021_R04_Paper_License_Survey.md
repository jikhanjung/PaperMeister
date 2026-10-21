# R04 — 논문 라이선스 조사: figsplit 학습·공개에 쓸 수 있는 도판은 얼마나 되나

2026-10-21

> ⚠️ 법률 자문이 아니다. 아래는 **확인 가능한 사실**(논문 본문에 인쇄된 문구, 출판사가
> Crossref에 등록한 라이선스, OpenAlex의 OA 판정)과 그로부터 나오는 통상적 해석이다.
> [R03](./20260813_R03_License_Audit.md)이 *우리 소프트웨어*의 라이선스였다면 이건 *우리가 가진 논문*의 라이선스다.

## 발단

P16 도판 파이프라인이 라이브러리 전체를 한 번 돌았다(도판 99,041개, 패널 분할 35,181개).
이 결과로 패널 분할 모델(figsplit)을 학습시키고 공개하려면 먼저 물어야 한다 —
**각 논문이 PD인가, CC0인가, CC BY인가, 아니면 저작권이 걸려 있는가.**

## 방법

DB는 읽기 전용으로만 열었다. 스크립트는 저장소 밖(`<data>/tmp/license_survey_20261021/`)에 있다.

| 출처 | 무엇을 읽었나 | 걸러낸 것 |
|---|---|---|
| **우리 PDF의 OCR 본문** | `passage_fts`에서 "creative commons / cc by / cc0 / public domain / copyright / open access" 문구. 첫·끝 쪽을 먼저 본다 | Wiley 다운로드 워터마크("OA articles are governed by the applicable Creative Commons License" — 모든 쪽에 찍힌다), 그림 출처 크레딧("photo by X, licensed under CC BY-SA"), BMC의 **데이터 전용** CC0 waiver, "3-D data are licensed under…" |
| **Crossref** | DOI별 `license`(URL + content-version) | `am`(저자 원고) 라이선스 — 우리 PDF는 출판본이다 |
| **OpenAlex** | `primary_location.license`, `oa_status` | OpenAlex가 `closed`라 부르는 논문의 라이선스 |

- DOI: Zotero 4,299 + 서지 추출 33 + 본문 첫 쪽 54 → 고유 **4,171개**. HTML 엔티티가 섞인 2개(`&lt;`)를 풀었고,
  접두가 세 자리인 오타 DOI(`10.314/...`)는 뺐다 — Crossref가 그 하나 때문에 묶음 전체를 400으로 거부한다.
- 요청은 **15초에 한 번, 50개씩**, 이메일 없이(같은 IP의 다른 서버도 비슷한 작업 중이었다). Crossref는 그래도
  429를 반복해 OpenAlex를 먼저 돌렸다. 총 OpenAlex 85회, Crossref 100회.

**판정 순서** (위가 이긴다)

1. 본문 라이선스와 Crossref 출판본 라이선스 — 둘이 다르면 **더 제한적인 쪽**(충돌 표시)
2. OpenAlex 라이선스 — 단 Crossref가 출판사 자체 약관만 등록했으면 약관 쪽
3. 미국 정부 저작물("This is a U.S. government work…" 또는 USGS 등 간행물)
4. **1931년 이전 출판** → 미국 기준 PD(2026-01-01 현재 1930년까지 출판분)
5. 미국 외 정부 간행물(지질조사소 보고서 등) → 그 정부의 조건 확인
6. 무료 열람이지만 개방 라이선스 없음(OpenAlex green/bronze 등)
7. 출판사 약관(Crossref) 또는 `oa_status: closed`
8. PDF 첫·끝 쪽의 날짜 붙은 © 표시
9. 미상

## 결과

라이브러리 전체(9,903편, 휴지통 제외). *도판*은 Figure 행, *분할*은 패널 분할을 마친 도판, *패널*은 FigurePanel 행,
*출처 표기*는 캡션에 "reprinted / courtesy / with permission / © / modified after / after Smith (1990)" 같은 말이 있는 도판.

| 분류 | 논문 | 도판 | 분할 | 패널 | 출처 표기 |
|---|---:|---:|---:|---:|---:|
| 미상 (라이선스 못 찾음) | 4,978 | 57,105 | 18,130 | 176,893 | 1,268 |
| 저작권 (출판사 약관) | 2,360 | 20,375 | 8,089 | 55,841 | 1,370 |
| 무료 열람, 개방 라이선스 없음 | 923 | 7,402 | 3,277 | 21,813 | 521 |
| CC BY | 614 | 5,430 | 2,827 | 17,669 | 242 |
| PD (미국, 1931년 이전 출판) | 428 | 3,202 | 1,021 | 16,758 | 13 |
| 저작권 (PDF의 © 표시) | 349 | 3,347 | 943 | 8,427 | 55 |
| CC BY-NC | 107 | 748 | 298 | 1,532 | 54 |
| CC BY-NC-ND | 64 | 591 | 270 | 1,340 | 46 |
| CC BY-NC-SA | 47 | 490 | 206 | 1,260 | 15 |
| CC0 | 12 | 93 | 33 | 218 | 2 |
| 미국 외 정부 간행물 | 10 | 88 | 30 | 312 | 6 |
| PD (미국 정부 저작물) | 5 | 143 | 53 | 337 | 2 |
| PD mark | 3 | 14 | 0 | 0 | 0 |
| CC BY-SA | 3 | 13 | 4 | 40 | 1 |

### figsplit 관점으로 묶으면

| 묶음 | 포함 | 논문 | 도판 | 분할 | 패널 |
|---|---|---:|---:|---:|---:|
| **A. 재배포 가능** | PD(미국 정부)·PD mark·CC0·CC BY·CC BY-SA | 637 | 5,693 (5.7%) | 2,917 | 18,264 (6.0%) |
| B. 미국에서만 PD | 1931년 이전 출판 | 428 | 3,202 | 1,021 | 16,758 |
| C. 비상업만 | BY-NC·BY-NC-SA·BY-NC-ND | 218 | 1,829 | 774 | 4,132 |
| D. 저작권, 무료 열람 | green 448·bronze 418·diamond 44·gold 10·hybrid 3 | 923 | 7,402 | 3,277 | 21,813 |
| E. 저작권 | 출판사 약관 + © 표시 | 2,709 | 23,722 | 9,032 | 64,268 |
| F. 확인 필요 | 미국 외 정부 간행물 | 10 | 88 | 30 | 312 |
| G. 미상 | | 4,978 | 57,105 | 18,130 | 176,893 |
| 합계 | | 9,903 | 99,041 | 35,181 | 302,440 |

**이미지째 공개할 수 있는 건 A — 도판의 6% 남짓이다.** B까지 넣어도(미국 기준) 9%, 패널로는 12%.

## 읽는 법

- **미상은 "자유롭다"가 아니라 "확인을 못 했다"다.** 라이선스가 없으면 기본값은 저작권 보호다. 미상의 대부분은
  DOI가 없는 옛 문헌이다(1931–69년 838편, 1970–89년 1,187편, 1990–2009년 1,854편, 2010년 이후 710편, 연도 없음 389편;
  컬렉션으로는 *1. Trilobite Literature* 2,553편). 같은 학술지의 판정을 붙인 힌트(`journal_hint`)가 1,713편에 있고,
  그중 1,346편이 "저작권"이다 — *Journal of Paleontology* 385편, *化石* 186편, *Palaeontology* 159편 같은 학회지.
- **B는 미국 기준이다.** 미국은 1930년까지 출판된 저작물이 PD지만, 다른 나라는 저자 사후 70년(한국 포함) 등이다.
  1931–63년 미국 출판물 중 갱신 안 된 것도 미국에선 PD일 수 있지만 개별 확인이 필요해 분류하지 않았다.
- **C의 ND**는 "변경 없는 복제만" — 패널을 잘라낸 이미지는 개작으로 볼 여지가 있다.
- **D의 "무료 열람"은 개방 라이선스가 아니다.** green은 저장소 사본, bronze는 출판사 사이트에서 공짜로 읽힐 뿐이다.
  다만 diamond 44·gold 10편은 학술지 차원의 CC 라이선스를 메타데이터에 안 올렸을 가능성이 있다 — 학술지 사이트 확인 대상.
- **© 표시**에는 CNKI의 "(C) 1994-2008 China Academic Journal Electronic Publishing House" 같은 DB 스탬프도 섞여 있다.
  어차피 저작권 쪽이라 판정은 같다.
- **CC 논문 안에도 남의 그림이 있다.** A의 도판 5,693개 중 247개는 캡션이 다른 출처를 밝힌다.
  CC BY는 *논문의* 라이선스이지 그 안에 허락받아 실은 제3자 그림까지 덮지 않는다. CSV의
  `figures_credited_elsewhere`로 논문 단위 수가 있다(도판 단위로 거르려면 같은 정규식을 캡션에 다시 적용).
- **출처 충돌 21건** — Crossref는 출판사 약관만 있는데 OpenAlex는 CC라 한 것 13, 본문과 Crossref의 CC 종류가 다른 것 5,
  본문은 CC인데 Crossref는 약관만 있는 것 3(ACM 2025·*Comptes Rendus Palevol* 2022는 본문이 맞아 보이고,
  *Biological Reviews* 2012 하나는 애매하다).
  모두 CSV의 `conflict` 열에 있다.

## 학습·공개에 대해 (판단이 아니라 질문 목록)

- **학습 자체**는 저작물 이용이 아니라 정보 분석으로 보는 예외가 관할권마다 다르다 — EU DSM 지침 3조(연구기관의
  과학 연구 목적)·4조(옵트아웃 존중), 일본 저작권법 30조의4, 미국은 fair use 다툼 중. 한국은 TDM 조항이
  개정안으로 논의됐지만 **알기로는 아직 입법되지 않았고** 공정이용(35조의5)에 기대야 한다 — 확인 필요.
- **figsplit은 상자를 내는 검출 모델**이라 출력이 원본 그림을 재현하지 않는다. 생성 모델보다 학습 데이터
  유출 위험이 구조적으로 낮다는 점은 공개 판단에 유리한 사실이다.
- 공개 방식 선택지:
  1. **가중치만** 공개
  2. **A 묶음 이미지 + 주석**을 데이터셋으로(출처 표기 의무 — DOI·저자·라이선스를 함께)
  3. **주석만** 공개(DOI·쪽·bbox·패널 라벨) — 이미지는 각자 PDF에서 잘라 쓰게. 전체 35,181개 도판을 담을 수 있다

## 산출물 (저장소 밖 — 논문별 목록은 공개 저장소에 두지 않는다)

- `<data>/tmp/paper_licenses_20261021.csv` (UTF-8 BOM, 엑셀에서 바로 열림) — 논문 한 줄씩:
  `paper_id, year, year_source, title, journal, collection, doi, doi_source, category, reuse_of_figures, source,
  all_sources, conflict, evidence(근거 문구), publisher, oa_status, openalex_license, crossref_licenses, in_crossref,
  in_openalex, figures, paneled_figures, panels, figures_credited_elsewhere, journal_hint`
- `<data>/tmp/license_survey_20261021/` — `collect.py`(DB → papers.json) · `lookup.py`(Crossref/OpenAlex, 받은 건 다시 안 묻는다) ·
  `textlic.py`(본문 판정) · `classify.py <data> [out.csv]`(분류). 받은 응답 185개가 캐시로 같이 있어 **네트워크 없이 재분류**된다.

## 다음에 할 수 있는 것

- 미상 중 DOI 없는 논문을 제목으로 OpenAlex에 찾기(1편 1요청이라 느리다 — 대부분 옛 문헌이라 얻을 게 적을 수도)
- diamond/gold 54편의 학술지 라이선스 확인
- A 묶음의 도판 단위 출처 필터 + 데이터셋 내보내기
