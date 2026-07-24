# 071 — P15 구현: 코드 품질 인프라 + 크로스플랫폼 릴리스

> 구현 기록 (2026-07-23~24). 검토 [R01](20260723_R01_Code_Quality_Guide_Adoption.md),
> 계획 [P15](20260723_P15_Code_Quality_Adoption_Plan.md). ../Modan2 가이드를 개인 도구 현실에
> 맞춰 도입. **R-series(리뷰/감사) devlog 타입을 CLAUDE.md에 신설.**

## P15 6단계 (전부 완료)

1. **ruff** — `pyproject.toml` curated 룰셋(base + DTZ/RUF012/S; 스타일 SIM/RET/PIE/A는 후속
   패스로 연기). Qt camelCase·의도적 패턴은 사유 달아 ignore. 61파일 자동+수동 수정. `requires-python≥3.12`.
2. **pytest** — markers(unit/ui/integration) + `tests/`(conftest headless Qt). 회귀 테스트
   씨앗: 스코어러(P14)/CJK 저자/ServerGuard/import 스모크. **73 passed**. `pythonpath=["."]`로
   plain `pytest`도 import되게(CI가 실제 잡은 버그).
3. **CI + 릴리스** — Modan2 미러(아래 §).
4. **견고성** — `desktop/app.py`에 전역 `sys.excepthook`(미처리 슬롯 예외 로깅+비치명 다이얼로그,
   KeyboardInterrupt 위임) + `.pre-commit-config.yaml`(ruff --fix + 파일위생; ruff-format 보류).
5. **deps 보안 + mypy** — `pip-audit`로 Pillow 10(CVE 다수)·requests·python-dotenv 발견 →
   **python-dotenv 제거**(미사용: main.py가 .env를 plain open()으로 읽음), Pillow≥12.3·requests≥2.33.
   `security.yml`(pip-audit 주간 cron). mypy를 references/search/biblio 3모듈 clean → CI 게이트.
   vulture는 **사용자 요청으로 제외**.
6. **인코딩 + 패키징 문서** — 텍스트 `open()` 잔여 3곳에 `encoding='utf-8'`. `docs/RELEASE.md`.

**의도적 미실행**(1인 도구엔 과잉): `ruff format` 대량 커밋, vulture, 엄격 coverage gate,
Dependabot, 코드사이닝.

## 크로스플랫폼 릴리스 (Modan2 미러)

`version.py`(`__version__`) + build_number=`git rev-list --count`. `.github/workflows/`:
- **test.yml**: ruff+mypy lint 게이트 + {ubuntu,windows}×3.12 매트릭스(import 스모크+pytest).
  OpenGL/GLUT/Xvfb 불필요(PDF는 PyMuPDF). `workflow_call` 노출.
- **reusable_build.yml** — 3 레그:
  - **Windows**: clean **pip**(conda 아님 → devlog 061 함정 회피, spec conda 보강은 `os.path.isdir`
    가드로 no-op) → `pyinstaller` → portable zip **+ Inno Setup 설치본**(per-user).
  - **Linux**: onedir → **AppImage**(`packaging/linux/create_appimage.sh`, appimagetool
    `APPIMAGE_EXTRACT_AND_RUN=1`로 FUSE 회피).
  - **macOS**: onedir → 수동 `.app` → **DMG**(`hdiutil` — create-dmg의 AppleScript는 헤드리스
    CI 불안정). **미공증**(Gatekeeper 우회 필요).
- **build.yml**: 수동(`workflow_dispatch`)만 — 커밋 잦아 매-push 빌드는 과함.
- **release.yml**: 태그 `v*.*.*` → test 게이트 → build → GitHub Release(4종 산출물 + SHA256,
  `-alpha/-beta/-rc`면 prerelease).

**검증**: CI 라이브 그린(Linux+Windows), 수동 Build로 **3플랫폼 전부 실빌드 성공**, v0.1.0 릴리스
end-to-end, Windows에서 `verify_image.py`가 Pillow 12.3.0 PASS(OCR 이미지 경로 무손상).

## 결정 로그
- 왜 Modan2 그대로가 아닌가: PaperMeister는 1인·Windows-run이라 배포 항목 완화, build는 수동.
- Windows-first로 시작 → 사용자 요청으로 Linux, 그다음 macOS 레그 추가(전부 미서명 — 개인 도구엔 수용).
- 액션 버전은 Modan2와 동일(Node 24)로 통일해 deprecation 워닝 제거.
