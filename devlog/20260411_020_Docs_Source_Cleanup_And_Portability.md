# 020: docs source 정리 + Windows 이식성 점검 + API 키 rotation

[019](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md) 작성 이후 같은 세션에서 이어진 운영성 작업 세 가지를 분리해서 기록한다. 코드 변경은 없고 DB 상태 변경과 운영 점검이 주된 내용이다.

## 동기

Windows 머신에서 같은 corpus로 작업할 수 있게 `~/.papermeister/` 디렉토리 이식 가능성을 점검하다가:

1. DB 안에 Linux 절대 경로(`/home/jikhanjung/projects/PaperMeister/docs/...`)를 가진 `PaperFile` row가 3개 있었다.
2. 이 3개는 초기 테스트용으로 등록된 `docs` directory source의 잔재였고, 실제 OCR/메타데이터 파이프라인에서는 거의 의미가 없었다 (Zotero 소스가 전부).
3. 이것들을 그대로 둔 채 Windows로 옮기면 경로가 깨지고, 이식성 검증을 흐림.

그래서 "docs source 삭제 → 이식성 재확인 → 압축" 순서로 정리하고, 마지막에 세션 로그에 노출된 API 키를 rotate했다.

## 1. `docs` source 삭제

### 1.1 삭제 대상 집계 (dry-run)

```
Source: #1 name='docs' path='/home/jikhanjung/projects/PaperMeister/docs'
Folders under source: 2
  #1 'docs'        path='/home/jikhanjung/projects/PaperMeister/docs' parent=None
  #2 'ocr_results' path='/home/jikhanjung/projects/PaperMeister/docs/ocr_results' parent=1

Papers:        3
Authors:       0
PaperFiles:    3
Passages:      0
PaperBiblio:   0
passage_fts:   0

Sample PaperFile paths:
  /home/jikhanjung/projects/PaperMeister/docs/2822.pdf
  /home/jikhanjung/projects/PaperMeister/docs/2822_ocr.pdf
  /home/jikhanjung/projects/PaperMeister/docs/2937.pdf
```

Passage/FTS/biblio가 0이라 실질적으로 "등록만 되고 OCR도 안 돌렸던 초기 테스트 3건"이었다.

### 1.2 Cascade 전략 (중요)

`models.py`를 보면:

- `Folder.source = FK(Source, on_delete='CASCADE')` — Source 삭제 시 Folder 삭제 ✓
- `Folder.parent = FK('self', on_delete='CASCADE')` — 중첩 폴더도 루트 삭제 시 제거 ✓
- `Paper.folder = FK(Folder, null=True, on_delete='SET NULL')` — **Folder 삭제만으로 Paper는 안 지워진다 (folder만 NULL로 설정)**

즉 "Source 삭제 → Folder 삭제 → Paper는 folder=NULL로 orphan"이 되어버린다. Paper는 **명시적으로 먼저 삭제**해야 한다.

또한 `passage_fts`는 virtual table이라 FK cascade 대상이 아니다. 수동 `DELETE FROM passage_fts WHERE paper_id IN (...)` 필요.

### 1.3 실행

```python
with db.atomic():
    if paper_ids:
        # 1. passage_fts 먼저 (FK cascade 없음)
        db.execute_sql(
            f"DELETE FROM passage_fts WHERE paper_id IN ({placeholders})",
            paper_ids,
        )
        # 2. Paper 명시 삭제 → Author/PaperFile/Passage/PaperBiblio cascade
        Paper.delete().where(Paper.id.in_(paper_ids)).execute()
    # 3. Source 삭제 → Folder(self-ref CASCADE 포함) cascade
    src.delete_instance()
```

결과:

```
deleted 3 Paper rows (cascades to Author/PaperFile/Passage/PaperBiblio)
deleted Source #1
```

### 1.4 검증

```
Sources remaining: 1
  [zotero] #2 Zotero (6518039)  path='6518039'
Folders total: 543
Papers with folder=NULL: 0
PaperFile rows with /home/... path: 0
```

Library 카운트 변화:

| 항목 | 이전 | 이후 |
|------|-----:|-----:|
| All Files | 11,981 | 11,978 |
| Pending OCR | 7,484 | 7,481 |
| Processed | 4,494 | 4,494 |
| Failed | 3 | 3 |
| Needs Review | 0 | 0 |
| Recently Added | 9,786 | 9,783 |
| Paper total | 9,786 | 9,783 |
| PaperFile total | 11,981 | 11,978 |

**OCR JSON 캐시는 손대지 않았다.** 삭제된 3개 PDF의 해시가 만약 있다면 `~/.papermeister/ocr_json/{hash}.json`이 orphan으로 남지만, 해시 기반 공유 가능성이 있어 무해하고 용량도 미미하므로 그대로 둔다.

## 2. Windows 이식성 점검

### 2.1 디렉토리 내용

| 항목 | 크기 | cross-platform? |
|------|------|-----------------|
| `papermeister.db` | 793 MB | ✅ SQLite 바이너리 포맷 호환 |
| `ocr_json/` (2,385 JSON) | 679 MB | ✅ 해시명, 경로 독립 |
| `preferences.json` | 4 KB | ✅ API 키/ID만 (경로 없음) |
| `zotero_collections.json` 캐시 | 48 KB | ✅ |
| `eval_results_*.json` | 1.2 MB | ✅ (필요하면 제외 가능) |
| **합계** | **약 1.5 GB** | |

`.db-wal` / `.db-shm` 사이드카 **없음** — 이미 체크포인트된 상태라 DB 파일 하나만 복사해도 무결.

### 2.2 DB 내 경로 분포

`docs` source 삭제 후:

```
PaperFile.path 분포 (11,978개):
  relative       11,978  ← Zotero attachment (파일명만)
  /home/...           0
```

- **Zotero source**: `Source.path = '6518039'` (user_id), `Folder.path = ''`, `PaperFile.path = '<파일명>.pdf'`. PDF는 OCR 시점에만 API로 임시 다운로드 → 로컬 경로 무관.
- `preferences.json`: API 키/ID만, 경로 의존성 0.
- `os.path.expanduser('~')`는 Windows에서 `C:\Users\<유저>`로 풀림 → `database.py::DB_PATH` 자동 호환.

### 2.3 Windows에서 작동 여부

**✅ 그대로 작동**: Paper 브라우징 (11,978), Zotero 트리, OCR 미리보기, FTS5 검색, `biblio_reflect`, Zotero sync, RunPod OCR, `python -m desktop`

**❌ 깨짐**: 없음 (docs source 제거 후)

**가정사항**:
- Python 3.12 + PyQt6>=6.7 (현재 requirements.txt)가 Windows wheel 제공 — 확인됨
- Inter 폰트는 미설치 시 Segoe UI로 자동 fallback (QSS `FONT['family.ui']`가 콤마 구분 family list)

## 3. 압축 아티팩트

```bash
cd ~ && tar czf papermeister.tar.gz .papermeister/
```

결과:

- 파일: `/home/jikhanjung/papermeister.tar.gz`
- 크기: **334 MB** (원본 약 1.5 GB → 약 22%)
- 엔트리: 2,397개 (DB 1 + OCR JSON 2,385 + preferences/eval/cache)
- SHA256: `a5f1eeef2ce59133149fae14adbd28046de9274caa954fb9e9b9a146cd00080d`

최상위가 `.papermeister/` 하나라 Windows에서 `C:\Users\<유저>\` 에 풀면 바로 `C:\Users\<유저>\.papermeister\` 구조가 된다.

**주의**: tar.gz 파일 자체는 git 추적 대상이 아니며 배포용 일회성 아티팩트다. 다른 세션/머신이 보고 "이게 뭐지?" 할 수 있어서 여기 기록만 해둔다. 필요 없으면 `rm ~/papermeister.tar.gz`.

## 4. API 키 rotation

### 4.1 배경

이식성 점검 과정에서 `cat preferences.json` 명령으로 preferences 내용을 세션 대화에 노출시켰다. 노출된 값:

- RunPod API key
- RunPod endpoint ID (비밀 아님, URL의 일부)
- Zotero API key
- Zotero user ID (비밀 아님, 프로필 URL에 공개)

즉 비밀로 관리해야 할 값은 **RunPod API key + Zotero API key** 두 개.

### 4.2 노출의 실제 위험

- Anthropic API 트래픽은 기본적으로 모델 학습에 쓰이지 않지만 abuse/safety 목적의 retention이 일정 기간 있음 (대체로 30일 내외).
- Claude Code는 로컬에 세션 JSONL을 `~/.claude/projects/.../` 하에 저장 — 세션 종료 후에도 자동 삭제되지 않음.
- 노출 채널은 실무적으로 "로컬 디스크 + 서버 retention"이 주. 외부 유출 가능성은 낮지만 0은 아님.

피해 가능성 순위:

1. **RunPod** — 유출 시 공격자가 GPU 호출로 청구서를 태울 수 있음 (금전 피해).
2. **Zotero** — 라이브러리 read/write 권한이면 복구 불가능한 데이터 삭제/수정 가능 (학술 자산).

### 4.3 조치

두 키 모두 revoke + 재발급 + `preferences.json` 업데이트 완료.

- RunPod: 콘솔 → API Keys → 기존 키 delete → 새 키 생성 → `runpod_api_key` 교체
- Zotero: https://www.zotero.org/settings/keys → 기존 키 revoke → 새 키 생성 (permissions 동일) → `zotero_api_key` 교체

### 4.4 예방책 (이후 세션용)

- AI 어시스턴트가 보는 파일에 평문 시크릿을 두지 않기가 근본 해결책이지만, 운영상 preferences.json에 키가 들어가는 구조 자체를 당장 바꾸기는 어려움.
- 대신 **대화에서 `cat preferences.json`을 직접 실행하는 경로를 피하기**가 실용적 중간점. 필요하면:
  - 특정 key 존재 여부만 확인 (`python -c "from papermeister.preferences import get_pref; print(bool(get_pref('runpod_api_key')))"`)
  - 또는 일부 마스킹 후 출력
- `preferences.json.jikhan` / `preferences.json.psok` 백업 파일도 옛 키를 담고 있을 수 있으므로, 개인 프로파일 전환 용도라면 키 부분만 제거하거나 파일 자체를 제거하는 게 안전.

## 5. 다음 세션 인계

### 5.1 DB 상태 변화

- docs source 전부 제거 (Source/Folder/Paper/PaperFile). Zotero source만 남음.
- 총 Paper 9,783 / PaperFile 11,978.
- `biblio_reflect --dry-run`의 "scanned=97" 계산은 PaperBiblio를 가진 Paper 기준이라 이 정리와 무관 (동일하게 유지).

### 5.2 이식 아티팩트

- `~/papermeister.tar.gz` (334 MB) — Windows 머신 이식 대기. 필요 없으면 삭제 가능.

### 5.3 크리덴셜

- RunPod/Zotero 키 모두 새 값으로 교체됨. 이전 세션 로그에 등장하는 값은 전부 무효.

## 배운 점

### cascade 설계는 "겉으로 보이는 관계"와 다를 수 있다

`Paper.folder`가 `on_delete='SET NULL'`로 잡혀 있어 Folder 삭제로 Paper가 안 지워지는 건 예상 밖이었다. 직관적으로는 "Source 하나 지우면 다 따라간다"를 기대하지만, 실제로는 `SET NULL` → orphan이 되는 구조. 삭제 스크립트는 **삭제 순서를 의존 그래프 역순으로 명시**하는 편이 안전하다.

이후 비슷한 작업 시 체크리스트:

1. `on_delete`가 CASCADE인지 SET NULL인지 모델을 읽고 확인
2. FTS 같은 virtual table은 FK 없음 — 수동 삭제 필요
3. 트랜잭션으로 감싸고 before/after 카운트 찍기
4. 한 번에 통합 commit보다 dry-run 먼저

### 이식성은 "경로 의존성이 어디에 남는가"의 문제

이 앱이 Windows에서 거의 그대로 작동한 이유는 **데이터 저장소가 처음부터 네트워크 API 기반**이었기 때문이다 (Zotero, RunPod). 로컬 파일 의존성은 OCR JSON 캐시(해시명)와 preferences(경로 없음)뿐. 처음 설계 시 "로컬 파일 경로를 DB에 넣지 않는다" 규칙을 지켰더라면 3건의 잔재도 없었을 것. 향후 directory source를 본격 지원할 때는 **path 필드를 source root 상대 경로**로 저장하는 편이 이식성 관점에서 안전하다.

### 시크릿 위생은 "대화 표면"에서 결정된다

preferences.json에 키가 있는 것 자체는 일반적이고, 그게 위험해지는 건 그 파일이 AI 대화나 공유 로그에 dump되는 순간이다. 근본 해결(환경변수, vault)은 프로젝트 규모에 비해 과할 수 있지만, "대화에서 시크릿 파일을 직접 cat하지 않는다"는 실행 규칙은 비용 없이 지킬 수 있다.

## 관련 문서

- [019 새 데스크탑 앱 스캐폴드 + P08 러너](./20260411_019_New_Desktop_App_Scaffold_And_P08_Runner.md) — 이 세션의 본편
- [P07 구현 계획](./20260410_P07_Desktop_Software_Implementation_Plan.md) — DB 재구성 경로 점검은 여전히 Phase 1 잔여 숙제로 남음
