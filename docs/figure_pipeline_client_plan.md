# 도판 파이프라인 — 클라이언트(PaperMeister) 계획

**작성**: 2026-09-16
**상태**: 계획. [P16](../devlog/20260914_P16_Figure_Panel_Split.md)·[P17](../devlog/20260916_P17_P16_Client_Readiness_For_ocrserver.md)을
기준으로 두고, **2026-09-16 사용자 결정(§0)** 과 ocrserver 쪽 설계
([ocrserver P02](../../ocrserver/devlog/20260916_P02_figure_split_service_design.md))와 맞춘 것만 적는다.
P16·P17에 이미 있는 내용은 반복하지 않고 절 번호로 가리킨다.

---

## 0. 2026-09-16 사용자 결정 — P16 결정에 더해진 것

| # | 결정 | P16과의 관계 |
|---|---|---|
| D1 | ③ 패널 분할은 **gpt-6-astra(Codex CLI)만**. 다른 모델은 성능이 만족스럽지 않았다 | P16 §11-2 그대로 |
| D2 | **② 캡션 연결·분할도 Astra**로 | **P16 §0·§8 변경** — Opus 5(`claude -p`) → Astra(`codex exec`, 텍스트 전용) |
| D3 | 도판 추출(①)은 **클라이언트가** — HTML 레이아웃을 이미 갖고 있다 | P16 §4.1 그대로 |
| D4 | ①은 자주 틀린다(edge case 대부분). 문제가 있으면 **Astra 가 스스로 주변 쪽을 불러오거나 텍스트 전체를 훑어보며** 도판 판정을 다시 한다 — 어디까지 볼지는 클라이언트가 아니라 **Astra 가 판단** | **새 단계 ①′ 재판정** (§2). 서버는 논문 전체를 작업 폴더로 준다 |
| D5 | P17 §3.2 **채택** — 프롬프트·스키마는 PaperMeister 가 갖고 요청에 싣는다 | P16 §6.3·6.4 변경 확정 |
| D6 | P17 §3.5 **채택** — `panel_key` 에서 entries 를 뺀다. 박스가 맞으면 재분할 없이 다시 잇는다 | P16 §5 변경 확정 |
| D7 | ②는 **Astra 로 확정**. Opus 복귀 여지를 두지 않는다 | 워커에 `claude` CLI 경로 없음 |
| D8 | 호출 속도는 **5분에 1건**으로 시작 (서버 워커 최소 간격 300 s, 단계 무관). 로그를 보며 조정 | 하루 상한 대신 간격 |

D2의 결과: 서버 워커는 **CLI 하나(`codex`), 로그인 하나, 구독 한도 하나**만 다룬다. `claude` CLI 의존이 사라진다.
P17 §3.2("프롬프트·스키마는 클라이언트가 갖고 요청에 실어 보낸다")가 자연스러워진다 — 서버는
"이미지(선택) + 지시문 + JSON 스키마 → `codex exec` → 구조화 출력" 한 가지만 하면 된다(§5 권고).

---

## 1. 단계 — P16 §4에 ①′ 가 들어간다

```
[캐시] ocr_json/{name}.{hash8}.json
   │
   ▼ ① 조립 — 클라이언트, 규칙                        (Phase 1 ✅ 095·096·097)
Figure 행 + figures.uncertainty() 가 붙인 의심 사유
   │
   ├─ 의심 없음 ─────────────────────────────┐
   ▼ ①′ 재판정 — 서버 POST /figures/detect     │        (Phase 2, 도판 단위, Astra 가 작업 폴더를 훑는다)
     의심 도판만. 결과: bbox 보정·캡션 쪽·판정  │
     클라이언트가 행에 반영(§2.3)               │
   ◀──────────────────────────────────────────┘
   ▼ ② 연결·분할 — 서버 POST /figures/link      (Phase 2, 논문 단위, Astra 텍스트)
Figure.caption(+출처) · FigureEntry
   │        ↑ 사람이 고칠 수 있다
   ▼ ③ 패널 — 서버 POST /figures/panels         (Phase 3, 도판 단위, Astra 이미지)
FigurePanel
   │
   ▼ ④ 표시·검색                                (Phase 5)
```

①′ 는 ② 앞에서만 도는 게 아니다. ②·③ 결과가 이상하면(§2.1의 6·7) 그 도판을 다시 ①′ 로 보낸다.
반영이 bbox 를 바꾸면 `panel_key`가 바뀌어 ③만 다시 돈다(P17 §3.5).

---

## 2. ①′ 재판정 — 클라이언트가 정할 것

### 2.1 의심 사유 — `figures.uncertainty(fig, facts) -> list[str]`, 판정은 한 곳

| 사유 | 조건 | 근거 |
|---|---|---|
| `no_caption` | 그림 블록은 있는데 `caption_hint == ''` 이고 같은 쪽·앞뒤 쪽에 플레이트 표기도 없다 | fsis EC §1-4 · §4-4·4-5 |
| `caption_without_figure` | `Caption`(특히 `Plate`/`Explanation`으로 시작)이 있는 쪽에 그림 블록이 없다 — 설명 쪽일 가능성, 또는 그림이 `Text`로 잡힘 | EC §4-3, devlog 261 |
| `fragmented` | `caption_group_union` 인데 조각이 4개 이상, 또는 `dropped`에 `two_captions`·`gap` 사유가 남은 쪽 | 095 §2.1, EC §4-3 |
| `odd_size` | bbox 면적이 쪽의 85% 이상(캡션 있음)이거나 4,000‰² 미만인데 번호 캡션이 붙어 있다 | EC §4-3 폭 필터 사고 |
| `text_as_figure` | 그림 블록 `html`에 `<img>` 없이 글자만 | devlog 261 "본문이 도판으로" 14건 |
| `split_mismatch` | ③ 결과: `panels == 0` · entries ≥ 2 인데 `is_compound=false` · 패널 수가 항목의 ½ 미만/2배 초과 | P16 §1.2-6·7 |
| `link_mismatch` | ② 결과: `skipped` 이거나 `description_not_printed`·`caption_shared`·`plate_no_entries` (P17 §3.4) | P17 §3.4 |
| `manual` | 사용자가 Text 탭에서 "다시 찾기" | — |

- 사유는 `Figure.uncertain_reasons_json`에 남긴다(검수 배지가 같이 쓴다, P17 §3.10).
- `plate_inferred` 는 의심 사유가 **아니다** — 규칙이 근거를 갖고 추론한 것이고, 검수 목록에서 따로 센다.
- 사유 하나면 보낸다. **비용이 Astra 에이전트 세션 1회**(시간 미실측, 상한 10분) 라 기본으로 전부 보내지 않는다.

### 2.2 요청 — 클라이언트는 의심만 표시하고, 무엇을 볼지는 Astra 가 정한다

```json
POST /figures/detect
{ "client_id": "papermeister-…", "file_hash": "<sha256>",
  "items": [
    { "figure_key": "f12@<detect_key>",
      "page": 13,                              // 0-based (P17 §3.1)
      "hint_bbox_page_1000": [71,125,930,880], // ①의 상자. 없으면 null (caption_without_figure)
      "hints": {"name": "Plate II", "caption_hint": "…", "plate_pages": [12, 40, 41]},  // ①이 아는 것. 참고일 뿐
      "reasons": ["no_caption"] } ],
  "prompt": {"version": "detect-v1-…", "instructions": "…", "schema": {…}} }   // P17 §3.2
```

- **쪽을 고르지 않는다.** 서버가 논문 전체를 작업 폴더(쪽별 텍스트 + 쪽 이미지, ocrserver P02 §3.3)로 만들어 Codex 세션에
  주고, Astra 가 대상 쪽에서 시작해 **필요하면 앞뒤 쪽을 열고, 필요하면 전체 텍스트를 검색**한다(`Explanation of Plate`
  같은 설명 쪽이 30쪽 뒤에 있어도 찾는다). 어디까지 봤는지는 결과의 `pages_consulted` 로 돌아온다.
- 클라이언트가 주는 것은 **힌트**뿐: ①의 상자·이름·같은 쪽 캡션 블록·플레이트 표기가 있는 쪽 번호. 지시문에 "힌트는
  레이아웃 파서의 추정이며 틀릴 수 있다" 를 못박는다.
- OCR 텍스트를 보낼 필요가 없다 — 서버 DB 에 그 논문의 쪽별 OCR 결과가 있다(`pages.markdown`).
- PDF 는 `HEAD /pdfs/{hash}` → 없으면 `POST /pdfs` (P16 §7.2 그대로).

### 2.3 결과 반영 — `figure_store.apply_detect(row, result)`

```json
{ "figure_key": "f12@…", "status": "done",
  "verdict": "kept | adjusted | replaced | split | not_a_figure",
  "figures": [ { "page": 13, "bbox_page_1000": [60,110,940,900],
                 "caption": "PLATE 2. …", "caption_pages": [14],
                 "caption_kind": "same_page | facing_page | explanation_of_plate | none",
                 "confidence": "high" } ],
  "pages_consulted": [12, 13, 14, 41],       // Astra 가 실제로 연 쪽 — 검수·비용 추적
  "notes": ["…"] }
```

| verdict | 행에 하는 일 |
|---|---|
| `kept` | `uncertain_reasons_json` 에 `detect:kept` 기록. 상자 그대로 |
| `adjusted` | `bbox_page_1000` 교체, `bbox_source='detect'`, `blocks_json` 은 원본 블록 유지(되돌릴 근거) |
| `replaced` | 위와 같되 쪽이 바뀔 수 있다 |
| `split` | 원 행은 `dismissed_by='detect'` 로 접고 `figures[]` 마다 새 행 (`assembly='detect'`) |
| `not_a_figure` | `dismissed_by='detect'`. 지우지 않는다 |

- `caption`·`caption_pages` 는 **②의 힌트로만** 둔다(`caption_hint`에 넣지 않고 `detect_caption_json`에). 확정은 ②가 한다 —
  규칙·재판정·연결이 한 칸에 쓰면 P16 §1.2-4가 된다.
- 보호 판정(P17 §3.7): `bbox_locked`·`user_confirmed` 행은 detect 결과를 **적용하지 않고** 검수 사유 `detect_conflicts_user`.
- `detect_key = file_hash|page|hint_bbox|prompt_version` — 입력의 정체만(P17 §3.5 원칙). Astra 가 어디까지 봤는지는 키에 안 들어간다. 캐시 히트면 재호출 없음.
- **비용 상한은 서버가 건다** (세션 시간·턴 수, P02 §3.3). 상한에 걸리면 `status: 'budget_exhausted'` — 실패와 구분해 검수 사유 `detect_budget`.
- 시도 3회(`detect_attempts`), 치명 오류는 잡 전체 정지 (P16 §6.4).

### 2.4 스키마 추가 — P17 §3.6 위에

| 테이블 | 칸 | 이유 |
|---|---|---|
| `Figure` | `uncertain_reasons_json` | §2.1 |
| `Figure` | `bbox_source` ('' \| assembly \| detect \| user) | 누가 상자를 정했나 — 재조립이 detect 상자를 덮지 않게 |
| `Figure` | `detect_key` · `detect_attempts` · `detected_at` · `detect_caption_json` | ①′ 메타 |
| `Figure.dismissed_by` | 값에 `detect` 추가 | §2.3 |
| `Figure.assembly` | 값에 `detect` 추가(split 로 생긴 행) | §2.3 |

---

## 3. ② 연결·분할 — Astra 로 (D2)

- 요청·응답은 **P16 §6.3 + P17 §3.1 명세 v2** 그대로. 바뀌는 건 `options.model = "gpt-6-astra"` 와 워커가 `codex exec`
  (이미지 없이, `--output-schema`) 를 쓴다는 것뿐.
- **쪽 선정·배치를 클라이언트가 하지 않는다** — 같은 원리로 Astra 가 작업 폴더에서 설명 쪽을 직접 찾아 읽는다.
  P17 §3.3(`link_payload` 의 쪽 선정·설명 쪽 우선·플레이트 묶음 배치)은 fsis 가 가장 비싸게 치른 곳인데, 그 판단을 모델에게
  넘기면 **고정 길이 절단(P16 §1.2-5)·배치가 플레이트 하나를 통째로 빠뜨리는 일(DG §4-3)** 이 구조적으로 사라진다.
  클라이언트는 도판 목록 + 힌트(`plate_pages`, `explanation_hints` — P17 §3.3 의 정형 설명 규칙 파서 결과는 그대로 유용)만 보낸다.
  결과에 `pages_consulted` 가 오므로 "설명 쪽인데 안 읽었다" 를 검증(P17 §3.4 `plate_no_entries`)에서 잡는다.
- 검증·반영(`validate_link_result` · `apply_link`)은 P17 §3.4 그대로. ①′ 가 남긴 `detect_caption_json` 이 있으면 힌트로 싣는다.
- 위험: 모델이 스스로 고르면 **빠뜨린 쪽을 모른다**. 그래서 `pages_consulted` 와 클라이언트 검증이 필수이고, Phase 2 게이트에서
  "플레이트가 있는데 항목 0" 비율을 센다. 못 미치면 P17 §3.3 의 클라이언트 쪽 선정을 `suggested_pages` 힌트로 되살린다(API 는 그대로).
- P16이 ②에 Opus 를 고른 이유는 텍스트 추론 강도였고 Astra 의 텍스트 연결 품질은 아직 잰 적 없다. **그래도 Astra 로 확정(D7)**.
  Phase 2 파일럿 게이트(P16 §9)에서 **연결 정확도·지어낸 설명 0건**을 재되, 못 미치면 모델을 바꾸는 게 아니라 프롬프트·힌트
  (`explanation_hints`, `plate_pages`)를 고친다.
- 호출 시간은 **미실측** (Opus 기준 fsis 편당 169초). 파일럿에서 잰다.

---

## 4. ③ 패널 분할 — P16 §6.4 그대로

바뀌는 것 없음. 좌표는 **도판 이미지 기준 0..1000**(`bbox_figure_1000`), 픽셀 변환은 클라이언트(`OcrView` 크롭 경로).
`panel_key` 는 P17 §3.5 권고대로 **entries 를 뺀다**(§5).

---

## 5. P17 의 🔴 확인 2건 — 채택 (2026-09-16)

| 항목 | 권고 | 이유 |
|---|---|---|
| P17 §3.2 프롬프트·스키마를 클라이언트가 갖고 요청에 싣기 | **채택됨 (D5)** | D2 로 세 단계(①′②③)가 전부 같은 CLI 다. 서버는 "지시문+스키마(+이미지) → codex → JSON" 하나면 되고, 프롬프트 규칙(9/16 하루에 넷이 늘었다)은 서버 배포 없이 고친다. dedup 키에 prompt digest |
| P17 §3.5 `panel_key` 에서 entries 제외 + 재연결 규칙 | **채택됨 (D6)** | Astra 는 구독 한도다. 캡션 한 글자에 재분할은 낭비. 박스가 맞으면 다시 잇는다 |

프롬프트 파일: `papermeister/figure_prompts/detect.md` · `link.md` · `panels.md` + `*.schema.json`. `link.md` 출발점은
fsis `plate_links.py`·`claude_augment.py`, `panels.md` 는 `astra_panels.py`(ocrserver `scripts/subfigure/` 에 사본),
`detect.md` 는 새로 쓴다 — 요지는 ocrserver P02 §4.5.

---

## 6. 모듈·레인 — P16 §7.1 에 더하는 것

| 파일 | 역할 |
|---|---|
| `papermeister/figures.py` | `uncertainty()` 추가(§2.1). `link_payload` 는 쪽 선정·배치 없이 도판 목록+힌트만(§3). 판정은 계속 이 한 곳 |
| `papermeister/figure_store.py` | `apply_detect()`(§2.3) — `plan_store` 와 같은 "무엇인지로 맞추기" 규칙 |
| `papermeister/figure_client.py` | `/pdfs` · `/figures/detect` · `/figures/link` · `/figures/panels` · `/figures/jobs`. `client_id` 규칙은 OCR 과 같다 |
| `papermeister/figure_prompts/` | §5 |
| `scripts/detect_figures.py` | ①′ 레인 (`--execute`, `--limit`, `--retry-errors`, `--paper-ids`, `--reasons`) |
| `scripts/link_figures.py` · `split_panels.py` · `figure_review.py` | P16 §7.1 그대로. `figure_review` 에 ①′ 범주(의심 대기 · detect 소진 · `detect_conflicts_user`) |

원격 잡 영속화: P16 §7.2 "대상은 DB 에서 도출" 원칙이라 잡 테이블은 두지 않는다. 대신 각 단계의 `*_key`·`*_attempts` 가
커서다. 서버 잡 id 는 진행창 세션 동안만 메모리에(OCR 과 같음). 앱이 죽으면 다음 실행이 `GET /figures/jobs?client_id=` 로
**끝난 잡을 먼저 거둔다**(P17 §3.10 "반영 대기").

---

## 7. 앱 통합 — P16 §7.3 에 더하는 것

- "Process Figures" 체인: ① → **①′(의심만)** → ② → ③. 끝난 단계는 키로 건너뛴다.
- Text 탭 도판 목록: 의심 사유 배지 · detect 판정 배지 · **"다시 찾기"** 우클릭(`manual`) · ①′ 가 바꾼 상자는 원본 블록과 겹쳐 보여주기.
- 진행창: 단계 4개 진행바. 구독 한도 대기 표시는 P16 §7.3 그대로.

---

## 8. 순서 — P17 §4 에 끼워 넣기

```
[지금, 서버 없음]
 A. 검수 도구 (P17 §3.9)
 B. Windows 파일럿 100편 --execute → 사람이 본다 (Phase 1 게이트)
 C. 조립 후보 셋 측정 (P17 §3.8)
 D. 스키마 (P17 §3.6 + §2.4) · 보호 판정 · 조각 부활 방지 · 예외 격리
 D'. figures.uncertainty() + 테스트 → 파일럿 3,750 도판에 dry-run → **의심 비율을 잰다**
     (10% 안팎이면 설계대로. 40% 면 ①′ 가 기본 경로가 되는 것이라 규칙을 더 고쳐야 한다)
 E. link_payload(도판+힌트만, §3) + 검증·반영 (P17 §3.4). §3.3 의 쪽 선정은 힌트 규칙(`explanation_hints`)만 남긴다
 F. panel_key 재정의 · split_targets · piece box 변환 · review (P17 §3.5·3.10)
 G. 프롬프트 3벌 + 명세 v2 (P17 §3.1 + §2.2·2.3 의 detect) ──▶ ocrserver 에 넘긴다
[서버 착수 후 — ocrserver P02]
 H. figure_client.py · detect_figures.py · link_figures.py · split_panels.py
 I. Phase 2 게이트: 의심 도판 표본 30 의 ①′ 판정을 사람이 본다 + ② 연결 정확도(Astra) + `pages_consulted` 로 놓친 설명 쪽 비율 — 못 미치면 프롬프트·힌트를 고친다
```

---

## 9. 하지 않는 것 (P16 §10 에 더해)

- 의심 없는 도판을 ①′ 로 보내기 — 한도.
- ①′ 결과의 캡션을 `caption` 칸에 바로 쓰기 — ②의 힌트까지만.
- ①′ 가 `user_confirmed`·`bbox_locked` 행을 바꾸기.
- 서버가 레이아웃을 파싱하거나 의심 사유를 정하기 — 판정은 클라이언트 `figures.py` 한 곳.
- 클라이언트가 Astra 에게 줄 쪽을 미리 고르기 — 힌트까지만. 어디를 볼지는 Astra.

## 10. 서버 문서(ocrserver P02) 대조에서 나온 것 — 명세 v2에 넣을 것

P02는 P16 §6·P17 §3.1을 따르고, D1~D8과 어긋나는 데가 없다. 다만 대조에서 **명세에 없는 전제 하나**와 규모 셈이 나왔다.

### 10.1 🔴 작업 폴더의 OCR 텍스트는 서버 DB에서 가져올 수 없다 — 클라이언트가 보낸다

P02 §3.3은 `text/p013.txt`를 wrapper DB `pages.markdown`에서 만든다(§2.2도 "보낼 필요 없음"이라고 썼다). 세 경우에 틀린다:

| 경우 | 왜 |
|---|---|
| **서버에 job이 없다** | RunPod·Direct pod 시절 OCR한 논문. PDF가 없을 수 있는 것과 같은 이유(P16 §2.3) |
| **서버의 최신 job이 클라이언트가 거부한 조각이다** | 2026-09-08 사고 — 서버가 `done_with_errors`로 몇 쪽만 돌려준 걸 이제 클라이언트가 `_reject_incomplete_ocr()`로 버린다. 서버 DB에는 그 조각 job이 그대로 남는다. `jobs`는 `(file_hash, client_id)`로 여러 건이라 "최신"이 조각일 수 있다 |
| **다른 판본** | 재OCR 전후, 다른 PC의 job. 좌표(`bbox`)가 텍스트 판본에 묶여 있어 다른 판본의 텍스트 위에서 ①의 상자를 판정하면 엉뚱한 곳을 본다 |

**진실의 원천은 클라이언트 캐시**(`ocr_json/{name}.{hash8}.json`)다. 그래서:
- 클라이언트가 논문마다 **한 번** `POST /figures/workspace` 로 쪽별 텍스트(캐시 JSON의 `pages[].markdown`, 태그는 서버가 벗긴다)를 올린다. 300쪽 ≈ 1–2MB.
  키는 **`file_hash|ocr_digest`**(캐시 JSON 내용 해시). detect·link 요청은 `ocr_digest`를 싣고, 서버는 같은 키의 작업 폴더가 있으면 쓰고 없으면 `workspace_missing`으로 거절한다.
- 서버 DB 텍스트는 **쓰지 않는다** — 있어도 판본이 같다는 보장이 없고, 확인하는 비용이 보내는 비용보다 크다.
- P02 §3.3 작업 폴더 TTL 7일은 그대로. `ocr_digest`가 바뀌면(재OCR) 새 폴더.
- `detect_key`·`link_key`에도 `ocr_digest`가 들어간다 — 텍스트가 바뀌면 판정도 낡는다(P17 §3.5 "입력의 정체").

### 10.2 규모 — D8(5분에 1건 = 하루 ≈ 288건)로 무엇이 얼마나 걸리나

| 대상 | 호출 수(추정) | 일수 |
|---|---:|---:|
| 파일럿 100편 — ② link | 100 (논문당 1, 배치 없음) | 0.4 |
| 파일럿 — ①′ detect (의심 10% 가정, D'에서 잰다) | ≈ 375 / 3,750 | 1.3 |
| 파일럿 — ③ panels (entries ≥ 2 를 097의 후보 비율 ≈ 20%로) | ≈ 750 | 2.6 |
| **파일럿 합** | **≈ 1,200** | **≈ 4일** |
| 전체 — ② 9,800편 | 9,800 | 34 |
| 전체 — ③ 후보 29,928(097 §5) | 29,928 | 104 |

- 요청 단위라(P16 §7.3) 전체 백필은 계획에 없다. 그래도 **Phase 2·3 게이트가 파일럿만으로 나흘**이라는 건 알고 시작한다. 게이트 표본을 줄이면
  (② 30편 · ③ 도판 100) 하루다 — 게이트는 그렇게 자르고, 나머지 파일럿은 뒤에 돌린다.
- detect·link는 에이전트 세션이라 **호출당 시간이 5분을 넘을 수 있다**(P02 상한 10/20분). 그러면 간격이 아니라 세션 시간이 처리량을 정한다.

### 10.3 그 밖에 맞춘 것

- `pages_consulted`는 detect·link 결과 **스키마 파일에 들어간다**(클라이언트가 스키마를 보내므로). 없으면 §3의 "빠뜨린 쪽" 검증이 불가능.
- ✅ **Codex가 세션 중 폴더 PNG를 스스로 연다 — 실측 확인(2026-09-16 06:27 UTC, ocrserver P02 §3.3)**. `-i` 없이 4쪽 폴더를 주고
  "FIGURE 1 쪽을 찾아 이미지를 보고 묘사·bbox"를 시키니 `rg`로 쪽을 찾고 `view_image`로 열어 시각 묘사 + bbox `[336,590,667,758]`.
  같은 도판의 chandra `data-bbox`는 `335 588 662 756` — 5‰ 안 일치(좌표계 동일 확인). 약 90초. 절충안은 불필요.
  `view_image` 호출은 `--json` 이벤트에 안 찍히므로 `pages_consulted`는 **스키마 필드**로 받는다(위 항목과 일치).
- 서버 dedup 키에 `client_id`가 있다(P16 §6.5) — 같은 논문을 두 PC가 요청하면 두 번 부른다. 구독 한도상 낭비지만 결과가 클라이언트 DB에 있으므로 두 번째 PC는
  Zotero sibling 같은 공유 경로가 생기기 전까진 어쩔 수 없다. 기록만.
- 서버는 쪽 번호를 0-based로 README에 박는다(P02 §3.3) — DB·OCR JSON·요청 모두 0-based. 일치.

## 11. 결정 기록 (2026-09-16, 사용자)

| 질문 | 결정 |
|---|---|
| P17 §3.2 프롬프트 소재 | 클라이언트가 갖고 요청에 싣는다 (D5) |
| P17 §3.5 `panel_key` | entries 제외, 재연결 규칙 (D6) |
| ② 모델 | Astra 확정, 되돌릴 여지 없음 (D7) |
| 호출 속도 | 5분에 1건으로 시작 (D8). 서버 `FIGURES_MIN_INTERVAL=300` |

§10.1은 ocrserver P02 §3.3에 반영됐다(`POST /figures/workspace`, 키 `file_hash|ocr_digest`). 명세 v2에는 G 단계에서 넣는다. 다음은 P17 §4 의 A 부터.
