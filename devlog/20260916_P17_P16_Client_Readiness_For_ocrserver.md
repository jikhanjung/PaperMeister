# P17 — P16 준비: fsis 9/16 개정분 반영과 ocrserver 착수 전 PaperMeister 쪽 준비 목록

**작성**: 2026-09-16
**상태**: 계획
**읽은 것**: fsis2026 `docs/figure_edge_cases.md`(9/16 개정, §1-4-1 · §3-1 보강 · §4-3~4-5 · §6-7~6-14 · §7) ·
`docs/figure_pipeline_design_guide.md`(9/16 개정, §2-2 · §2-3 · §3 · §4-2 · §4-6 · §6-1 · §6-5 · §6-6 · §7 · §8) ·
devlog 275~277 · `TODOs.md` §4. 이 저장소의 [P16](./20260914_P16_Figure_Panel_Split.md) · [095](./20260915_095_P16_Phase0_Figure_Assembly_Survey.md) ·
[096](./20260915_096_P16_Phase1_Figure_Store_And_List.md) · [097](./20260915_097_P16_Assembly_Rules_From_fsis_Edge_Cases.md).

---

## 0. 요약

- 097은 fsis 문서의 **9/15 시점**을 반영했다. fsis는 **9/16에 21건을 PDF 원문과 직접 대조**하고(0.6.99) 두 문서를 다시 고쳤다.
  새로 들어온 것은 조립(①)이 아니라 거의 전부 **② 캡션 연결 · ③ 패널 분할 · 저장 · 검수**에 관한 것이다 — 즉 서버 작업이
  시작되기 전에 **PaperMeister가 먼저 정해 둬야 할 것들**이다.
- 실제 모델 호출은 ocrserver가 하지만, **입력을 만드는 것 · 결과를 검증하는 것 · 결과를 DB에 반영하는 것 · 사람이 고친 것을
  지키는 것**은 전부 클라이언트 몫이다. 이 넷은 **서버 없이 지금 만들고 테스트할 수 있다**(§3). 그러면 서버 쪽 일은
  "이 JSON을 받아 CLI를 돌리고 이 JSON을 돌려준다"로 줄어든다.
- P16의 결정 두 가지를 손보자고 제안한다(§3.2 · §3.5). 둘 다 fsis가 9/16 개정에서 반대 근거를 새로 적었다.
- 순서: **Phase 1 게이트(파일럿 100편 검수)를 먼저 통과**하되, 게이트를 통과하기 위한 검수 도구가 없다(§3.9). 그걸 먼저 만든다.

---

## 1. fsis 9/16 개정 — 097 이후 새로 온 것

| fsis | 내용 | 해당 단계 | PaperMeister 상태 | 이 문서 |
|---|---|---|---|---|
| EC §1-4-1 | 표기 없는 사진 쪽 + 설명이 **다음** 쪽 `PLATE N—`. §1-3(앞 쪽)의 대칭. fsis는 규칙화 안 함 | ① | 앞 쪽 규칙만 있음 (`_explanation_titles`) | §3.8 측정 후 결정 |
| EC §3-1 보강 | 쪽 아래 **전폭** 캡션을 옆 그림이 가져감. 제 캡션은 왼쪽 단 | ① 힌트 → ② | 힌트도 같은 실수를 한다. ②가 풀어야 | §3.3 입력에 "힌트일 뿐" 명시, §3.10 검수 사유 |
| EC §3-3 보강 ×2 | 같은 쪽 다른 도판에 **같은 캡션 텍스트**(190행) · 형제 행은 `own_caption`인데 한 행만 모델 결과 | ② 검증 | 없음 | §3.4 검증 규칙 |
| EC §4-3 | 한 그림이 **세 쪽**, 캡션은 마지막 쪽. 폭 필터가 오른쪽 단 그림을 버림 | ② 결과 · ① | 폭 필터 없음(면적 4,000‰²) | §3.4 `continuation_of` |
| EC §4-4 · §4-5 | 글자 캡션 사진 쪽 + 설명이 **앞 쪽 아래** / 쪽 전체 그림 + 캡션이 **다음 쪽 아래** | ② 입력 | P16 §1.3은 다음 쪽 꼬리말만 | §3.3 앞·뒤 쪽 포함 |
| EC §4-5 | 인쇄 캡션을 글자별로 펼칠 때: 묶음 소제목(`B–C.`)은 나눠 갖고, 본문 상호참조(`in E–F.`)는 표지가 아니다 | ② 프롬프트 | 없음 | §3.2 프롬프트 규칙 |
| EC §6-7 | 못 찾으면 `[]`로 **덮어** 714행이 매일 비었다. 이름 두 계열(`Figure 22`↔`Fig. 22`)은 **같은 정규화 함수**를 양쪽에 | ② 반영 | 정규화 함수 없음. `name`은 인쇄 그대로 | §3.4 `normalize_figure_name`, skipped ≠ cleared |
| EC §6-8 | 사람이 접은 행을 규칙이 되살리려다 unique 오류 → 일일 체인 정지 | 저장 | 키가 (해시·쪽·bbox·조립)이라 접힌 행을 찾아 그대로 둔다 ✅ | — |
| EC §6-9 | `kind='map'`이라 분할에서 **조용히** 빠짐. 같은 그림인데 쪽마다 kind가 달랐다 | ③ 대상 선정 | `kind`는 ③ 결과에서 온다 — **첫 실행 전엔 알 수 없다** | §3.5 제외 사유 출력, 순환 해소 |
| EC §6-11 | 한 사진 속 **개체 둘 ≠ 패널 둘**. 반대로 독립 사진을 조각으로 오인 | ③ 프롬프트 · 검수 | 없음 | §3.2 · §3.10 |
| EC §6-12 · DG §4-6 | 설명이 **여러 쪽**에 걸침(`source_pages`) · 원문 번호 중복의 **편집 보정**은 인쇄 번호와 분리(`printed_label`, `label_status`) | 스키마 | `caption_page` 하나. `FigureEntry`에 label만 | §3.6 |
| EC §6-13 · DG §6-5 | 수동 행의 `subfigures`는 지켰는데 `caption`·`alt`는 덮였다. **한 플래그로 모든 칸이 보호된다고 가정하지 말 것** | 반영 | `user_confirmed` 하나 | §3.7 보호 판정 한 곳 |
| EC §6-14 · DG §4-2 | 좌표를 넓힌 행이 있으면 동기화가 **원본 청크를 새 행으로 되살린다** → `merged_chunk_bboxes` | 저장 | `blocks_json`이 이미 그것이다. 단 `plan_store`가 안 본다 | §3.7 |
| DG §2-3 | **입력 키는 입력의 정체만.** 결과에 따라 바뀌는 값을 키에 넣으면 반영할 때마다 키가 바뀐다 | ③ 키 | P16 §5 `panel_key`에 **entries digest 포함** | §3.5 재검토 |
| DG §2-2 · §6-5 | 항목이 바뀌어도 **박스가 맞으면 재분할하지 않고 다시 연결** | ③ 반영 | 계획은 "캡션 바뀌면 다시 자른다" | §3.5 |
| DG §3 | 쪽 번호 계열(0/1-기준)을 **파일마다 명시**. 0-기준 추출을 1-기준으로 대조해 227↔714 | 명세 | DB·OCR JSON 0-based. P16 §6 명세에 **안 적혀 있다** | §3.1 |
| DG §4-3 | 배치가 **플레이트 하나를 통째로** 빠뜨린다 · 정형 설명(소제목 + 표본번호 목록)은 **규칙 파서가 더 정확** · "원문 없음" 단정 전에 앞·뒤 쪽 | ② 검증 · 입력 | 없음 | §3.3 · §3.4 |
| DG §6-1 | 동기화도 **대상마다 예외 격리** | 저장 | `assemble_figures.py::store_mode`는 파일 단위 트랜잭션이지만 **`try`가 없다** — 캐시 한 파일이 깨지면 파일럿 108개 실행이 거기서 멈춘다 | §3.7 |
| DG §6-6 | 검수 0건 ≠ 완료. **5범주**(자동 대기 · 반영 대기 · 사람 검수 · 후보 밖 누락 · 보존)를 따로 센다 | 검수 | `figure_review.py` 미작성 | §3.10 |
| DG §8 | 새 프로젝트 순서: 표본을 사람이 본다 → 데이터 모델 → 규칙 단계 + dry-run + 픽스처 테스트 → 파일만 쓰는 레인 → **검수 화면을 일찍** | 전체 | 1~3 완료. 검수 도구가 없다 | §3.9 · §4 |

**097에 이미 있는 것**(다시 안 함): 표지 줄 · PLM · 한 장 플레이트 · 번호 중복(마주 보는 두 쪽 예외) · 번호 추론 셋 · 도판별 캡션 플레이트 ·
조각(틈 80/160 · 가로 70% · 두 캡션 청구 · 옆 캡션 · `Photo`/`사진`) · 옆 단 캡션 · IoU 0.5 좌표 옮김.

**PaperMeister가 구조로 이미 피한 것**: 좌표 같은 중복 행(EC §5-1 — 키에 bbox가 있어 생길 수 없다) · `그림 9-65`·`Figure 1-2` 이름 훼손(EC §7 —
`_FIG_NAME`이 인쇄 표기를 그대로 둔다) · 폭 필터(DG §3 — 면적·가장자리 기준이고 플레이트 판정이 먼저다) · 원본 행 삭제(접기만).

---

## 2. 설계 가이드 열 가지 원칙 대조

| # | 원칙 | PaperMeister | 비고 |
|---|---|---|---|
| 1 | 구조는 규칙, 의미는 모델 | ✅ ① 규칙 / ②③ 모델 | |
| 2 | 연결은 원문을 읽는 순간에 | ✅ ②가 논문 단위로 연결+분할을 한 번에 | |
| 3 | 정체는 좌표 | ✅ 키 = (해시·쪽·bbox·조립) | |
| 4 | 항목 수 ≠ 패널 수 | 계획만 (P16 §1.3 `annotation_indices`) | §3.5 |
| 5 | 모델 답은 준 입력에 근거 — 양쪽 검증 | **없음** | §3.4 |
| 6 | 판정은 한 곳 | ✅ `figures.py` — 단 **보호 판정**은 아직 없다 | §3.7 |
| 7 | 파생값에 출처 | `caption_source`·`link_*`·`panel_*` ✅ / `source_pages`·`printed_label` ✗ | §3.6 |
| 8 | 지우지 말고 접기 | ✅ `dismissed_by` | |
| 9 | 레인은 파일만, 반영은 따로 | 서버 job = 결과 파일. 클라이언트가 반영 ✅ | `link_result_digest` ✅ |
| 10 | 검수 목록은 사람이 할 일만 | **없음** | §3.10 |

---

## 3. ocrserver 착수 전에 여기서 준비할 것

### 3.1 명세 v2 — P16 §6을 자기완결적으로 고쳐 넘긴다

ocrserver는 P16 **§6만** 읽는다. 그런데 Phase 2·3 요구의 절반은 §1.3에 있고 §6에는 없다. 그리고 9/16에 더 늘었다. §6을 아래를 담아 다시 쓴다.

| 바뀌는 것 | 근거 |
|---|---|
| **`page`는 0-based**라고 요청·응답 모두에 명시. 서버가 렌더할 때 PDF 인덱스와 같은 계열 | DG §3 (227↔714) |
| ② 결과 도판마다 **`name`**(인쇄된 표기 그대로) 추가. 지금 응답엔 caption·entries만 있어 096 "②가 이름을 붙인다"가 성립하지 않는다 | 096 §2 · EC §6-7 |
| ② 결과 **`caption_pages: [..]`**(리스트) — `caption_page` 하나로는 두 쪽에 걸친 설명을 못 적는다 | EC §6-12 |
| ② 결과 도판마다 **`continuation_of: figure_id \| null`** — 세 쪽에 걸친 한 그림. 이름이 같은 행이 쪽마다 있어도 된다(PaperMeister는 (쪽·이름) unique가 없다) | EC §4-3 |
| ② 결과 entries에 **`printed_label`**(인쇄 그대로) + `label`(정규화). 모델은 보정하지 않는다 — 보정은 사람 몫(`label_status`) | DG §4-6 |
| ② 입력 `figures[]`에 `page_kind` 포함, **`captioned_plate`는 클라이언트가 애초에 안 보낸다** | P16 §1.3 |
| ② 입력 `pages[]`는 클라이언트가 고른 쪽만. **서버는 쪽을 더하거나 자르지 않는다**. 자르면 `truncated`가 아니라 **오류** — 자르기는 클라이언트가 배치로 한다 | DG §4-3 (2,500자 절단 335장) |
| ② `skipped[]`는 "못 찾음"이지 "비어 있음"이 아니다 — 클라이언트는 skipped 도판의 기존 값을 **건드리지 않는다** | EC §6-7 |
| ③ 결과에 **`non_compound_reason`** ∈ {legend_labels, image_incomplete, single_image_many_captions, ''} + **`annotation_indices`** + 레이블별 role | P16 §1.3 · DG §4-5 |
| ③ 결과 panel `label`이 비고 `caption_indices`만 있는 경우를 허용 — 채우는 것은 클라이언트 규칙 | EC §6-1 |
| 워커: **item 하나의 실패는 그 item만** · 치명 오류(한도·로그인·CLI 없음)는 stdout+stderr 양쪽에서 찾고 **시도로 세지 않는다** · 프로세스 그룹째 타임아웃 | DG §5-3 · §6-1 |
| 워커: 하위 프로세스 환경에서 `OPENAI_API_KEY`/`CODEX_API_KEY`/`ANTHROPIC_API_KEY` 제거 | P16 §6.4 |
| 서버 dedup 키에 **prompt digest** 포함(§3.2에서 프롬프트가 요청에 실리므로) | DG §2-3 |

### 3.2 프롬프트·스키마는 PaperMeister가 갖고 요청에 실어 보낸다 — **P16 §6.3·6.4 변경 제안**

P16은 프롬프트·스키마·검증을 **서버 워커**에 두기로 했다(fsis `astra_panels.py` 재사용). 반대 근거:

- 프롬프트가 곧 도메인 규칙이다 — "인쇄된 것만 · 지어내지 말 것 · 묶음 소제목은 나눠 갖고 상호참조는 표지가 아니다 · 개체 둘 ≠ 패널 둘"은
  9/16 하루에 넷이 늘었다. 이 규칙의 결과를 책임지는 건 PaperMeister DB다. **서버 배포 없이 고쳐야 한다.**
- fsis DG §5-3: 호스트 레인이 옛 체크아웃을 써서 네 번의 배포 동안 새 방어가 안 들어갔다. 프롬프트를 요청에 실으면 이 문제가 **구조적으로 없다** — 서버는 받은 것을 돌린다.
- 서버가 범용이 된다: "이미지(선택) + 지시문 + JSON 스키마 → 구독 CLI → 구조화 출력". fsis도 같은 서버를 쓸 수 있다.

바뀌는 것: 요청에 `prompt: {version, instructions, schema}`가 실리고, 서버는 **구조 검증(스키마)만**, 도메인 검증(figure_id가 요청에 있는가 · 좌표 범위 ·
항목 수 타당 범위)은 **클라이언트**(`figures.py`)가 한다. 서버 dedup 키에 prompt digest가 들어간다. `prompt_version`은 클라이언트가 정한다.
프롬프트 원문은 `papermeister/figure_prompts/link.md` · `panels.md` + `*.schema.json`으로 두고 테스트가 스키마 유효성을 검사한다.
출발점은 fsis `plate_links.py` · `claude_augment.py` · `astra_panels.py`의 검증된 문장 + EC §4-5 · §6-11 규칙.

**사용자 확인 필요** — P16 §11 결정 1(구독 CLI)·2(Astra)는 그대로고 소재만 바뀐다.

### 3.3 ② 입력 만들기 — `figures.link_payload(paper_file)` — 서버 없이 지금 만들고 잰다

fsis가 가장 비싸게 치른 곳이 "어느 쪽을 얼마나 주나"다. 클라이언트가 결정해서 서버는 받은 대로 보낸다.

- **쪽 선정**: 도판이 있는 쪽 · `Caption` 블록이 있는 쪽 · 플레이트 표기/`Explanation` 제목이 있는 쪽(`plate_marks`·`_explanation_titles` 재사용) ·
  **그리고 도판 쪽의 앞 쪽과 뒤 쪽 전체**(EC §4-4 앞 쪽 아래 설명, §4-5 다음 쪽 아래 캡션, §4-1 다음 쪽 꼬리말). 앞·뒤 쪽은 텍스트가 길면
  **아래쪽 절반**(앞 쪽)·**위·아래 가장자리**(뒤 쪽)로 줄이되 줄인 사실을 표시.
- **설명 쪽 우선**: 예산은 설명 쪽부터 채우고, 설명 쪽이 모든 플레이트를 덮으면 **본문 인용 쪽은 넣지 않는다**(2492 — 인용 쪽을 고른다).
- **자르지 않는다**: 설명 쪽은 설명 시작점부터 끝까지. 예산 초과면 **플레이트 묶음 단위로 배치**(fsis: 설명 쪽 5쪽씩) — 한 논문이 여러 job이 되고
  `truncated`가 아니라 `batch i/n`이다. 배치마다 도판 목록은 **그 배치의 플레이트에 해당하는 것만**.
- **정형 설명은 규칙으로 먼저**(DG §4-3): 소제목 `1-4, 16, 17 종명` + 표본번호 달린 번호 목록 형태는 규칙 파서가 모델보다 정확했다(22 중 11 vs 22).
  `figures.parse_formal_explanation(text)`를 만들어 **결과를 힌트로 실어 보낸다**(`explanation_hints`) — 모델이 최종 판정. 어디까지 규칙인지는 파일럿 표본으로 정한다.
- **측정**: `scripts/link_figures.py --dry-run --dump tmp/p16_link/` 로 파일럿 108 파일의 payload JSON을 떨어뜨리고 **문자 수·쪽 수·배치 수 분포**를 낸다.
  P16 §8 "편당 호출 시간·한도 소모는 측정 전"의 **입력 쪽 절반은 서버 없이 지금 잰다**.
- 픽스처: fsis 사례 쪽 모양(2142 · 2400 · 2647 · 2574)을 합성 OCR HTML로 만들어 쪽 선정 테스트.

### 3.4 ② 결과 검증·반영 — `figures.validate_link_result()` · `figures.apply_link()`

**쓰기 전 검증**(DG 원칙 5, 쓰기·읽기 양쪽):

| 검사 | 조치 |
|---|---|
| `figure_id`가 요청에 있던 것인가 · `caption_pages`가 준 쪽 안인가 · `continuation_of`가 준 목록 안인가 | 아니면 그 도판 **거부**, job은 계속 |
| entries ≥ 1이고 label이 문자열, description이 캡션 원문의 **부분 문자열 근사**인가(모델 묘사 방지 — 문자 유사도로 완화) | 벗어나면 검수 사유 `description_not_printed` |
| 같은 쪽 **다른 좌표 두 도판에 같은 캡션**(80자 접두어) | `captioned_plate` 아니면 검수 사유 `caption_shared` (EC §3-3, 190행) |
| 플레이트 있는 논문에서 **플레이트별 항목 유무** — 배치가 한 플레이트를 통째로 빠뜨린다 | 0인 플레이트는 `skipped`로 취급 + 검수 사유 `plate_no_entries` (DG §4-3) |
| 항목이 **줄었다** | 기존 `caption_source`가 있을 때만 덮지 않는다(출처 없는 원본은 지어낸 것일 수 있다, 3607) |

**반영 규칙**:
- `skipped`·거부된 도판은 **기존 값 그대로**(EC §6-7). 절대 `[]`로 덮지 않는다.
- 이름 비교는 `figures.normalize_figure_name()` 한 함수를 **모델 결과와 규칙 힌트 양쪽에**. 정규화가 같은 쪽에서 둘 이상에 걸리면 매칭에 안 쓴다(EC §6-7 138행).
  저장은 인쇄 표기 그대로(`name`), 정규화는 비교에만.
- 보호된 행(§3.7)은 건너뛴다. 트랜잭션은 **도판 단위가 아니라 논문 단위**, 예외는 논문마다 격리.
- `link_result_digest`가 같으면 unchanged — 파일명·키가 아니라 **내용 해시**(fsis 268).

이 둘은 순수 함수라 **fsis 결과 파일 모양을 픽스처로** 지금 테스트할 수 있다.

### 3.5 ③ 입력·키·반영 — `panel_key` 재검토 (**P16 §5 변경 제안**)

P16 §5는 `panel_key = file_hash|page|bbox|render|entries digest`로 두어 "캡션이 바뀌면 자동 stale"을 노렸다. fsis 9/16 개정이 정면으로 반대한다:
- DG §2-3 "입력 키는 **입력의 정체만**. 결과에 따라 바뀌는 값을 키에 넣으면 반영할 때마다 키가 바뀐다."
- DG §2-2 · §6-5 "**박스가 맞으면 항목이 늘어도 재분할하지 않는다** — 기존 박스를 보존하고 원문 번호·위치로 항목을 다시 연결한다."
  fsis 재분할 472장에 5시간 20분. 캡션 한 글자 고칠 때마다 Astra를 다시 부르는 건 구독 한도로도 낭비다.

제안:
- `panel_key = file_hash|page|bbox_page|dpi|prompt_version` — **이미지의 정체만**. entries는 키에서 뺀다.
- 새 칸 `panel_entries_digest` — 분할 당시의 entries. 지금 entries와 다르면 **패널의 `entry_orders_json`이 낡은 것**이지 박스가 낡은 게 아니다.
- 재연결은 규칙: 패널 `label` ↔ 새 entries `label`(정규화)로 다시 잇는다. **번호 중복·무표지 패널은 순서만으로 짝짓지 않는다**(DG §6-5) → 못 잇는 패널이 있으면
  그때만 검수 사유 `entries_changed_unmapped` (사람이 재분할을 고른다).
- Astra가 `label`을 비우고 `caption_indices`만 준 패널은 그 항목 글자로 채운다. 둘 다 빈 뒤쪽 패널은 **안 붙은 패널 수 = 안 쓰인 항목 수**일 때만 순서로(EC §6-1).

**kind 순환 해소**(EC §6-9): `kind`는 ③ 결과인데 ③ 대상 선정이 `kind≠map`을 본다. 첫 실행에서는 kind가 없으므로 **지도 제외는 재분할에만** 적용하고,
`figures.split_targets()`는 `(targets, excluded[{figure_id, reason}])`를 돌려주며 스크립트가 **제외 사유를 반드시 출력**한다
(map · entries<2 · dismissed · user_confirmed · pdf_missing · attempts≥3). "오류 없이 아무것도 안 함"을 없앤다.

**조각 도판의 힌트**: `caption_group_union`의 `blocks_json`을 **도판 이미지 기준 0..1000**으로 변환해 `piece_boxes_figure_1000`으로 싣는다(P16 §6.4). 변환 함수 + 테스트.

### 3.6 스키마 보강 — Phase 2 전에

`_migrate()`로 컬럼 추가. 지금 넣어야 ② 첫 결과부터 출처가 남는다.

| 테이블 | 칸 | 이유 |
|---|---|---|
| `Figure` | `caption_pages_json` (`caption_page` 유지, 호환) | 두 쪽에 걸친 설명 (EC §6-12) |
| `Figure` | `continuation_of` (FK self, null) | 세 쪽 한 그림 (EC §4-3) |
| `Figure` | `caption_locked` · `bbox_locked` · `panels_locked` (bool) | 칸별 보호. `user_confirmed` 하나로 전부를 보호하면 "캡션만 고치고 패널은 다시" 가 불가능하고, 한 경로가 다른 칸을 덮는다(EC §6-13) |
| `Figure` | `panel_entries_digest` | §3.5 |
| `Figure` | `review_json` | 검수 사유 목록 `[{reason, at, detail}]` — §3.10의 판정 함수 결과 캐시 |
| `FigureEntry` | `printed_label` · `label_status` ('' \| printed \| inferred \| user_editorial_correction) · `specimen_number` (선택) | 편집 보정과 인쇄 번호 분리 (DG §4-6). `specimen_number`는 다음 라운드 엔티티 연결의 씨앗 |
| `FigurePanel` | `annotation` (bool) | 범례·그림 속 표시 — 캡션 수 세기에서 뺀다 (DG §4-5) |

### 3.7 저장 — 보호 판정 한 곳 + 사람이 넓힌 도판의 조각 부활 방지

- **보호 판정 함수** `figures.protection(row) -> {assembly, caption, panels}`를 만들고 `figure_store`(①) · `apply_link`(②) · `apply_panels`(③) · 검수 목록이 **전부 이것만** 본다.
  `user_confirmed`는 셋 모두 참, `*_locked`는 그 칸만. fsis는 `user_confirmed`·`own_caption`·`manual_fix`를 경로마다 다르게 봐서 33행이 덮일 뻔했다.
- **조각 부활**(EC §6-14): 사람이 도판 상자를 넓히거나 둘을 합치면(Phase 5, 또는 §3.9 스크립트) 재조립은 원본 블록을 다시 `create`한다 — `plan_store`가 키로만 찾기 때문이다.
  fsis의 `merged_chunk_bboxes`는 PaperMeister에선 **`blocks_json`이 이미 있다**. `plan_store`에서 `create` 전에: 같은 파일·쪽의 **보호된 행**(user_confirmed 또는 bbox_locked)
  의 `blocks_json`이 이 조립 결과의 블록을 **정확히**(bbox 일치) 포함하면 `absorbed`로 세고 만들지 않는다. **단순 포함 관계는 쓰지 않는다**(독립 사진을 삼킨다) ·
  **둘 이상이 주장하면 만들지 않고 검수 사유**로. 테스트: 넓힌 행 + 재조립 → 신규 0.
- **예외 격리**: `store_mode`는 파일마다 `try`가 없다. 파일마다 격리하고 실패 목록·종료코드(0이 아님, 나머지는 계속)를 낸다(DG §6-1 — fsis는 한 편이 일일 체인 전체를 멈출 뻔했다).

### 3.8 조립 규칙 후보 — 측정하고 결정 (Phase 1 게이트와 함께)

새 규칙은 **전 캐시 dry-run → 바뀌는 쪽 전부 → 렌더해 눈으로**(097 §4의 절차). 세 후보:

| 후보 | 근거 | 측정 |
|---|---|---|
| 표기 없는 사진 쪽 + **다음** 쪽 `PLATE N—` 설명 → N | EC §1-4-1 (fsis는 1건이라 규칙화 안 함). 이 라이브러리는 모노그래프가 많아 다를 수 있다 | `_explanation_titles`를 다음 쪽에도 → 발동 쪽 수 |
| 좁은 사진(단 폭) 조각이 `TINY_AREA`에 걸리는가 | EC §4-3 폭 필터 사고. PaperMeister는 면적 4,000‰² | 조각 병합 도판 중 면적 4,000~8,000 블록 분포 |
| `_owned_elsewhere`의 반대 실패 — 전폭 캡션이 옆 단 그림을 가져감 | EC §3-1 보강 | 같은 쪽에 번호 캡션 둘 + 그림 둘인데 힌트가 같은 캡션인 쪽 수 |

결정 기준은 fsis DG §8-8 그대로: **후보 중 진짜 비율**. 29장 중 4곳이면 규칙이 아니라 데이터.

### 3.9 검수 도구 — Phase 1 게이트를 통과하려면 먼저 있어야 한다

HANDOFF의 게이트는 "파일럿 100편(도판 3,750) Text 탭 목록을 사람이 보고 맞다". 그런데 (a) 3,750개를 Text 탭에서 하나씩 누르는 건 현실적이지 않고,
(b) **틀렸을 때 그것을 기록할 방법이 없다**(`user_confirmed`·`dismissed_by='user'` 칸은 있는데 세우는 경로가 없다). fsis DG §8-6 "검수 화면을 일찍" ·
§6-5 "사람 수정도 재현 가능한 결과로".

- **`scripts/figure_contact_sheet.py`** — 파일럿 도판을 **쪽 렌더 위에 상자 + 이름·조립·page_kind·힌트 앞부분**을 겹쳐 HTML로. `pdfdoc.render_page` + `ocr_layout.crop_box` 재사용.
  전부가 아니라 **층별 표본**: `plate_inferred` 전부(90) · `dup_number` 표본 · `caption_group_union` 표본 · `captioned_plate` 전부(342) · 보통 300. 097 §4가 손으로 한 것을 스크립트로.
- **`scripts/figure_curate.py --execute`** — `--figure-ids` + 동작(`confirm` · `dismiss` · `rename` · `set-bbox` · `merge`) + `--reason`. 결과는 DB 플래그와 함께
  **`tmp/p16_curation/<date>.json`에 남긴다**(fsis 277: `scripts/curation/20260916_figure_review.json` + 적용기). 재조립·재OCR 뒤 같은 결정을 다시 적용할 수 있어야 한다.
  `merge`·`set-bbox`는 `bbox_locked` + `blocks_json` 갱신 → §3.7이 조각 부활을 막는다.
- Text 탭 목록에 검수 사유 배지(§3.10) — 클릭 경로는 Phase 5.

### 3.10 완료 판정 — `scripts/figure_review.py` 출력 규격 (DG §6-6)

검수 0건을 완료로 보고하지 않는다. 다섯을 따로 센다.

| 범주 | 셈 |
|---|---|
| 자동 처리 대기 | `link_key` 낡음/없음 · `panel_key` 낡음/없음 · attempts<3 인 도판 수 (단계별) |
| 반영 대기 | 서버 job done인데 클라이언트가 안 받은 것 (`GET /figures/jobs?client_id=`) |
| 사람 검수 | 판정 함수 `figures.review_reasons(row)`의 사유별 수 — `description_not_printed` · `caption_shared` · `plate_no_entries` · `panel_count_out_of_range`(항목의 ½~2배 밖) · `panels_0` · `panels_1_with_siblings`(이미 나뉜 쪽) · `single_image_many_captions` · `image_incomplete` · `entries_changed_unmapped` · `plate_inferred` · `attempts_exhausted` |
| 후보 밖 누락 | entries 0/1 · `kind=map` · PDF 없음 · **OCR 그림 블록인데 도판 행이 없는 것**(폭·면적 필터 검증) |
| 보존 | 보호된 행 수 · 재조립 dry-run에서 보호된 행이 바뀌려 한 수(0이어야) |

판정 함수는 `figures.py` 한 곳, 스크립트와 Text 탭 배지가 같이 쓴다(DG 원칙 6).

---

## 4. 순서

```
[지금, 서버 없음]
 A. §3.9 검수 도구 (contact sheet · curate)          ← Phase 1 게이트에 필요
 B. Windows에서 파일럿 100편 --execute → 사람이 본다   ← Phase 1 게이트 (HANDOFF)
 C. §3.8 후보 셋 측정 → 규칙 반영 여부 결정
 D. §3.6 스키마 + §3.7 보호 판정·조각 부활 방지 + 예외 격리
 E. §3.3 link_payload + 측정(입력 크기) · §3.4 검증·반영 (픽스처 테스트)
 F. §3.5 panel_key 재정의 · split_targets · piece box 변환 · §3.10 review
 G. §3.2 프롬프트·스키마 파일 + §3.1 명세 v2  ──────▶ ocrserver에 넘긴다
[서버 착수 후]
 H. figure_client.py (HTTP) · link_figures.py · split_panels.py 레인  ← 서버 API가 확정돼야
```

- **G까지가 "여기서 준비할 것"**이다. G가 끝나면 서버 쪽은 명세와 프롬프트를 받아 워커만 만들면 되고, 첫 응답이 오는 날 E·F의 검증·반영이 이미 테스트돼 있다.
- B와 D~F는 독립이라 순서를 바꿔도 된다. 단 **D는 파일럿 저장 전이 낫다** — 저장된 첫 도판부터 새 칸을 갖게.
- 사용자 확인이 필요한 것: **§3.2**(프롬프트 소재) · **§3.5**(`panel_key`에서 entries 제외). 둘 다 P16 결정의 변경이다.

---

## 5. 하지 않는 것 · 열린 것

- fsis 검수 데이터(ref 번호)를 가져오지 않는다 — 다른 코퍼스다. 가져오는 것은 **모양**뿐.
- 지도 자동 판별(캡션의 "map")을 넣지 않는다 — fsis EC §6-9가 그걸로 한 그림의 쪽마다 kind가 달라졌다. kind는 Astra가 준 것만.
- 편집 보정(`label_status=user_editorial_correction`)의 UI는 Phase 5. 칸만 먼저 둔다.
- **열린 것**: 정형 설명 규칙 파서(§3.3)를 어디까지 규칙으로 할지 — 파일럿 플레이트 620장의 설명 형식 분포를 보고 정한다.
  fsis처럼 "표본번호 유무로 항목/소제목을 가른다"가 이 라이브러리의 19세기 모노그래프에도 맞는지는 모른다.
