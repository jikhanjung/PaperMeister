# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: MVP 동작 확인 — OCR 실 연동 성공, 25개 논문 처리 중**

GUI 실행 확인. RunPod OCR 실 연동 성공 (Chandra2-vllm).
Trilobite Shape 컬렉션 25개 PDF 중 일부 처리 완료, 나머지 재처리 필요.

---

## 다음 할 일

- [ ] Trilobite Shape 나머지 파일 Reprocess All로 처리 완료
- [ ] Zotero 연동 모듈 구현 (Source type='zotero')
- [ ] 검색 결과 매칭 패시지 하이라이트 표시
- [ ] 에러 핸들링 보강 (암호화된 PDF 등)
- [ ] 테스트 코드 작성

---

## 결정된 사항

| 항목 | 결정 | 비고 |
|------|------|------|
| GUI | PyQt6, 3-pane | 소스/폴더 트리 \| 논문 목록 \| 상세 뷰 |
| DB | SQLite + FTS5 | `~/.papermeister/papermeister.db` |
| ORM | Peewee 4.x | `DatabaseProxy` + `SqliteDatabase` |
| 텍스트 추출 | 항상 RunPod OCR | 텍스트 레이어 유무 불문 |
| OCR 응답 | `markdown` 필드 사용 | `chunks`도 raw JSON에 보존 |
| Raw OCR 보존 | `~/.papermeister/ocr_json/{hash}.json` | 캐시 재활용 가능 |
| 메타데이터 | PyMuPDF (fitz) | PDF 내장 메타데이터만 |
| 검색 | FTS5 BM25 | title×10, authors×5, text×1 |
| Import 흐름 | Scan → Process 분리 | ScanWorker(빠름) → ProcessWindow(OCR) |
| 처리 UI | 독립 윈도우 (ProcessWindow) | 비모달, 로그 누적, 프로그레스 바 |
| 재처리 | 기존 데이터 삭제 후 재생성 | 멱등성 보장, 캐시 있으면 OCR 스킵 |

---

## 미결 사항

- Zotero API 연동 방식 미결정
- 검색 결과 매칭 패시지 하이라이트 표시 방식

---

## 최근 세션 요약

**2026-03-30**
- PRD → MVP 전체 구현 (0 → 1)
- 기술 스택: PyQt6 + SQLite/FTS5 + Peewee 4.x + PyMuPDF + RunPod OCR
- 3-pane UI, ScanWorker/ProcessWorker 분리
- Chandra2-vllm 응답 구조 대응 (`markdown` 필드, `chunks` 보존)
- Raw OCR JSON 보존 (`~/.papermeister/ocr_json/`)
- 캐시 기반 재처리: JSON 있으면 RunPod 호출 스킵
- 독립 ProcessWindow (비모달, 로그 누적, 프로그레스 바)
- 메뉴: Process Pending, Retry Failed, Reindex from Cache, Reprocess All
- OCR health 체크 `ensure_workers_ready()` (세션당 1회)
- 소스 트리 root folder 중복 표시 수정
- DB 마이그레이션 (`_migrate()`), .gitignore, .env 설정
