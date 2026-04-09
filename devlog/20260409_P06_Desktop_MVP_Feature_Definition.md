# P06: 데스크탑 애플리케이션 MVP 기능 정의

## 배경

세션 1~6을 거치며 PDF → OCR → 서지 추출 → Zotero 연동 파이프라인이 검증되었다. 이 경험을 바탕으로 데스크탑 앱의 MVP 기능 범위를 확정한다.

## 핵심 원칙

- **"Store first, understand later"**: OCR 결과(JSON)가 source of truth. 서지정보는 파생 레이어.
- **DB는 재구성 가능**: Zotero든 파일시스템이든, 처리가 잘 되어 있으면 DB 없어도 다시 만들 수 있어야 함.
- **비파괴**: 원본 PDF를 변경하지 않음. 서지 추출은 별도 보관 후 사용자 검토를 거쳐 반영.

---

## MVP 기능

### 1. Data Source 관리

두 종류의 data source를 지원:

**Zotero**
- pyzotero로 연동 (user_id + api_key, read+write)
- 컬렉션 트리 동기화 (시작 시 자동, 수동 새로고침)
- 컬렉션 클릭 → 아이템 fetch (parent + 모든 attachment 매칭)
- PDF는 로컬 저장 안 함 (임시 다운로드 → 처리 → 삭제)
- NAS/로컬 storage 경로 지정 시 Zotero 다운로드 대신 로컬 PDF 사용 가능 (옵션)

**Local directory**
- 폴더 구조 스캔 → Source/Folder/Paper/PaperFile 생성
- hash 기반 dedup (SHA256)
- PDF 파일은 원래 위치에 유지, 경로만 DB에 저장

### 2. OCR 처리 (PDF → JSON)

- **엔진**: RunPod serverless (Chandra2-vllm). endpoint URL + API key 설정.
- **입력**: PDF 파일
- **출력**: `~/.papermeister/ocr_json/{sha256_hash}.json`
  - hash 기반 파일명 → data source 무관 공통
  - 같은 PDF는 같은 hash → 중복 OCR 방지
- **병렬 처리**: RunPod idle worker 수 확인 → ThreadPoolExecutor로 동시 제출
- **상태 관리**: PaperFile.status = pending → processed / failed
- **캐시**: JSON 파일이 존재하면 OCR 스킵, DB만 갱신
- **Zotero 추가 동작**: parent item이 있는 PDF → JSON을 sibling attachment로 업로드 (opt-in)

### 3. 서지정보 추출 (JSON → 메타데이터)

OCR JSON의 첫 1~3페이지에서 LLM(claude -p 또는 Anthropic SDK)으로 추출.

**추출 스키마**:
```
title, authors[], year, journal, doi, abstract,
doc_type (article|book|chapter|thesis|report|journal_issue|unknown),
language, confidence (high|medium|low), needs_visual_review, notes
```

**텍스트 추출** (1차, 기본):
- 모델: Haiku (비용 최적, 평가에서 Sonnet/Opus와 동률)
- OCR JSON의 markdown → prompt → JSON 응답
- PaperBiblio 테이블에 저장 (source='llm-haiku')

**Vision pass** (2차, 필요 시):
- 트리거: needs_visual_review=true, confidence!=high, 또는 수동 요청
- PyMuPDF로 첫/마지막 페이지 PNG 렌더 → Claude vision
- 모델: Sonnet (CJK vision은 Haiku 부정확)
- 같은 PaperBiblio에 source='llm-sonnet-vision'으로 별도 행

**적용 정책 (Zotero)**:
| 상태 | 동작 |
|------|------|
| parent item 있음 + 메타데이터 충분 | **보수적 업데이트**: 빈 필드만 보강 (DOI, abstract 등) |
| parent item 있음 + 메타데이터 부족 | LLM 결과로 보강, 사용자 검토 후 |
| parent item 없음 (standalone PDF) | **새 parent 생성** + PDF/JSON을 children으로 이동 (nothing to lose) |
| journal issue 표지 | doc_type='journal_issue' → document 타입으로 생성/수정 |

**적용 정책 (Local directory)**:
- 서지정보 + JSON 매칭 모두 로컬 DB로 처리
- Paper 테이블에 반영 (confidence=high 자동, 나머지 수동 검토)

### 4. 로컬 DB

`~/.papermeister/papermeister.db` (SQLite + FTS5)

**테이블 구조**:
```
Source → Folder → Paper → PaperFile (PDF/JSON, hash, status, zotero_key)
                       → Author
                       → Passage → passage_fts (FTS5)
                       → PaperBiblio (LLM 추출, source 필드로 버전 관리)
```

**재구성 가능 원칙**:
- Zotero source: API에서 컬렉션/아이템 재fetch + OCR JSON 캐시로 Passage 재생성 → DB 완전 복구
- Directory source: 폴더 재스캔 + hash 매칭으로 OCR JSON 캐시 재연결 → DB 완전 복구
- 자동 마이그레이션: `database.py._migrate()`가 새 컬럼/인덱스 변경 적용

### 5. 설정 (Preferences)

`~/.papermeister/preferences.json`

| 설정 | 용도 |
|------|------|
| `runpod_endpoint` | RunPod OCR serverless endpoint URL |
| `runpod_api_key` | RunPod API 키 |
| `zotero_user_id` | Zotero user ID |
| `zotero_api_key` | Zotero API key (read+write) |
| `llm_api_key` | LLM API 키 (Anthropic) — claude -p 대신 SDK 사용 시 |
| `llm_model_text` | 텍스트 추출 모델 (기본: claude-haiku-4-5) |
| `llm_model_vision` | Vision 추출 모델 (기본: claude-sonnet-4-6) |
| `zotero_upload_ocr_json` | OCR 후 JSON Zotero 업로드 여부 (기본: false) |
| `zotero_storage_path` | 로컬 Zotero storage 경로 (옵션, 설정 시 API 다운로드 대신 사용) |

GUI에서 Preferences 다이얼로그로 관리. `.env` 사용하지 않음.

---

## MVP 이후 (Phase 2+)

MVP에는 포함하지 않지만 기록:

- **검색 UI**: FTS5 BM25 full-text search + 결과 목록 + 매칭 passage 하이라이트
- **PDF 뷰어**: 검색 결과에서 해당 페이지로 이동, passage 위치 하이라이트
- **서지 검토 UI**: PaperBiblio 결과를 사용자에게 보여주고 승인/수정/거부
- **Hybrid search**: BM25 + embedding vector search
- **LLM query interpretation**: 자연어 질의 → 검색 쿼리 변환
- **Entity extraction**: taxon, locality, stratigraphic unit 등 도메인 특화 추출
- **Relation extraction**: 논문 간 인용 관계, 동의어 관계

---

## 기술 스택

| 구성 | 기술 | 비고 |
|------|------|------|
| GUI | PyQt6 | 3-pane: source tree / paper list / detail |
| DB | SQLite + FTS5 | Peewee ORM |
| PDF 처리 | PyMuPDF (fitz) | 메타데이터 + 페이지 렌더 |
| OCR | RunPod (Chandra2-vllm) | serverless, 병렬 |
| LLM | claude -p 또는 Anthropic SDK | Haiku(텍스트) + Sonnet(vision) |
| Zotero | pyzotero | read+write API |
| CLI | cli.py (argparse) | PyQt6 없이 독립 실행 가능 |

---

## 화면 구성 (MVP)

```
┌─────────────────────────────────────────────────────────┐
│ Menu: File | Settings | Help                            │
├──────────┬──────────────────┬───────────────────────────┤
│ Sources  │ Papers           │ Detail                    │
│          │                  │                           │
│ ▸ Zotero │ [status] Title   │ Title                     │
│   ├ Col1 │ [status] Title   │ Authors, Year             │
│   ├ Col2 │ [status] Title   │ Journal, DOI              │
│   └ Col3 │ ...              │                           │
│ ▸ ~/docs │                  │ [OCR text / passages]     │
│   ├ sub1 │                  │                           │
│   └ sub2 │                  │                           │
├──────────┴──────────────────┴───────────────────────────┤
│ Status: 1,234 processed | 456 pending | 3 failed        │
└─────────────────────────────────────────────────────────┘
```

- 왼쪽: Source/Folder 트리
- 가운데: 선택 폴더의 Paper 목록 (status 아이콘: pending/processed/failed/no PDF)
- 오른쪽: 선택 Paper 상세 (메타데이터 + OCR 텍스트)
- 하단: 전체 상태바

---

## 처리 워크플로 (사용자 관점)

1. **Source 추가**: Zotero 자격증명 입력 또는 로컬 디렉토리 선택
2. **스캔**: 컬렉션/폴더 구조 + PaperFile 생성 (빠름)
3. **OCR 처리**: pending 파일 선택 → Process 시작 (독립 윈도우, 비모달)
   - 진행률 바 + 로그
   - 캐시 있으면 자동 스킵
   - Zotero: JSON sibling 자동 업로드 (opt-in)
4. **서지 추출**: processed 파일 → LLM 추출 (백그라운드)
   - 텍스트 1차 → vision 2차 (필요 시)
   - standalone → 자동 promote (high confidence)
5. **검토** (Phase 2): 추출 결과 사용자 확인 → Paper 반영
6. **검색** (Phase 2): full-text search
