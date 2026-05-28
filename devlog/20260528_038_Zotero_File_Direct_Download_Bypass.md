# 20260528_038 — pyzotero `Zotero.file()` 우회: direct GET으로 attachment 다운로드

## 컨텍스트

세션 36에서 [`devlog/20260526_036`](20260526_036_OCR_Log_File_Zotero_Error_Wrap_DB_Stats.md) 작업 중 `_resolve_filepath`의 Zotero 다운로드 경로에 에러 wrap을 추가했지만, **밑단의 진짜 버그는 그대로**였다. pyzotero `Zotero.file()` 메서드는 응답의 `Content-Type` 헤더를 sniff해서 반환 타입을 결정하는데:

- `application/pdf` → `bytes`
- `application/json` → `dict` (자체적으로 `json.loads`)
- 매치 안 됨 → JSON fallback 시도

문제는 **`imported_url` linkMode 인 attachment가 S3에서 서빙될 때 Content-Type이 비어있다**는 점. pyzotero는 이걸 JSON으로 간주하고 `json.loads(pdf_bytes)`를 호출 → `JSONDecodeError`. 멀쩡한 PDF인데도 다운로드 자체가 실패. 세션 36의 에러 wrap이 메시지를 친절하게 다듬어주긴 했지만 다운로드는 여전히 안 됐다.

또 한 가지 케이스: attachment 레코드는 존재하지만 실제 파일은 Zotero web storage에 업로드된 적이 없는 상태(`imported_file` linkMode + sync 안 됨). 서버는 HTTP 404로 응답하는데 pyzotero를 통과하면 generic exception이 되어서 사용자가 "네트워크 문제인가 권한 문제인가 파일 부재인가" 구분 불가.

## 변경 사항

### 1. `papermeister/zotero_client.py::download_file_content` 신규

raw `requests.get`으로 Zotero API의 `/items/{key}/file` 엔드포인트를 직접 호출. Content-Type 무시, `.content`를 그대로 반환.

```python
def download_file_content(self, attachment_key):
    """Download raw file bytes for an attachment, bypassing pyzotero's
    Content-Type sniffing.
    ...
    Returns: bytes.
    Raises: requests.HTTPError — notably 404 when the attachment record
        exists but its file was never uploaded to Zotero web storage
        (linkMode 'imported_file' with no synced file).
    """
    import requests
    url = (
        f'{self._zot.endpoint}/{self._zot.library_type}/'
        f'{self._zot.library_id}/items/{attachment_key.upper()}/file'
    )
    resp = requests.get(
        url,
        headers={
            'Zotero-API-Key': self.api_key,
            'Zotero-API-Version': '3',
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.content
```

설계 메모:
- `self._zot.endpoint` / `library_type` / `library_id`를 재사용해서 base URL 구성 — 인증/베이스 결정 로직 중복 안 함.
- `attachment_key.upper()` — Zotero 키는 대소문자 구분 없으나 endpoint가 대문자 키를 정식으로 받음.
- `timeout=180` — 큰 PDF S3 다운로드 고려. pyzotero 기본보다 보수적.
- `raise_for_status()`로 HTTPError를 그대로 노출 → 호출자가 status code 보고 404/그 외를 구분 가능.

`ZoteroClient.download_attachment` (이미 존재)도 `self._zot.file()` → `self.download_file_content()`로 교체. 같은 path를 따라가는 모든 attachment fetch 통일.

### 2. `papermeister/text_extract.py::_resolve_filepath` — 404 친화 메시지

Zotero-sourced PaperFile 경로의 다운로드 단계:

```python
import requests
client = ZoteroClient(user_id, api_key)
try:
    content = client.download_file_content(paper_file.zotero_key)
except requests.HTTPError as e:
    status = e.response.status_code if e.response is not None else '?'
    if status == 404:
        raise RuntimeError(
            f'Zotero has no file for key={paper_file.zotero_key} '
            f'path={paper_file.path!r} (HTTP 404) — the attachment record '
            f'exists but its file is missing from Zotero web storage'
        ) from e
    raise RuntimeError(
        f'Zotero file download failed for key={paper_file.zotero_key} '
        f'path={paper_file.path!r}: HTTP {status}'
    ) from e
except Exception as e:
    # (기존 일반 wrap 유지)
    ...
```

세션 36의 일반 wrap은 그대로 두고, **HTTP 에러만 분리해서 status code를 메시지에 박음**. 404는 명시적으로 "Zotero에 파일이 없음 — sync 안 됐거나 storage에서 제거됨" 라고 표기 → 사용자가 Zotero 클라이언트에서 직접 확인할 수 있는 액션 아이템이 됨.

### 3. `_try_fetch_sibling_json` — 정규화 로직 제거

`{hash}.json` sibling attachment fetch 경로도 같은 우회를 거치니, 기존에 있던 `dict`/`bytes`/`str` 분기 처리가 불필요해짐:

기존:
```python
content = client._zot.file(sibling.zotero_key)
# pyzotero sniffs content-type: returns a dict for JSON attachments,
# bytes for binary, str for plain text. Normalise.
if isinstance(content, dict):
    raw_result = content
elif isinstance(content, bytes):
    raw_result = json.loads(content.decode('utf-8'))
else:
    raw_result = json.loads(content)
```

→ 변경:
```python
content = client.download_file_content(sibling.zotero_key)
raw_result = json.loads(content.decode('utf-8'))
```

direct GET이 항상 `bytes`만 반환하니 분기 단일화. 사이드 효과로 "pyzotero가 마침 JSON으로 정확히 인식한 케이스"와 "PDF인데 잘못 인식한 케이스"의 일관성도 사라짐 — 모든 sibling JSON이 동일하게 bytes → utf-8 decode → json.loads 경로.

## 영향 범위

- Zotero PDF/JSON 다운로드 실패율이 떨어짐. 특히 외부에서 (Zotero web UI에서) drag-and-drop으로 추가된 attachment(`imported_url` linkMode + 빈 Content-Type)가 OCR 파이프라인에 들어올 수 있게 됨.
- 404 메시지가 명확해져서 "Zotero web storage에 파일이 없는" 케이스를 한 번에 식별 가능. 세션 36 잔여 작업의 48편 extracted 재시도 / 1960s 226편 Process Folder 운영 중 발생할 가능성 높은 케이스.
- pyzotero 의존성은 유지 — items/collections fetch 등 메타데이터 API는 계속 그 인터페이스 사용. 우회는 **파일 다운로드 한 경로**에만 적용.

## 미해결 / 다음

- pyzotero가 `Content-Type` sniffing을 끄거나 raw bytes 모드를 노출하는 옵션을 추가하면 우회 코드는 제거 가능. 현재는 upstream에 우회를 강제하는 케이스라 우리 쪽에서 wrap.
- 큰 attachment 다운로드 도중 timeout 180s를 넘기는 케이스가 발견되면 chunked download + resume으로 확장 필요. 지금 운영 규모에서는 단순 GET으로 충분.
- `download_attachment`은 디스크 파일 경로를 반환하는 헬퍼인데 임시 디렉토리 cleanup 정책이 없음 (`~/.papermeister/tmp/{key}.pdf`). 누적되는 cache라 별도 LRU/aged-out 정리 필요할 수 있음 — 운영 중 디스크 사용량 보고 판단.
