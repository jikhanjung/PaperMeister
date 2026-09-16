# 도판 분할 서버 명세 v2 — PaperMeister → ocrserver

**작성**: 2026-09-16 · **상태**: 확정 (G 단계 산출물, **wrapper 0.3.2와 대조해 맞춤**). 이 문서가 클라이언트가 보내고 믿는 것의 **원본**이다 —
[P16 §6](../devlog/20260914_P16_Figure_Panel_Split.md)·[P17 §3.1](../devlog/20260916_P17_P16_Client_Readiness_For_ocrserver.md)·
[클라이언트 계획](figure_pipeline_client_plan.md) §2·§3·§10·[099 §4](../devlog/20260916_099_P16_Uncertainty_Reasons.md)를 하나로 모았다.
서버 쪽은 ocrserver `docs/WRAPPER_API.md` "도판 분할" 절(wrapper 0.3.2, `scripts/figures_worker.py`)이 구현이고, 이 문서는 그 위에서
**항목 안의 내용**(워커가 모델에 그대로 넘기는 것)과 **응답 스키마**(클라이언트가 보내는 것)를 정한다. 전송 형식은 서버 문서가 이긴다.

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

## 1. 엔드포인트 (wrapper 0.3.2 — 구현됨)

```
HEAD/GET /pdfs/{file_hash}                         200 | 404
POST     /pdfs                                     multipart file (+client_id) → 201 {file_hash, existed, size}   없을 때만

POST     /figures/workspace                        {client_id, file_hash, ocr_digest, pages[]} → 201.  PDF 없으면 404 pdf_missing
HEAD/GET /figures/workspace/{file_hash}/{ocr_digest}   200 | 404

POST     /figures/{kind}                           kind ∈ detect | link | panels → 202 {job_id, total, cached, queued}
GET      /figures/{kind}/{job_id}                  job + 항목별 결과
GET      /figures/jobs?client_id=&kind=&status=    목록 (결과 본문 없음)
POST     /figures/{kind}/{job_id}/resume?retry_errors=   실패·예산 소진 항목 재큐 (retry_errors=true면 시도 초기화)
POST     /figures/worker/resume                    치명 정지 해제 (호스트에서 원인을 고친 뒤)
GET      /api/figures                              대시보드 요약
```

**요청 공통**:
```json
{"client_id": "papermeister-…", "file_hash": "<sha256>", "ocr_digest": "<…>",
 "items": [{"key": "…", …}], "prompt": {"kind", "version", "instructions", "schema"},
 "options": {"model": "gpt-6-astra", "effort": "high", "dpi": 216}, "force": false}
```
`key`는 응답에 그대로 돌아온다. dedup: `(kind, file_hash, ocr_digest, item 내용, prompt, options)`가 같고 같은 `client_id`로 `done`이면 `cached`.
항목 상태 `queued → processing → done | failed(3회) | budget_exhausted`, 잡 상태 `queued | processing | done | done_with_errors | failed`.
치명 오류는 시도로 세지 않고 항목을 큐로, 워커를 `paused`로(`GET` 응답의 `worker.state`·`paused_reason`).

---

## 2. `POST /figures/workspace` — 논문 작업 폴더

```json
{"client_id": "papermeister-c2a80813",
 "file_hash": "<sha256 of the PDF>",
 "ocr_digest": "<sha256 over the pages' text, client-computed (figure_link.ocr_digest)>",
 "pages": [{"page": 0, "markdown": "<Chandra HTML of page 0, verbatim>"}, …]}
```

- **PDF가 먼저 있어야 한다**(404 `pdf_missing`) — `HEAD /pdfs/{hash}` → 없으면 `POST /pdfs`.
- 서버는 `figure_ws/{file_hash}/{ocr_digest}/`를 만든다: `README.txt`, `text/pNNN.txt`(블록마다 `[Label x0 y0 x1 y1] text`, 그림은 `[image: alt]`),
  `text/all.txt`(`=== page N ===`), `pages/pNNN.png`(100 dpi 전 쪽). 재OCR은 새 폴더. TTL 7일.
- 크기: 파일럿 108편 중앙값 147 KB, 최대 1.8 MB(215쪽).
- detect·link 요청은 `ocr_digest`를 싣는다(작업 폴더 키). 클라이언트는 `HEAD /figures/workspace/…`로 확인하고 없으면 올린다.

---

## 3. 프롬프트 블록 (세 요청 공통)

```json
"prompt": {"kind": "link", "version": "link-v1-80d89c4e6900", "instructions": "<markdown>", "schema": {…JSON Schema…}}
```

- `version`은 지시문+스키마의 해시에서 클라이언트가 만든다(`figure_prompts.load(kind)`). 서버 dedup 키와 `figure_calls` 기록에 그대로 쓴다.
- 워커는 `instructions` 뒤에 `=== INPUT (JSON) ===` 구분선과 JSON 하나를 붙여 `codex exec` stdin으로 보낸다. JSON은 `{kind, item: <요청 항목 그대로>, workspace: {…}, …}` —
  즉 **항목 안에 넣은 것은 전부 모델에게 간다**(§4~6의 항목 필드는 그래서 "워커가 읽는 것"과 "모델이 읽는 것"으로 나뉜다). `schema`는 `--output-schema`.
- 서버는 출력이 **스키마에 맞는지만** 검증한다(type/required/properties/items/enum). 도메인 검증은 클라이언트가 한다.
- 스키마는 Codex 구조화 출력 제약(모든 키 required, `additionalProperties: false`)을 지킨다 — 테스트가 검사.

---

## 4. `POST /figures/link` — ② 캡션 연결·분할 (논문 단위)

요청(클라이언트 `figure_link.link_payload` → `items: [link_item]`, 논문당 항목 하나):

```json
{"client_id": "…", "file_hash": "…", "ocr_digest": "…",
 "items": [{"key": "<hash12>@<digest12>@<prompt.version>", "page_count": 126,
   "figures": [
     {"figure_id": "984", "page": 14, "bbox_page_1000": [71,125,930,880],
      "assembly": "plate_page_union", "page_kind": "plate", "name_hint": "Plate II", "plate": 2, "plate_inferred": false,
      "caption_hint": "", "label_hints": [], "reasons": [], "locked": false},
     {"figure_id": "985", "page": 3, "bbox_page_1000": […], "assembly": "single", "page_kind": "body",
      "name_hint": "Fig. 4", "caption_hint": "Fig. 4. …", "locked": true,
      "caption": "Fig. 4. A person wrote this.", "entries": [{"label": "a", "description": "…"}]}
   ],
   "hints": {"plate_pages": [12, 40, 41], "explanation_pages": [12], "caption_pages": [3, 7]}}],
 "prompt": {…}, "options": {"model": "gpt-6-astra", "effort": "high"}}
```

- 워커가 읽는 것: `figures[].figure_id/page/bbox_page_1000`. 나머지는 모델용. `-C <작업 폴더>`, **이미지 없음**. 세션 상한 1200 s.
- `locked` 도판은 답에 포함하지 않는다(들어 있으면 클라이언트가 버린다).

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
 "items": [{"key": "984@<panel_key>", "page": 14, "bbox_page_1000": [71,125,930,880],
            "caption": "PLATE II. …", "entries": [{"label": "1", "description": "…"}],
            "piece_boxes_figure_1000": [[0,0,475,543], …], "label_hints": [], "dpi": 216}],
 "prompt": {…}, "options": {"model": "gpt-6-astra", "effort": "high", "dpi": 216}}
```

- 워커가 읽는 것: `page`·`bbox_page_1000`·`caption`·`entries`(fsis 프롬프트 호환 이름 `original_caption`·`existing_subfigures`로도 넣어 준다)와 `options.dpi`.
  `item.dpi`는 `options.dpi`와 같은 값이어야 한다(클라이언트가 둘 다 216으로 보낸다). 렌더는 `figure.png` 한 장, `-i`, 작업 폴더 없음. 세션 상한 600 s.
- 응답 `result`(스키마 `panels.schema.json`). 이미지 크기는 워커의 `image` 메타에서 온다:

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
 "items": [{"key": "<hash12>|27|<digest12>|<prompt.version>", "page": 27,
            "hint_boxes": [[48,70,282,188], [294,70,527,188], …],          // 워커가 그린다 — figures[]와 같은 순서
            "figure_keys": ["1201", "1202", …],                             // 상자와 같은 순서
            "reasons": ["unmarked_plate_page"],
            "figures": [{"figure_id": "1201", "bbox_page_1000": [48,70,282,188], "assembly": "single",
                         "name_hint": "", "caption_hint": "", "reasons": ["unmarked_plate_page"]}, …],
            "hints": {"plate_pages": [26, 30], "explanation_pages": [26]}}],
 "prompt": {…}, "options": {"model": "gpt-6-astra", "effort": "high"}}
```

- 워커가 읽는 것: `page`·`hint_boxes`(빨간 선 + 순서 번호로 대상 쪽 150 dpi 렌더에 그림; 쪽 전체 상자는 안 그림)·`figure_keys`. `figures[]`·`reasons`·`hints`는 모델용.
- `hint_boxes`가 **비어 있을 수 있다**(`plate_without_pictures`·`caption_without_figure` — 파서가 상자를 못 만든 쪽). 그때 `figures`도 비어 있다.
- `-C <작업 폴더>`, `-i items/<id>/target.png`. Astra가 앞뒤 쪽·전체 텍스트를 스스로 본다(실측 확인, P02 §3.3). 세션 상한 600 s.

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
(wrapper 0.3.2 + `scripts/figures_worker.py`가 이미 이렇게 한다 — 클라이언트가 기대는 전제로 적어 둔다)

| 항목 | 내용 |
|---|---|
| 실행 | 호스트 systemd 유닛(`ocrserver-figures-worker`, codex 로그인이 있는 사용자), `codex` 하나. wrapper가 SQLite의 유일한 writer; 워커는 내부 API로만. heartbeat 끊기면 항목 재큐(1800 s) |
| 환경 | 하위 프로세스 env에서 API 키 제거. `PATH`에 `codex` 명시 |
| 순서 | 한 번에 한 항목, 호출 사이 `min_interval_s`(서버가 claim 응답으로 알려줌, 기본 300) |
| 시도 | 항목 3회. **치명**(`login required`·`Codex CLI not found`·`usage limit`·`rate limit`)은 시도로 세지 않고 항목을 큐로, 워커 `paused`. 호출 전 `codex login status` + 호출 후 stdout·stderr. 해제는 `/figures/worker/resume` |
| 타임아웃 | 프로세스 그룹 kill. detect 600 · link 1200 · panels 600 s → `budget_exhausted` |
| 기록 | `run/a<시도>/`에 prompt·schema·response·events·stderr·run.json; `figure_calls` |
| 상태 | `/status` 카드 · `GET /api/figures` · `journalctl -u ocrserver-figures-worker -f` |

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
