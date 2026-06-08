# 047 — OCR JSON 파일명 마이그레이션 재개 + `lastRead` PATCH 버그 픽스

> 세션 43 (2026-06-08). 세션 42([devlog 046](./20260605_046_OCR_JSON_Filename_Migration.md))의 중단된 마이그레이션을 완주.

## 배경

세션 42에서 OCR cache + Zotero sibling attachment 파일명을 `{hash}.json` →
`{pdf_basename}.{hash[:8]}.json`으로 통일하는 마이그레이션(`scripts/rename_ocr_json.py`)을
돌리다 **창을 닫아 중간에 중단**됐다. 전체 9,920편 중 약 1,900편 처리 시점.

스크립트는 idempotent하게 설계돼 있어(이미 새 형식인 행은 `find_pairs`가 skip,
Zotero PATCH도 filename+title이 이미 맞으면 round-trip 생략) **같은 명령 재실행으로
중단 지점부터 이어진다.**

## 실행 환경 메모

- 라이브 DB/캐시/`preferences.json`은 **Windows 홈**(`C:\Users\Jikhan Jung\.papermeister\`)에 있음.
  WSL 홈의 `~/.papermeister`는 5월 13일자 빈 사본 — 헷갈리지 말 것.
- 실제 마이그레이션은 세션 42와 동일하게 **Windows native Python(Anaconda PowerShell)** 에서 실행.
  WSL/NTFS WAL 충돌 + 홈 경로 오인식(`OCR_JSON_DIR`이 WSL 홈을 가리킴) 때문.
- 진척 확인은 WSL에서 `/mnt/c/...`의 라이브 DB를 **read-only**(`mode=ro&immutable=1`)로 조회.

## 진행

1. **재개 1차**: `python scripts/rename_ocr_json.py --sleep 0.1`
   → 7,822편 시도, **7,816 성공 + 6 Zotero failures**.
   - cache renames 7,481 / cache copies 243(1:N) / cache missing 1(자가복구) / collisions 0.
   - cache missing 1건은 "지난 중단 때 캐시는 이미 rename됐는데 DB/Zotero 직전에 끊긴" 행 →
     재실행이 캐시 작업 skip하고 DB+Zotero만 맞춰 자가복구.

2. **6 failures 원인 규명**: 6개 중 4개는 그냥 재시도하니 성공, 2개가 동일 에러로 실패:
   ```
   Zotero PATCH FAIL [UJQ39IRK]: Invalid keys present in item 1: lastRead
   Zotero PATCH FAIL [53KZJJSZ]: Invalid keys present in item 1: lastRead
   ```
   - 404(파일 없음)가 아니라 **스크립트 버그**. 일부 attachment의 `data.lastRead`
     (Zotero에서 마지막으로 열어본 시각, 서버 read-only 필드)를 fetch한 item dict 그대로
     `update_item`에 되돌려보내면서 Zotero가 거부. `lastRead`가 없는 다른 attachment는 안 걸렸음.

3. **픽스**: PATCH 직전 `item['data'].pop('lastRead', None)`.
   - `numPages` 등 다른 필드는 건드리지 않음 — 이미 성공한 7,816개가 그대로 echo해서 보존됐으므로
     쓰기 가능 필드일 수 있어 일관성 위해 `lastRead`만 제거.

4. **재개 2차**: 남은 2개 → `DB updates: 2, Zotero failures: 0`. 완료.

## 최종 상태

| | |
|---|---|
| 전체 JSON PaperFile | 9,935 |
| 새 형식 마이그레이션 완료 | **9,924** |
| 처리 가능 레거시 잔존 | **0** |
| 의도적 orphan 잔존 | **8** |

## orphan 8개 (의도적 잔존)

처리 불가로 남은 레거시 `{hash}.json` = **8개**. 모두:
- `hash=(empty)`, status=processed, zotero_key 있음
- **소속 논문은 이미 현재 PDF의 올바른 새 JSON을 보유**(`has_newform_json=1`)
- 레거시 파일의 filename hash는 그 논문에 더 이상 없는 옛/교체된 PDF를 가리킴

→ **PDF가 교체되며 남은 stale 중복 OCR JSON.** rename 스크립트는 짝 PDF가 없어 새 이름을
유도할 수 없으므로 `find_pairs`가 "no matching PDF sibling"로 skip(스크립트 카운트와 정확히 일치).
레거시 이름이라도 `biblio.load_ocr_pages`의 glob fallback으로 resolve되어 **기능상 무해**.

해당 PaperFile id: `3178, 3996, 4053, 4059, 4082, 4164, 4201, 7230`.

cleanup(DB row + Zotero attachment + 캐시 파일 3곳 삭제)은 파괴적이라 별도 TODO로 분리.

## 시행 착오 — read-only 진척 쿼리의 false positive

WSL에서 진척도를 빠르게 세려고 쓴 휴리스틱
`path GLOB '[0-9a-f]*' AND length(path)=69`이 **3개를 레거시로 오탐**했다.
새 이름(예: `2016 - SCS volume 22 issue 1 Cover and Front matter.pdf.02c5ce5c.json`)이
우연히 **정확히 69자 + hex 문자로 시작**(`2`,`1`,`5`)하면 매칭됨. GLOB가 첫 글자만 검사하기 때문.
엄격 패턴(점이 정확히 1개 = `{64hex}.json`)으로 재검하니 진짜 레거시는 8개.
스크립트 자체의 `LEGACY_RE = ^([0-9a-f]{64})\.json$`는 처음부터 정확했음 — 휴리스틱만 느슨했던 것.

**교훈**: 파일명 패턴 카운트는 첫 글자 GLOB 말고 점 개수/전체 hex 검증으로.
