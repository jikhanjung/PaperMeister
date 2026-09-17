# 104 — P16 H: 서버에 실제로 말하는 부분 — HTTP 클라이언트 · detect 반영 · 레인의 제출/폴링/반영

[클라이언트 계획](../docs/figure_pipeline_client_plan.md) §2.3·§6·§8 H, [명세 v2](../docs/figure_server_spec_v2.md). 서버는 wrapper 0.3.3 + 워커 systemd 가동 중(ocrserver HANDOFF 09-17).
**아직 실제 호출은 하지 않았다** — 구독 사용량을 쓰는 첫 호출은 사용자 확인 뒤.

## 1. `papermeister/figure_client.py`

엔드포인트마다 메서드 하나(`has_pdf`·`upload_pdf`·`has_workspace`·`upload_workspace`·`submit`·`job`·`jobs`·`resume`) + `wait()`.
`X-Client-ID`는 OCR과 같은 설치 id, base URL은 `ocr_pod_url`. JSON이 아닌 응답은 본문 앞 200자를 들어 말한다(ocr.py의 교훈).
`wait()`는 워커가 `paused`(로그인·한도)면 `on_progress`로 알리고 **기다린다** — 이 잡의 실패가 아니고 큐의 자리는 그대로다.

## 2. `papermeister/figure_detect.py` — ①′ 반영

- `detect_items`: 의심 트리거(`figure_review.DETECT_TRIGGERS` — `no_caption` 제외)가 있고 잠기지 않은 행을 **쪽 단위**로 묶는다. 항목 = `key`·`page`·
  `hint_boxes[]`·`figure_keys[]`(워커용) + `figures[]`·`reasons`·`hints`(모델용). 자리표시 행은 상자 없이 `placeholder: true`로 탄다.
- `apply_detect`: 답의 `from`/`dismiss`에서 verdict를 **도출**한다 —
  | 답 | 행 |
  |---|---|
  | `from`에 id 하나, 그 id가 답 하나에만 | 같은 상자면 **kept**, 다르면 **adjusted**(`bbox_source='detect'`, `bbox_locked`) |
  | `from`에 여럿 | **merge**: 새 행(`assembly='detect'`, 잠김, 원본 블록 합집합), 원본은 `dismissed_by='detect'` |
  | 한 id가 답 여럿에 | **split**: 답마다 새 행, 원본 접힘 |
  | `from` 비어 있음 | **new** |
  | `dismiss` · `kind` table/text | 접힘 |
  | 언급 없음 | 그대로(트리거 사유만 지움). 자리표시 행은 쪽에 진짜 도판이 생기면 접힘 |
  이름·플레이트 번호(`_plate_hits`로 파싱)·`plate_inferred`·`page_kind`·`detect_caption_json`(②의 힌트)을 적는다.
  **사람의 행은 절대 안 건드린다** — 애초에 항목에 안 넣고, 답이 그래도 건드리면 `detect_conflicts_user`만 기록.
  새 행·옮긴 행은 잠기고 원본 블록을 가지므로 재조립이 접지도, 조각을 되살리지도 않는다(테스트).

## 3. `papermeister/figure_lane.py` + 레인 세 개의 `--execute`

`local_pdf`·`fetch_pdf`(Zotero에서 pdf_cache로)·`ensure_pdf`(해시가 다르면 거부 — 다른 판본의 좌표를 자르게 된다)·`ensure_workspace`·`run_job`(진행 줄에 워커 상태)·`results_by_key`.
- `link_figures.py --execute [--limit N] [--no-wait]` · `--collect`(먼저 낸 잡을 키로 찾아 반영 — 잡 id는 저장하지 않고 **키가 커서**)
- `detect_figures.py --execute` (신규)
- `split_panels.py --execute`
한 논문의 서버 오류는 그 논문만(`FAILED`), 답이 없으면 시도만 센다.

라이브 dry run: detect — 8803(Zhou & Zhang) 4쪽 `unmarked_plate_page`, 1191 5쪽(`dup_number`·`plate_without_pictures`·…), 674 1쪽 / link 664 due 24 / panels due 0(캡션 전).

## 4. 테스트

`tests/test_figure_detect.py` 6건(쪽 단위 항목·merge→잠긴 새 행+재조립 안전·kept/adjusted/split/table 접기·사람 행 불가침·무응답 시도·가짜 세션으로 클라이언트 폴링+paused). 전체 **515** 통과.

## 5. 첫 실제 호출 — 사용자 확인 뒤, Windows에서 (DB writer + `ocr_pod_url`)

P16 §9 Phase 2 게이트 순서: **② 30편**(link 정확도·지어낸 설명 0건·편당 시간) → ①′ 의심 표본 → ③ 도판 100.
```powershell
python scripts/link_figures.py --paper-ids 664 --execute          # 1편 먼저: 워크스페이스 업로드 → 잡 → 답 → 반영
python scripts/link_figures.py --pilot "$env:USERPROFILE\PaleoBytes\PaperMeister\tmp\p16_pilot.json" --limit 30 --execute
python scripts/figure_review.py --pilot …                          # 반영 상태
```
5분 1건이면 30편 ≈ 2.5시간 — `--no-wait`로 내고 나중에 `--collect --execute`로 거둬도 된다. 서버 쪽은 `journalctl -u ocrserver-figures-worker -f`.
