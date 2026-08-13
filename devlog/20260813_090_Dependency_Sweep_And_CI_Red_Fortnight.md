# 090 — Dependabot 5건 정리, 그리고 CI가 2주 동안 red였던 이유

2026-08-13

## 배경

7/29 이후 2주 동안 코드 커밋이 없었다. 배치만 돌았고 Dependabot PR이 5건 쌓였다.

## 검증 방식

081의 관례대로 **CI 그린만 믿지 않았다** — 커버리지가 19.6%이고 실패 경로는
테스트가 안 닿는다. 각 버전을 실제로 설치해 **우리가 호출하는 API 면을 훑는
probe**를 만들어 baseline과 출력을 diff했다:

- peewee: FTS5 external-content 트리거, `snippet()`/`bm25()`, `search()` 왕복,
  `fn`/JOIN/atomic, fk `_id` 접근(관계 fetch 없이), AutoField
- PyMuPDF: open/page_count/metadata/load_page/get_pixmap/Matrix/tobytes/close
- pyzotero: 클라이언트 메서드 16종 존재 확인 + `zotero_errors` 이름 조회 폴백
- platformdirs: `user_config_dir` + 우리 `CONFIG_DIR` 조립

전부 버전 배너 빼고 **byte-identical**. 151 테스트도 전 버전에서 통과.

## 🔴 peewee 4.3.0은 단독 머지가 불가능했다

4.3.0이 **자기참조 FK의 문자열 형태(`'self'`) 오버로드를 고쳤다.** 그 결과
`models.py`의 `# type: ignore[call-overload]`가 unused가 되어 mypy
`warn-unused-ignores`에 걸린다. **Dependabot은 requirements만 건드리므로 그
PR을 그대로 머지했으면 main이 red가 됐다.** 그래서 4건을 코드 수정과 함께
main에 직접 커밋하고 Dependabot이 자동 close하게 했다.

교훈: 타입 스텁이 개선되는 업그레이드는 **에러가 줄어드는 방향으로도** 게이트를
깨뜨린다. 늘어나는 쪽만 경계하면 놓친다.

## codeql-action은 받지 않았다

Dependabot이 `@v4` → `@v4.37.4` 핀을 제안했는데, 이 리포의 액션 참조 12개가
**전부 floating major**(`@v7`, `@v4`, `@v5`, `@v6`, `@v3`)다. 받으면 이것만
패치마다 PR이 생기는 유일한 예외가 된다. close하고 `dependabot.yml`에
patch/minor ignore를 넣었다 — major는 계속 온다(그건 사람이 볼 값어치가 있다).

## 🔴 CI가 7/29 이후 2주 동안 red였다

푸시하자마자 Tests가 Windows 레그에서 실패했다. 내 변경 때문이 아니었다 —
**8/10 Dependabot PR도 같은 에러로 실패**했고, main의 마지막 green Tests는
7/29(내 마지막 커밋)였다.

원인: `pip-audit`이 `pip-api`를 끌어오고, **`pip-api`가 pip 자신을
`requirements-dev.lock`에 핀한다**(`pip==26.1.2`). 그래서 이 설치는 pip를
덮어쓰는데, **Windows에서 `pip.exe`는 자기가 실행 중인 파일을 교체할 수 없다**
(`ERROR: To modify pip, please run ...`). `python -m pip`로 부르면 된다.

**왜 2주 동안 몰랐나** — 세 겹이다:

1. **Linux 레그는 멀쩡했다.** 잡이 반만 건강해 보였다.
2. **Tests는 push/PR에서만 돈다.** 7/29~8/12에 main에 push가 없었으므로
   main은 계속 7/29의 green을 표시했다.
3. **스케줄로 도는 Security·CodeQL은 green이었다.** 주기적으로 도는 잡이
   초록이니 리포가 건강해 보였다.

086에서 "릴리스를 안 컷하는 동안은 아무도 안 본다"고 적었는데, 이번엔 **커밋을
안 하는 동안 아무도 안 봤다.** 같은 실패 방식이 조건만 바꿔 재발했다.

수정은 `python -m pip`. 앞서 있던 `--upgrade pip` 줄은 뺐다 — lock이 pip를
핀하므로 pip를 올린 다음 줄에서 핀된 옛 버전을 다시 까는 왕복이었다.

## 부수 효과: `fitz` 별칭 제거

PyMuPDF 1.28.2가 `import fitz`에 deprecation 경고를 내기 시작했다(앱 시작마다
출력). 별칭에 예고된 끝이 있으므로 어차피 할 일이라, `import pymupdf` /
`pymupdf.` 로 기계적 rename했다(papermeister/·desktop/·scripts/, 9곳).
`deploy/chandra2-vllm-pod/batch_ocr.py`는 서버 pod 자기 환경이라 두었다.

## 결과

- 열린 PR 0건, Tests·Security·CodeQL 전부 green
- pyzotero는 PR이 제안한 1.13.4가 아니라 **lock이 잡은 1.13.5**로 검증·반영
- platformdirs는 floor만 `>=4.11.1`, lock은 4.11.2
