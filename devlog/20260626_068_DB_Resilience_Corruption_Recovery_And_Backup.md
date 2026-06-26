# 068 — DB 복원력: 인덱스 손상 복구 + 자동 오프사이트 백업

> 세션 (2026-06-26). 대량 references 재추출 중 발생한 **DB 손상**을 무손실 복구하고,
> 재발 대비로 **3시간→하루 1회 자동 gzip 백업(서버 scp)** 을 구축. P13(FTS 변환)과
> 같은 세션의 운영/복원력 작업 정리.

## 1. 인덱스 손상 — `database disk image is malformed`

### 증상
`reset_references.py --execute`의 `DELETE FROM reference …` 실행 중 발생. SELECT(미리보기)는
정상이었는데 DELETE 쓰기에서 터짐.

### 진단 (무손실)
손상 DB를 WSL 로컬로 복사(drvfs 순차읽기 ~28s) 후 `PRAGMA integrity_check`:
- 에러 **1,291건 전부** `row N missing from index reference_resolved_work_id` — **인덱스 1개만**
  깨짐. 테이블·FTS·다른 인덱스는 정상. **데이터 손실 0**(테이블 B-tree는 멀쩡, 보조 인덱스만
  desync).

### 복구
```sql
REINDEX reference_resolved_work_id;   -- 테이블에서 인덱스 재구축, 즉시
PRAGMA integrity_check;               -- ok
```
복구 검증: 실패했던 DELETE를 트랜잭션 안에서 재현→ROLLBACK으로 476행 정상 삭제 확인.
라이브 적용은 Windows 네이티브에서 in-place 한 줄:
```
python -c "import sqlite3,os; c=sqlite3.connect(os.path.expanduser('~/.papermeister/papermeister.db')); c.execute('REINDEX reference_resolved_work_id'); c.commit()"
```

### 원인·예방
- 유력 원인: **WSL `/mnt/c`로 라이브 DB를 Windows 쓰기와 동시에 접근**(drvfs는 SQLite 잠금
  미보장) + 중단된 추출. → read-only여도 동시 쓰기와 겹치면 인덱스 desync 가능.
- 예방: 대량 배치 중 WSL에서 라이브 DB 조회 금지, 데스크톱/배치 동시 실행 금지, **작업 전 백업**.
  (메모리 [[migration-scripts-run-on-windows]]에 사례·복구법 반영.)
- 네이티브 Windows는 WAL이라 reader+writer 동시 안전 — 손상은 drvfs 동시접근 한정.

## 2. 자동 오프사이트 백업

### `scripts/_db_snapshot.py`
SQLite **online-backup API**(`Connection.backup`)로 일관성 스냅샷 → gzip. 앱이 쓰는 중에도
안전(변경된 페이지 자동 재복사) — raw 파일 copy의 torn/stale WAL 사본 문제 회피. stdlib만 사용.

### `scripts/backup-papermeister.ps1`
스냅샷+gzip → `scp`(타임스탬프 파일명 누적) → 서버에서 최신 `$Keep`개만 보존(`ls -t | tail`).
- **gotcha**: Task Scheduler는 conda env PATH를 안 물려받아 `python` 미해석 → 스냅샷 실패 →
  scp가 "no such file or directory". **conda python 절대경로 호출**(+PATH 폴백)과 단계별
  `$LASTEXITCODE` throw로 해결.
- 수동 실측: 2.4GB DB → **880MB gz**, scp 103MB/s.

### 스케줄 (Task Scheduler)
```
schtasks /Create /TN "PaperMeister DB Backup" /SC DAILY /ST 04:00 /F /TR "powershell …\backup-papermeister.ps1"
```
- 처음 `/SC HOURLY /MO 3`로 했다가 **하루 1회(`/SC DAILY /ST 04:00`)** 로 변경.
- 검증: `schtasks /Run`(스케줄과 동일 컨텍스트)으로 환경 확인 → 2분짜리 `/SC ONCE` 임시
  작업으로 타이머 발화 확인 → `Get-ScheduledTaskInfo`의 `LastTaskResult=0`·`NextRunTime`.
- 보존: 하루 1회 × `$Keep=24` = 약 24일치(~24GB). 조정은 스크립트 `$Keep`.
- 복원: `gunzip -c papermeister-YYYYmmdd-HHMMSS.db.gz > papermeister.db`.

## 비고
- 스케줄(트리거)은 Task Scheduler에만 있고 코드와 무관 — repo에는 스크립트만, 주기는 OS가 관리.
- 로그오프 상태 실행을 원하면 작업을 "로그온 여부 무관"으로 + batch 로그온 시 `~/.ssh` 키 확인 필요.
