# 105 — P16 Phase 4a: 도판 결과가 캐시 JSON과 Zotero sibling을 탄다 (DB ↔ JSON 동기화)

사용자 제안(2026-09-18): "패널 분리가 완료되면 JSON까지 같이 업데이트하면 되겠다." 도판 단계는 기관망의 wrapper 서버가 있어야 도니, 다른 PC·기관 밖 사용자는
**처리는 못 해도 결과는 볼 수 있어야** 한다. biblio의 `papermeister_meta`가 이미 다니는 길(캐시 JSON → Zotero sibling in-place 교체)을 그대로 쓴다.

## 1. `papermeister/figure_share.py`

| | |
|---|---|
| `export_figures(pf, pages)` | 파일의 **모든 행**(접힘·자리표시 포함 — 사람의 접기는 결정이다)을 id 없이 직렬화. 단계 결과·타임스탬프·항목·패널·사람의 주장(`user_confirmed`·잠금). `continuation_of`는 (쪽·상자·조립) 정체로. `ocr_digest`(어느 OCR 텍스트에 대한 결과인가)와 `file_hash`를 박는다 |
| `write_to_cache(pf, push)` | 캐시 JSON에 `figures` 키로 쓰고(원자적, `papermeister_meta` 보존) pref `zotero_upload_ocr_json`이면 sibling 교체(`text_extract.push_sibling_json` — biblio와 공유하도록 뽑아냄) |
| `import_figures(pf, data, pages)` | 정체로 행을 맞춘다: 없으면 통째로 생성, 있으면 **단계별 타임스탬프가 더 새 쪽**의 결과만, **사람이 잠근 로컬 행은 절대 안 덮음**, export의 사람 결정은 아무도 안 잠근 행에만. `file_hash`가 다르거나 **`ocr_digest`가 다르면(재OCR) 무시** — 상자가 다른 텍스트를 가리킨다 |

## 2. 동기화 시점

- **DB → JSON**: 레인 셋(`link`·`detect`·`split_panels`)의 반영과 `figure_curate` 뒤, 논문마다 `share(pf)`. best-effort — DB엔 이미 결과가 있다.
- **JSON → DB**: (a) 캐시 miss로 sibling을 받을 때(`_try_fetch_sibling_json`) (b) Text 탭이 도판 목록을 처음 읽을 때 행이 없으면(`paper_service._import_shared_figures`) (c) `assemble_figures.py --execute`가 행 없는 파일을 만나면 규칙 저장 전에 — 정체로 맞아떨어지게.
- `ocr_digest`는 `pages[].markdown`만 해시하므로 `figures` 키를 더해도 작업 폴더 키가 안 바뀐다.

## 3. `scripts/figure_share.py --export|--import`

백필·수동용. 파일럿 108편 `--export --no-push`: Westergård JSON에 행 24(캡션·항목 33 등, 패널은 ③ 진행 중), `papermeister_meta` 보존, 파일 417 KB(텍스트가 대부분).
**Zotero에는 아직 안 올렸다** — pref가 켜져 있으면 다음 레인 반영부터 올라간다.

## 4. 테스트

`tests/test_figure_share.py` 5건 — 정체로 직렬화 · 다른 라이브러리에 통째 생성 + 멱등 · 새 결과만 갱신 + 사람 행 불가침 · 다른 텍스트/PDF 거부 · 캐시 왕복. 전체 526 통과.
