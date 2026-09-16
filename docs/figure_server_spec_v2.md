# 도판 분할 서버 명세 v2 — PaperMeister → ocrserver

**작성**: 2026-09-16 · **상태**: 확정 초안 (G 단계 산출물). 이 문서가 서버 명세의 **원본**이다 —
[P16 §6](../devlog/20260914_P16_Figure_Panel_Split.md)·[P17 §3.1](../devlog/20260916_P17_P16_Client_Readiness_For_ocrserver.md)·
[클라이언트 계획](figure_pipeline_client_plan.md) §2·§3·§10·[099 §4](../devlog/20260916_099_P16_Uncertainty_Reasons.md)를 하나로 모았고,
서로 어긋나면 이 문서가 이긴다. 서버 쪽 짝 문서는 ocrserver `devlog/20260916_P02_figure_split_service_design.md`.

**클라이언트가 이미 만들어 둔 것**: 요청을 만드는 코드(`papermeister/figure_link.py`·`figure_panels.py`), 답을 검증·반영하는 코드,
그리고 **프롬프트·스키마 3벌**(`papermeister/figure_prompts/`). 서버는 이 명세대로 받아서 `codex exec`를 돌리고 스키마로 검증한 JSON을 돌려주면 된다.

---

## 0. 원칙 (결정 D1~D8, 2026-09-16)

| | |
|---|---|
| 모델 | 세 단계 모두 **gpt-6-astra**, `codex exec`(ChatGPT 구독 로그인). API 키 없음. 워커는 `codex` 하나 |
| 프롬프트 | **요청에 실려 온다**(`prompt: {kind, version, instructions, schema}`). 서버는 도메인을 모른다 — 지시문 뒤에 요청 JSON을 붙여 CLI에 넘기고, **스키마로만** 검증한다 |
| 텍스트 | **클라이언트가 올린다**(§2 workspace). 서버 DB의 OCR 결과는 쓰지 않는다 — RunPod 시절 논문은 서버에 없고, 2026-09-08의 조각 job이 서버에 남아 있으며, 판본이 다를 수 있다 |
| 쪽 번호 | 요청·응답·작업 폴더 전부 **0-based**. PDF 렌더 인덱스와 같다 |
| 좌표 | 쪽 상자는 쪽 기준 0..1000(각 축 독립), 패널 상자는 **도판 이미지 기준** 0..1000. 픽셀은 클라이언트가 만든다 |
| 진실 | 결과의 주인은 **클라이언트 DB**. 서버 결과는 캐시(TTL 30일) |
| 속도 | 워커 전역 최소 간격 `FIGURES_MIN_INTERVAL=300`초로 시작 |
| 실행 단위 | 요청 단위. 전체 백필 없음 |

---

## 1. 엔드포인트

```
HEAD /pdfs/{file_hash}                 200 | 404
POST /pdfs                             multipart file (+client_id) → {file_hash}      없을 때만

POST /figures/workspace                {file_hash, ocr_digest, pages[]} → {file_hash, ocr_digest, pages}   논문당 1회
HEAD /figures/workspace/{file_hash}/{ocr_digest}    200 | 404

POST /figures/detect                   → {job_id}     ①′ 재판정   쪽 단위 항목, 이미지 + 작업 폴더
POST /figures/link                     → {job_id}     ② 캡션      논문 단위, 작업 폴더 텍스트
POST /figures/panels                   → {job_id}     ③ 패널      도판 단위 항목, 크롭 이미지
GET  /figures/{kind}/{job_id}          → job
GET  /figures/jobs?client_id=          → [{job_id, kind, status, submitted_at, completed_at}]   결과 본문 제외
POST /figures/{kind}/{job_id}/resume   치명 정지 뒤 운영자 재개
```

모든 요청에 `client_id`(JSON 필드 또는 `X-Client-ID`). 공평 분배는 OCR과 같은 `_FairScheduler`.

**job** — `{job_id, kind, status: queued|processing|done|paused|failed, submitted_at, completed_at, prompt_version, error, items[]}`.
item마다 `{key, status: queued|processing|done|failed|budget_exhausted|pdf_missing|workspace_missing, result, error, attempts, elapsed_seconds, usage}`.
**한 item의 실패는 그 item만** 실패시킨다. 치명 오류(§6)는 job을 `paused`로.

---

## 2. `POST /figures/workspace` — 논문 작업 폴더

```json
{"client_id": "papermeister-c2a80813",
 "file_hash": "<sha256 of the PDF>",
 "ocr_digest": "<sha256 over the pages' text, client-computed>",
 "pages": [{"page": 0, "markdown": "<Chandra HTML of page 0, verbatim>"}, …]}
```

- 서버는 `/data/figure_ws/{file_hash}/{ocr_digest}/`를 만든다: `README.txt`(쪽 수·규칙·"쪽 번호는 0-based"), `text/pNNN.txt`(태그 벗긴 텍스트),
  `text/all.txt`(`=== page NNN ===` 구분), `pages/pNNN.png`(100 dpi 전 쪽 렌더 — PDF가 있을 때; 없으면 텍스트만 만들고 응답에 `pdf: false`).
- 키가 `file_hash|ocr_digest`이므로 재OCR(텍스트가 바뀜)은 새 폴더다. TTL 7일, 상한 20 GB(오래된 것부터).
- 크기: 파일럿 108편 중앙값 147 KB, 최대 1.8 MB(215쪽).
- detect·link 요청은 `ocr_digest`를 싣고, 폴더가 없으면 item이 `workspace_missing`으로 끝난다(클라이언트가 올리고 다시 낸다).

---

## 3. 프롬프트 블록 (세 요청 공통)

```json
"prompt": {"kind": "link", "version": "link-v1-80d89c4e6900", "instructions": "<markdown>", "schema": {…JSON Schema…}}
```

- `version`은 지시문+스키마의 해시에서 클라이언트가 만든다. 서버 dedup 키와 `figure_calls` 기록에 그대로 쓴다.
- 워커 호출: `codex exec -C <작업 폴더 또는 임시 폴더> --sandbox read-only --model gpt-6-astra [-i <png>…] --output-schema <schema 파일> --output-last-message <out> -` 로,
  stdin에 **`instructions` + 빈 줄 + 요청 JSON(prompt 블록 제외)** 을 준다. fsis `astra_cli_bbox.run_command` 재사용(프로세스 그룹 kill, 타임아웃).
- 서버는 출력이 **스키마에 맞는지만** 검증한다(형식이 흐트러지면 첫 JSON 객체를 중괄호 깊이로 회수 시도, 그래도 안 되면 item 실패). 도메인 검증은 클라이언트가 한다.
- 스키마는 Codex 구조화 출력 제약(모든 키 required, `additionalProperties: false`)을 이미 지킨다.

---

## 4. `POST /figures/link` — ② 캡션 연결·분할 (논문 단위)

요청(클라이언트 `figure_link.link_payload`가 만든다):

```json
{"client_id": "…", "file_hash": "…", "ocr_digest": "…", "page_count": 126,
 "figures": [
   {"figure_id": "984", "page": 14, "bbox_page_1000": [71,125,930,880],
    "assembly": "plate_page_union", "page_kind": "plate", "name_hint": "Plate II", "plate": 2, "plate_inferred": false,
    "caption_hint": "", "label_hints": [], "reasons": [], "locked": false},
   {"figure_id": "985", "page": 3, "bbox_page_1000": […], "assembly": "single", "page_kind": "body",
    "name_hint": "Fig. 4", "caption_hint": "Fig. 4. …", "locked": true,
    "caption": "Fig. 4. A person wrote this.", "entries": [{"label": "a", "description": "…"}]}
 ],
 "hints": {"plate_pages": [12, 40, 41], "explanation_pages": [12], "caption_pages": [3, 7]},
 "prompt": {…}}
```

- 워커: `-C <작업 폴더>`, **이미지 없음**. Astra가 `text/all.txt`를 grep하고 필요한 쪽을 연다. 세션 상한 20분(초기값).
- `locked` 도판은 답에 포함하지 않는다(들어 있으면 클라이언트가 버린다).
- item은 하나(논문). dedup 키 `file_hash|ocr_digest|figures digest(id·쪽·상자)|prompt.version`.

응답 `result`(스키마 `figure_prompts/link.schema.json`):

```json
{"figures": [{"figure_id": "984", "name": "Plate II", "caption": "PLATE II. Oistodus …",
              "caption_source": "explanation_page", "caption_pages": [12], "continuation_of": null,
              "entries": [{"label": "1", "printed_label": "1", "description": "Lateral view, YSUG 00287", "specimen_number": "YSUG 00287"}]}],
 "skipped": [{"figure_id": "990", "reason": "explanation_not_found"}],
 "pages_consulted": [3, 12, 13, 14, 41],
 "notes": ["Plate IV is printed twice, pp. 40 and 60"]}
```

클라이언트 검증(참고): 보낸 적 없는 id·논문 밖 쪽·잠긴 도판은 거절, 캡션·설명이 쪽 텍스트의 단어로 안 이루어져 있으면 검수 사유, 항목이 줄면 안 덮음, skipped는 기존 값 유지.

---

## 5. `POST /figures/panels` — ③ 패널 분할 (도판 단위)

요청(`figure_panels.panel_item`):

```json
{"client_id": "…", "file_hash": "…",
 "items": [{"figure_key": "984@<panel_key>", "page": 14, "bbox_page_1000": [71,125,930,880],
            "caption": "PLATE II. …", "entries": [{"label": "1", "description": "…"}],
            "piece_boxes_figure_1000": [[0,0,475,543], …], "label_hints": [], "dpi": 216}],
 "prompt": {…}}
```

- 워커: `PDF_DIR/{file_hash}.pdf`의 `page`를 `dpi`로 렌더 → `bbox_page_1000`으로 크롭(각 축 독립, 약간의 여백은 두지 않음 — 클라이언트가 상자를 정한다) → PNG 한 장을 `-i`로. **작업 폴더 없음**, "다른 파일을 읽지 말 것". PDF가 없으면 item `pdf_missing`.
- dedup 키 `figure_key|prompt.version` (`panel_key`에 해시·쪽·상자·dpi가 이미 들어 있다).
- 응답 item `result`(스키마 `panels.schema.json`) + 서버가 붙이는 `image_size: [w, h]`:

```json
{"is_compound": true, "figure_kind": "fossil_plate", "non_compound_reason": "",
 "panels": [{"label": "1", "bbox_figure_1000": [12, 8, 331, 402], "caption_indices": [0], "confidence": "high"}],
 "annotation_indices": [], "notes": ["shared scale bar bottom right"]}
```

---

## 6. `POST /figures/detect` — ①′ 재판정 (쪽 단위)

요청(클라이언트가 만든다 — 한 쪽의 의심 도판 전부가 **한 항목**):

```json
{"client_id": "…", "file_hash": "…", "ocr_digest": "…",
 "items": [{"item_key": "<file_hash>|<page>|<ocr_digest>|<prompt.version>", "page": 27,
            "reasons": ["unmarked_plate_page"],
            "figures": [{"figure_id": "1201", "bbox_page_1000": [48,70,282,188], "assembly": "single",
                         "name_hint": "", "caption_hint": "", "reasons": ["unmarked_plate_page"]}, …],
            "hints": {"plate_pages": [26, 30], "explanation_pages": [26]}}],
 "prompt": {…}}
```

- `figures`가 **비어 있을 수 있다**(`plate_without_pictures`·`caption_without_figure` — 파서가 상자를 못 만든 쪽).
- 워커: `-C <작업 폴더>`, `-i pages/pNNN.png`에 **힌트 상자를 빨간 선으로 그린 사본**(대상 쪽) 한 장. Astra가 앞뒤 쪽·전체 텍스트를 스스로 본다(Codex가 세션 중 폴더 PNG를 여는 것은 실측 확인됨, P02 §3.3). 세션 상한 10분.
- dedup 키 = `item_key`.

응답 item `result`(스키마 `detect.schema.json`):

```json
{"figures": [{"bbox_page_1000": [40, 60, 960, 940], "from": ["1201", "1202", "1203"],
              "name": "Plate IV", "name_inferred": true, "kind": "plate",
              "caption": "", "caption_pages": [26], "caption_kind": "explanation_page", "confidence": "high"}],
 "dismiss": ["1210"],
 "pages_consulted": [26, 27, 28],
 "notes": []}
```

verdict는 열거형이 아니라 **`from`으로 도출**한다(클라이언트): 같은 상자로 하나 → kept, 다른 상자로 하나 → adjusted, 한 결과의 `from`에 여럿 → **merge**,
한 id가 여러 결과에 → split, `dismiss` → not_a_figure, `from`이 빈 결과 → 새 도판. 어느 쪽에도 없는 파서 도판은 그대로.

---

## 7. 워커 요구

| 항목 | 내용 |
|---|---|
| 실행 | 호스트 systemd, `codex` 하나. 컨테이너(wrapper)는 SQLite의 유일한 writer; 워커는 내부 API(`/internal/figures/claim`·`…/result`·heartbeat)로만. heartbeat 끊기면 item을 `queued`로 |
| 환경 | 하위 프로세스 env에서 `OPENAI_API_KEY`·`CODEX_API_KEY`·`ANTHROPIC_API_KEY` 제거(남으면 종량제). `PATH`에 `codex` 명시(nvm 밑이면 "login required"로 잘못 보고됨) |
| 순서 | 워커 큐 하나, **동시 1**, 호출 사이 `FIGURES_MIN_INTERVAL`초 |
| 시도 | item 3회. **치명**(`login required`·`usage limit`·`rate limit`·`Codex CLI not found`)은 **시도로 세지 않고** job을 `paused`, 워커 정지. 문구는 **stdout·stderr 양쪽**에서 찾는다. 해제 시각은 문구에서 읽되 박아두지 않는다. 운영자가 `codex login` 뒤 `/resume` |
| 타임아웃 | 프로세스 그룹째 kill. 세션 상한(detect 10분·link 20분·panels 5분 초기값)에 걸리면 `budget_exhausted` |
| 기록 | 호출마다 `figure_calls(kind, model, prompt_version, usage, elapsed, pages_consulted)` |
| 버전 | 워커 코드는 wrapper 이미지와 **같은 git 태그**에서 |
| `/status` | figures 큐 카드: 대기·처리·오늘 호출·마지막 치명 오류·워커 heartbeat |

---

## 8. 규모 (파일럿 100편, 클라이언트 실측)

| | |
|---|---|
| ② link | 논문 108 · 도판 3,752 · 요청 중앙값 6 KB(최대 124 KB) |
| workspace | 중앙값 147 KB · 최대 1.8 MB · 합 36 MB |
| ①′ detect | 쪽 ≈ 140 (no_caption 제외; 099 §5) |
| ③ panels | ②가 항목 ≥ 2를 돌려준 도판 — 추정 ≈ 750 |
| 5분 1건이면 | 게이트 표본(② 30편·③ 도판 100)은 하루, 파일럿 전체 ≈ 4일 |

---

## 9. 서버가 하지 않는 것

레이아웃 파싱 · 규칙 판정 · 의심 사유 판정 · 프롬프트 보관 · 도메인 검증 · 패널 이미지 저장 · 클라이언트로의 콜백 · Astra 외 모델.
