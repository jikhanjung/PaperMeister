# 093 — 기관 네트워크가 TLS를 가로챌 때: verify=False에서 OS 신뢰 저장소로

2026-08-28. Zotero 동기화가 상태바에 이렇게 찍혔다.

```
Sync failed: ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
self-signed certificate in certificate chain (_ssl.c:1010)
```

## 진단 — 추측하지 않고 인증서를 꺼내 봤다

WSL에서 Windows 파이썬을 직접 호출해(`/mnt/c/.../envs/PaperMeister/python.exe`)
`api.zotero.org`의 인증서를 검증 없이 받아 발급자를 찍었다.

```
subject: CN=zotero.org
issuer : CN=KOPRI SSL,O=KOPRI,C=KR
```

Zotero가 아니라 **기관 네트워크가 중간에서 다시 서명하고 있다.** 그 CA는 Windows 루트 저장소에
있고(`Cert:\LocalMachine\Root`에서 `DE58 9347…`, 만료 2039), 그래서 브라우저도 Zotero 앱도
아무 불편이 없다. 실패하는 건 파이썬뿐이다 — httpx/requests는 OS 저장소가 아니라 **certifi 번들**로
검증하는데, 거기엔 KOPRI CA가 있을 리 없다.

## 왜 지금 터졌나 — 옛 우회책이 조용히 죽어 있었다

`desktop/app.py` 맨 위에 이미 이 문제를 겨냥한 코드가 있었다.

```python
# pyzotero calls requests.get/post directly (no Session), so we patch the
# default verify parameter at the module level.
requests.api.request = _no_verify_request   # kwargs.setdefault('verify', False)
```

주석이 스스로 전제를 밝히고 있다: **"pyzotero가 requests를 쓴다"**. 그런데 0.1.6에서
`pyzotero ~=1.5.0 → ~=1.13.2`로 올리면서(`ea8cf2b`) pyzotero의 HTTP 백엔드가 **requests에서
httpx로** 바뀌었다. 패치가 앉아 있던 자리를 Zotero 호출이 더 이상 지나가지 않는다.
그래서 예외 타입도 `requests.exceptions.SSLError`가 아니라 `httpx.ConnectError`로 나왔다 —
에러 메시지 자체가 이미 백엔드가 바뀌었다고 말하고 있었던 셈이다.

같은 블록이 스크립트 10개에 복사돼 있었고, 전부 같은 이유로 죽어 있었다.

`tests/test_zotero_compat.py`가 이 requests→httpx 이행을 이미 알고 있었다는 점이 뼈아프다.
retry 판정에는 httpx 타입을 추가했지만, **SSL 우회책도 requests에 매여 있다는 사실은 같이
검토되지 않았다.** 한 라이브러리 교체가 건드리는 지점은 한 곳이 아니다.

## 고친 방법 — 검증을 끄는 대신, 맞는 CA를 보게 한다

`truststore`(MIT)를 넣고 `papermeister/nettls.py::install_system_trust()`에서
`inject_into_ssl()`을 한 번 호출한다. 이러면 파이썬의 TLS 검증이 **OS 신뢰 저장소**를 보게 되고,
KOPRI CA는 원래 거기 있다. httpx·requests 양쪽에 동시에 적용된다(둘 다 `ssl.SSLContext`를 거친다).

`verify=False`보다 나은 이유는 취향이 아니다.

- 옛 패치는 **모든 호스트**에 대해 검증을 껐다. 가로채는 네트워크가 아닌 곳에서도 껐다 —
  즉 문제가 없는 상황에서 보안을 깎고 있었다.
- 옛 패치는 **Zotero를 이미 보호하지 못하고 있었다**(위 참조). 남아 있던 효과는 부작용뿐이었다.
- 새 방식은 CA 하나를 더 신뢰하는 것이고, 그 판단은 이미 기기 관리자가 OS 저장소에 넣어
  내려둔 상태다.

`inject_into_ssl()`은 프로세스 전역이고 **이후에 만들어지는 SSLContext에만** 적용되므로,
호출 지점은 진입점(`desktop/app.py`·`main.py`·`cli.py::_init`)이지 호출부가 아니다.
truststore가 없거나 플랫폼이 거부하면 `False`를 반환하고 certifi로 계속 간다 — 가로채지 않는
네트워크에서는 그것으로 충분하므로, 이것 때문에 앱이 뜨지 못할 이유가 없다.

## 검증

라이브 Windows 환경(그 네트워크 안)에서 실제로 재현하고 실제로 고쳤다.

| | 결과 |
|---|---|
| `httpx.get('https://api.zotero.org/')` (certifi) | `FAIL ConnectError: CERTIFICATE_VERIFY_FAILED` |
| 같은 호출 + `truststore.inject_into_ssl()` | `OK 200` |
| `ZoteroClient.key_info()` / `last_modified_version()` | `True` / `69960` |

마지막 줄은 앱이 실제로 쓰는 클라이언트로, **검증을 켠 채** 통과한 것이다.

## 한 일

- `papermeister/nettls.py` 신설. `requirements.txt`에 `truststore~=0.10.4`, lock 재생성,
  `about.py` 라이선스 표에 MIT로 등록(테스트가 강제한다 — HANDOFF의 상수 항목 그대로)
- `desktop/app.py`의 monkey-patch 제거, `main.py`·`cli.py`에 설치 호출 추가.
  `main.py`는 `cli.py`와 달리 원래 이 우회책이 없었다 — 동결된 GUI지만 Zotero는 쓴다
- 스크립트 10개의 복사본 블록을 같은 한 줄 호출로 교체
- `tests/test_nettls.py` — 주입 1회·실패 무해·실제 플랫폼에서 동작에 더해, **`verify=False`가
  1차 소스에 다시 들어오면 실패하는 회귀 테스트**. 이번 건의 교훈은 "우회책은 조용히 썩는다"이므로
  썩을 수 있는 형태 자체를 막았다

## 남는 것

CA가 OS 저장소에 없는 기기에서는 여전히 실패한다(그때는 인증서를 신뢰할 근거가 실제로 없으므로
맞는 동작이다). 그 경우의 안내는 매뉴얼 troubleshooting에 추가할 후보.
