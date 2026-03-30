# HANDOFF.md

세션 간 프로젝트 상태를 인계하기 위한 파일입니다.
새 세션을 시작할 때 이 파일을 먼저 읽고 현재 상황을 파악하세요.
작업 종료 시 이 파일을 최신 상태로 업데이트하세요.

---

## 현재 단계

**Phase: MVP 구현 완료 — OCR 실제 연동 테스트 단계**

GUI 실행 확인됨. .env 설정 완료. RunPod OCR 실 연동 테스트 필요.

---

## 다음 할 일

- [ ] RunPod OCR 실제 연동 테스트 (Import Folder → OCR 처리 → 검색 확인)
- [ ] Zotero 연동 모듈 구현 (Source type='zotero')
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
| 메타데이터 | PyMuPDF (fitz) | PDF 내장 메타데이터만 |
| 검색 | FTS5 BM25 | title×10, authors×5, text×1 |
| Import 흐름 | Scan → Process 분리 | ScanWorker(빠름) → ProcessWorker(OCR) |
| 중복 방지 | SHA256 파일 해시 | |

---

## 미결 사항

- Zotero API 연동 방식 미결정
- 검색 결과 매칭 패시지 하이라이트 표시 방식

---

## 최근 세션 요약

**2026-03-30**
- PRD → MVP 전체 구현 (0 → 1)
- 기술 스택: PyQt6 + SQLite/FTS5 + Peewee 4.x + PyMuPDF + RunPod OCR
- 모듈: models, database, ingestion, ocr, text_extract, search, ui/main_window
- 3-pane UI (소스트리 | 논문목록 | 상세뷰), ScanWorker/ProcessWorker 분리
- 프로그레스 바, Retry Failed (Ctrl+R), OCR health 체크 추가
- DB 마이그레이션 (`_migrate()`), .gitignore, .env 설정
