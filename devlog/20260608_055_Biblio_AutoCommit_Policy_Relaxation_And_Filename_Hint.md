# 055 — placeholder/stub auto-commit 정책 완화 + 파일명 힌트

> 세션 43 (2026-06-08). 052~054에 이어, promoted standalone(파일명 제목)을 더 적극적으로
> 자동 채우기 위한 evaluate 정책 + 추출 프롬프트 개선.

## 동기

collection 단위로 biblio를 돌려보니, OCR은 됐는데 메타데이터가 없는 promoted standalone들이
대거 `needs_review`로 빠짐. `reflect_biblio.py --dry-run`(459 scanned) 사유 분포:
`override_conflict 86 · visual_review_flag 82 · missing_year 78 · low_confidence 4 …`.
사용자 관찰: "confidence medium이면 title=PDF 파일명이라도 다 needs_review." — placeholder는
보호할 curated 데이터가 없는데 소프트 게이트들이 막고 있었음.

## evaluate 소프트 게이트 완화 (commits `2d5133a`, `0e45d10`)

`evaluate`의 field-level 게이트는 stub/placeholder 여부와 무관하게 전부 needs_review로 보냈음.
**relaxable** 도입:

```python
relaxable = _is_stub_paper(paper) or zotero_writeback.title_is_filename_placeholder(paper, paper.title or '')
```

(`_title_is_filename_placeholder` → `title_is_filename_placeholder`로 public화해 biblio_reflect에서
재사용. `_is_stub_paper` = year 없음 + 저자 없음.)

relaxable이면 **soft 게이트 통과**:
- `missing_year` — year 없어도 통과 (placeholder는 어차피 year 없음; 제목/저자/journal이라도 채움)
- `visual_review_flag` — 텍스트 추출 결과로 진행 (정확도 원하면 추후 vision 재추출)
- confidence `medium` — 통과 (high만 요구하던 것 완화)

여전히 보류: hard gap(`missing_title`/`missing_authors`/`unknown_doctype`) + **low** confidence.
**curated 논문(실제 메타데이터 보유)은 full 게이트 유지** — 충돌·불완전 추출로부터 보호.

근거: placeholder/stub은 파일명 외 정보가 없으므로 "텍스트 추출 > 파일명"이 항상 성립.
low-confidence만은 헛값 위험이 커 사람 검토로 남김.

## PDF 파일명 → year/author 힌트 (commit `d6a2266`)

학술 PDF 파일명은 저자성+연도를 인코딩하는 패턴이 매우 흔함(`Smith2023.pdf`,
`Brock & Holmer 2004.pdf`, `Temple1980.pdf`). 추출 텍스트만으로 year를 못 찾던 케이스를 줄이기 위해
`extract_biblio_llm(file_hash, backend, filename)` 추가 — 프롬프트에 `--- SOURCE FILENAME ---`
블록을 끼움. 문구 핵심: **"인코딩된 year/author를 (추측이 아닌) evidence로 취급, 단 명시적 본문이
우선."** (기존 프롬프트의 "Do NOT guess"와 충돌하지 않도록 evidence로 명시.) desktop 두 추출 경로가
`os.path.basename(pf.path)` 전달.

## reflect_biblio.py SSL 패치 (commit `597531a`)

`reflect_all → apply`는 write-back으로 Zotero GET/PATCH(`--dry-run`도 item fetch)를 하는데
스크립트에 SSL monkey-patch가 없어 연구소망에서 실패. 다른 스크립트/데스크톱과 동일 패치 추가 →
기존 PaperBiblio를 새 정책으로 일괄 재평가·반영 가능.

## 운영 관계 (중요)

- `reflect_biblio.py`는 **재평가만**(재추출 X). → 기존 `missing_year` 추출분은 완화 정책으로
  auto_commit되지만 **year는 빈 채**. 파일명으로 연도까지 채우려면 **재추출** 필요(기존 biblio
  무시 옵션은 미구현 — 후속 과제).
- `visual_review_flag` 완화는 텍스트 추출을 그대로 적용하는 것 — 표지/목차의 정확도가 중요하면
  vision 재추출이 정공법(`extract_biblio_vision.py`, 현재 desktop 미연결).
