# Zotero DB 재동기화 + NAS Storage Hash 매칭

## 배경

이전 세션에서 만들어진 DB에 문제가 있었음:
- Paper.zotero_key가 7,215편에서 비어있음 (이전 코드가 backfill 못 한 레거시)
- Standalone PDF는 PaperFile에 아예 안 들어가 있었음

깨끗하게 처음부터 재동기화하기로 결정.

## 작업 내용

### 1. Zotero DB 초기화 + 재동기화 (`scripts/resync_zotero.py`)

1. 기존 Zotero source의 모든 데이터 삭제 (Passage → Author → PaperFile → Paper → Folder)
2. library_version 리셋 → 전체 컬렉션 재동기화 (542개)
3. 모든 컬렉션 아이템 fetch → Paper + PaperFile 생성

결과:
- 542 folders, 9,783 papers, 9,897 paperfiles
- 이전 대비 +1,500 papers, +2,510 paperfiles (standalone PDF 포함)

### 2. NAS Storage Hash 매칭 (`scripts/update_hashes.py`)

`/nas/JikhanJung/1. Large Data/storage/`에 Zotero storage를 복사해 둔 상태.
디렉토리명 = Zotero attachment key, 안에 PDF 1개.

스크립트 동작:
1. PaperFile.zotero_key로 NAS storage에서 PDF 찾기
2. SHA256 hash 계산 → PaperFile.hash 저장
3. `~/.papermeister/ocr_json/{hash}.json` 존재하면 status='processed'

결과:
- 9,500개 PaperFile hash 매칭 성공 (397개 PDF 없음)
- 1,116개 OCR 캐시 → processed로 복원

### 교훈

- Python subprocess의 stdout 버퍼링: background 실행 시 출력이 안 보이는 문제. `flush=True` 또는 `python -u` 필수.
- NAS I/O가 느려서 hash 계산에 시간 소요. progress 로그의 간격을 1000건으로 잡아 부담 줄임.
