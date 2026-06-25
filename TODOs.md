# TODOs

작업 단위 할 일 추적. 상세 진행 상황·컨텍스트는 [`HANDOFF.md`](./HANDOFF.md), 설계 근거는 `devlog/`.

규칙: `[ ]` 미완 / `[x]` 완료 / `[~]` 진행 중. 완료 항목은 한동안 두었다가 정리.

---

## P11 — References 추출 + 인용 네트워크 (Phase 1)

설계: [devlog P11](./devlog/20260625_P11_References_Extraction_Citation_Network.md)

### 코드 (완료, WSL 검증)
- [x] `models.py`: `Reference` 테이블 + `database.py ALL_TABLES` 등록
- [x] `biblio.py`: `extract_references_block` (헤딩 탐색 EN+CJK + appendix 끊기 + fallback)
- [x] `biblio.py`: `split_reference_entries` (번호형 결정적 분할) + `_REFS_PROMPT` + `_parse_llm_json_array` + `extract_references_llm`
- [x] `biblio.py`: `_call_qwen`에 `max_tokens` 파라미터
- [x] `scripts/extract_references.py` (`--scope`/`--paper-ids`/`--reextract`/`--execute`, delete-and-replace 멱등)
- [x] `scripts/resolve_references.py` (DOI → 토큰 후보 → year+저자 스코어, `--threshold`/`--reresolve`/`--execute`)
- [x] `papermeister/references.py`: `save_references` 공용 저장 헬퍼 (delete-and-replace 멱등, 스크립트+데스크톱 공유)
- [x] **desktop 우클릭 "Extract References"** — Paper(processed/review/done) / 폴더 / My Library 세 레벨. 전용 큐(`_refs_queue`) + `ReferencesWindow` 진행창, biblio와 동일 UX
- [x] **`Paper.references_checked` 체크 필드** — references 없는 paper 재파싱 방지. 마이그레이션 컬럼 추가 + 기존 Reference 보유 paper 백필. 타겟은 `references_checked==False`만. "no references section"은 실패가 아닌 checked-empty(`extract_references_llm`이 `[]` 반환)
- [x] **헤딩 다양성 보강** — 다국어(EN/FR/DE/ES/IT/PT/CJK) + 번호/콜론/접미사 변형, plain 라인 매치, 줄 앵커 오탐 방지. 헤딩 미검출 시 마지막 2p LLM fallback (35종 매치/8종 거부 검증)
- [x] 전체 self-test (compile + 임시 DB save/migration/backfill + 헤딩 35종 + headless 데스크톱 임포트)

- [x] **추출 직후 자동 resolve** (사용자 요청) — `references.py`에 resolve 로직 통합(`build_resolution_index`/`resolve_one`/`resolve_paper_references`). desktop 추출 워커가 save 후 자동 resolve(배치당 인덱스 1회 빌드·캐시, 드레인 시 무효화), 진행창에 "N references, M in library" 표시 + 완료 후 References 탭 자동 갱신. CLI도 추출 후 일괄 resolve(`--no-resolve`로 opt-out). `resolve_references.py`는 공용 헬퍼 사용하도록 리팩터

### 라이브 실행 + 튜닝 (대기 — Windows + ocrserver Qwen3)
- [ ] **소수 샘플 추출 품질 확인**: `extract_references.py --paper-ids <몇 개> --execute` → 번호형/비번호형/CJK 각각 파싱 결과 육안 검증
- [ ] **resolve 임계값 튜닝**: `resolve_references.py`(dry-run)로 title 매치 샘플 점검 → `--threshold` 조정 → `--execute`
- [ ] DOI/제목 매칭 정확도 측정 (false positive 확인)
- [ ] 라이브러리 전체 추출 완주 (`--scope all --execute`)

### UI / 활용
- [x] **DetailPanel References 탭** — 해당 논문의 references를 카드로 나열. 카드마다 citation(저자·연도·저널) + 제목 + held(in library, 클릭→이동) / cited-only 배지. raw 원문은 툴팁. lazy 빌드(탭 4번째). `paper_service.load_references` + `ReferenceRow.citation()`
- [x] **DetailPanel cited-by 역방향 표시** — References 탭 상단에 "CITED BY" 섹션(이 논문을 인용한 라이브러리 논문들, 카드 클릭→이동). `paper_service.load_cited_by`(resolved_paper==this, 최신순). 양방향(outgoing references + incoming cited-by) 한 탭에 통합
- [ ] 인용 네트워크 export(GEXF/CSV) 또는 `db_stats.py`에 cited 카운트 추가

### 범위 밖 (향후 Phase)
- [ ] Phase 2: `CitedWork` 정규화 노드 (외부 논문 dedup → most-cited-external·co-citation)
- [ ] Level 3: in-text `[12]` 마커 ↔ Reference 연결 (citation context)

---

## 기타 (HANDOFF "다음 할 일"에서 발췌)

상세는 HANDOFF.md 참조.

- [ ] **needs_review 일괄 검토** — Library "Needs Review" 필터 + Biblio 탭 대조 UI (Phase D 후처리, 현 자연스러운 다음 초점)
- [ ] **48편 extracted 잔존분 재시도** — bookSection 400 픽스 효과 + cross-machine meta sync 확인
- [ ] **Apply Biblio Zotero write-back 추가 검증** — auto_commit 1건 Zotero version 증가 + papermeister_meta in-place replace + cross-machine `BiblioAlreadyApplied` 스킵
- [ ] **Process / Settings 액션 end-to-end 실증** (Rail 버튼 → 다이얼로그 → 실제 동작)
- [ ] desktop: source/folder 단위 batch Reflect 트리거 + 결과 다이얼로그
- [ ] **PaperFolder remove (컬렉션 멤버십 양방향 sync)** — 현재 add-only, 정책 결정 필요
- [ ] 에러 핸들링 보강 (암호화/파손 PDF), 테스트 코드 작성
