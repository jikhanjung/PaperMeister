# 096 — P16 Phase 1: 도판 저장과 Text 탭 도판 목록

[P16](./20260914_P16_Figure_Panel_Split.md) Phase 1. 서버 변경 없음.
[095](./20260915_095_P16_Phase0_Figure_Assembly_Survey.md)의 조립 판정을 DB에 남기고, 사람이 Text 탭에서 확인할 수 있게 했다.

## 1. 스키마

`Figure` · `FigureEntry` · `FigurePanel` (P16 §5). 새 테이블이라 `_migrate()` 단계가 없다 — `init_db`의
`create_tables()`가 기존 DB에 없는 테이블을 만든다. §5 계획에서 더한 필드:

| 필드 | 이유 |
|---|---|
| `plate` | 플레이트 번호. 이름(`Plate IV`)만 있으면 ②가 설명 쪽과 짝지을 때 로마 숫자를 다시 풀어야 한다 |
| `caption_hint` | 조립이 찾은 아래 캡션 블록. **`caption`과 칸을 나눴다** — 규칙과 모델이 한 칸에 쓰면 fsis §12-4가 된다 |
| `label_hints_json` | 조각 도판 사이의 패널 라벨 (095 §2.1) |
| `assembled_at` | 언제의 규칙으로 만든 행인가 |
| `dismissed_by` | `reassembly` \| `user`. 재조립이 접은 것만 재조립이 되살린다 |

## 2. 다시 돌려도 안전한 저장 — `papermeister/figure_store.py`

조립 규칙은 계속 바뀐다(095에서 하루에 두 번). 그때 이미 캡션이 연결됐거나 사람이 본 행이 있을 수 있다.
fsis는 규칙이 흔들리는 중에 원본 행을 지워 95건을 잃었다. 그래서 도판을 **무엇인지로** 맞춘다 —
같은 PDF 해시·쪽·상자·조립 방식.

| 경우 | 동작 |
|---|---|
| 다시 나왔다 | 힌트 갱신. 재조립이 접었던 것이면 되살림 |
| 더는 안 나온다 | **접는다**(`dismissed_by='reassembly'`). 지우지 않는다 |
| PDF 해시가 바뀌었다 | 옛 판본의 도판은 접는다 — 상자가 가리키는 문서가 이제 이 문서가 아니다 |
| 사람이 확정(`user_confirmed`)했거나 사람이 접었다 | 그대로 둔다 |
| ②가 이름을 붙였다(`linked_at`) | 힌트는 갱신하되 이름은 그대로 둔다 |

계획(`plan_store`)과 쓰기(`apply_plan`)를 나눠 dry run이 `--execute`가 할 일을 정확히 보여준다.
쓰기는 파일 단위 트랜잭션.

## 3. 스크립트 — `scripts/assemble_figures.py`

대상이 없으면 095의 조사, `--paper-ids`·`--pilot`이 있으면 저장 모드.

- **dry run은 DB를 읽기 전용(`?mode=ro`)으로 연다.** `init_db`는 없는 테이블을 만들기 때문에, 부르는 순간
  사용자 라이브러리에 도판 테이블이 생긴다 — dry run이 그러면 안 된다.
- `--pilot`은 `--pilot-out`이 쓴 목록의 캐시 파일명에서 해시 앞 8자를 읽어 PDF를 찾는다. JSON 첨부 행과 휴지통 행은 뺀다.
- 같은 PDF가 여러 Zotero 부모에 있으면 파일 행마다 따로 저장된다.

라이브 DB dry run (WSL, 읽기 전용): **파일럿 30편 · 도판 295개 · 전부 신규 · 건너뜀 0**.

## 4. Text 탭 도판 목록

구조화 캐시이고 저장된 도판이 있으면 리더 위에 목록이 붙는다(`desktop/components/figure_list.py`).

```
Figures (17)
Plate 2  ·  p. 40  ·  plate, 8 photos  ·  no caption found
Figure 2  ·  p. 2  ·  4 pieces  ·  caption hint
```

- 줄을 누르면 그 쪽으로 간다 — `document_html`이 쪽마다 `<a name="pm-page-N">` 앵커를 단다
- 캡션은 **연결 전에는 "caption hint"라고 쓴다.** 툴팁도 "Caption hint (not yet linked)". 검수하는 사람이
  규칙의 추측을 인쇄된 캡션으로 읽으면 이 목록을 만든 이유가 없어진다
- 목록을 못 읽어도 리더는 뜬다

## 5. 테스트

`test_figure_store.py` 12건(재실행 무변화, 접기·되살리기, 사람 결정 보존, 연결된 이름 보존, 판본 변경, 삭제 연쇄),
`test_figure_list.py` 3건, `test_ocr_layout.py` 앵커 1건. 전체 409건 통과.

## 6. 남은 것 — Phase 1 게이트

- **Windows에서 `--execute`** (앱을 닫고): `python scripts/assemble_figures.py --pilot "%USERPROFILE%\PaleoBytes\PaperMeister\tmp\p16_pilot.json" --execute`
  — WSL에서 `/mnt/c`의 SQLite(WAL)에 쓰는 것은 잠금이 믿을 수 없어 하지 않았다
- 파일럿 30편의 Text 탭 도판 목록을 **사람이 보고 맞다** — 게이트
