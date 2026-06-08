# 048 — `failed` PDF 404 진단 + 로컬 Zotero storage 복구

> 세션 43 (2026-06-08), [047](./20260608_047_OCR_JSON_Rename_Resume_LastRead_Fix.md) 후속.

## 발단

세션 38에서 "OCR 잔존 10편 중 HTTP 404(Zotero web storage에 file 없음) 7편"이라고 적어둔 것을
사용자가 다시 떠올림 — **그 attachment key로 로컬 Zotero data 디렉토리
(`C:\Users\Jikhan Jung\Zotero\storage\<KEY>\`)를 뒤지면 서버 업로드가 안 된 PDF를
찾을 수 있지 않겠냐**는 가설. 업로드 과정에서 문제가 있었을 것이라는 추정.

## 진단 (read-only)

`failed` 상태 non-json PDF 13편을 추려 각 `zotero_key`로 로컬 storage + 로컬 Zotero DB
(`zotero.sqlite`의 `itemAttachments.linkMode/storageHash`)를 대조:

| 분류 | 수 | 내용 |
|------|----|------|
| **로컬 PDF 실재** | 2 | `WIZC6QDZ`(Park 2023 Generative Agents), `3MK6XEI2`(Balashova1960). imported_file + storageHash + 로컬 파일 O |
| 로컬에도 없음 (imported_file) | 5 | Segment Anything(hash는 있었으나 파일 소실) + Focal Loss/DETR/Triplet/ResNet(storageHash 없음, 빈 폴더 = 애초에 파일 받은 적 없음) |
| 파일 아님 (linked_url) | 6 | URL 링크 첨부. path/contentType 없음 → OCR할 PDF 자체가 없음. failed가 부정확한 분류 |

→ 가설대로 "로컬에 있는데 OCR 안 된" PDF 2편 확인. 두 파일 `%PDF-1.5`/`%PDF-1.6` 유효.

## 도구: `scripts/upload_missing_zotero_files.py`

대상을 하드코딩하지 않고 **"failed PDF + 로컬 `storage/<key>/`에 `.pdf` 존재"로 자동 탐지**,
`ZoteroClient.replace_attachment_file(key, local_path)`로 업로드(attachment key 보존),
성공 시 `status='failed' → 'pending'` 리셋 + `failure_reason` clear. dry-run 기본.

### 시행착오: PDF만 좁히기

첫 dry-run이 19~26편을 잡음 — `_local_file_for`의 `(pdfs or entries)[0]` 폴백이 **비-PDF
첨부까지 끌어옴**. storage에는 보충자료(`.txt`/`.xls`/`.zip`/`.pps`/`.doc`/`.blend`),
`.djvu` 책 6권(Lamarck/Sneath/Sokal/Wiley 등), Ameghiniana 저널 `.doc` 7편 등이 섞여 있었음.
이들은 "OCR 실패"가 아니라 "OCR 대상 아님"이라 업로드+pending 리셋하면 무한 재시도 루프.
→ `.pdf`만 대상(`found`)으로, 비-PDF 로컬 파일은 `non_pdf_local`로 분리 보고 + 미터치.

## 결과 — 가설 정정

`--execute`: **`uploaded: 0`, `unchanged: 2`**. pyzotero `_get_auth`가 서버에 md5를 물으니
**서버가 `exists:1`로 응답** = 두 파일은 이미 web storage에 있음. 즉 원래 가설("미업로드")은
틀렸고, **원래 `failed`가 stale 상태**였던 것. 업로드는 no-op, 실질 복구는 **status 리셋으로
재시도를 다시 연 것**. 두 논문 Process(OCR) → 정상 완료 (사용자 확인).

7532(Balashova1960)는 standalone(title=파일명, 저자/연도 없음)이라 OCR 후 auto-promote로
Zotero parent item 생성되는 흐름(세션 36).

## 교훈 / 남은 것

- `failed` + hash='' 라고 다 "다운로드 404"가 아님 — stale failed가 섞여 있음. 단순 status
  리셋 재시도로 풀리는 케이스 존재. (세션 35 폴더 Process가 failed 재시도를 포함하므로 폴더
  단위로는 이미 자동 해소 경로가 있음 — 단건으로 방치된 게 남았던 것)
- **비-PDF failed 첨부 24편**은 OCR 파이프라인 구조상 영구 failed: 보충자료/`.djvu` 책/`.doc`
  저널. status를 `failed` 말고 별도(`not_applicable` 등)로 분류하면 목록 노이즈 제거 가능 → TODO.
- **linked_url 6편**도 파일이 아니라 영구 failed → 같은 TODO.
- read-only 검증 주의: `immutable=1`은 **WAL을 무시**해서 desktop이 방금 쓴(checkpoint 전) OCR
  결과가 안 보임. 라이브 앱이 쓰는 중인 DB는 stale snapshot일 수 있음.
