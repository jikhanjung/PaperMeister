# Release & Packaging

PaperMeister ships a **Windows portable build**, produced by **CI** — never the
maintainer's laptop. A clean pip environment (not conda) is exactly what avoids
the conda-DLL packaging trap (devlog 061); the spec's conda `Library\bin` fixup
is guarded by `os.path.isdir`, so it no-ops on the CI runner.

## Cutting a release

1. Bump `version.py` `__version__` (e.g. `0.1.0` → `0.1.1`) and commit.
2. Tag and push:
   ```
   git tag -a v0.1.1 -m "PaperMeister v0.1.1"
   git push origin v0.1.1
   ```
3. `release.yml` runs: **test** (ruff + mypy + Linux/Windows pytest) → **build** →
   **GitHub Release** with all artifacts + `SHA256SUMS.txt`. Build outputs:
   - **Windows** (windows-latest): `pyinstaller PaperMeister.spec` → **portable zip**
     + **Inno Setup installer** (`installer/PaperMeister.iss.template`).
   - **Linux** (ubuntu-latest): PyInstaller onedir wrapped as an **AppImage**
     (`packaging/linux/create_appimage.sh`).
   - **macOS** (macos-latest, arm64): PyInstaller onedir → `.app` → **`.dmg`**
     (`packaging/macos/create_dmg.sh`, via `hdiutil`). **Not code-signed/notarized**
     — Gatekeeper warns on first launch; right-click → Open, or
     `xattr -dr com.apple.quarantine PaperMeister.app`.
   - Pre-release: use a `-alpha` / `-beta` / `-rc` suffix (auto-marked prerelease).
   - The Windows installer is a **per-user** install (no admin) into
     `%LocalAppData%\Programs\PaperMeister`, with Start-Menu (+ optional desktop) icons.
   - The Linux AppImage bundles Qt but not host system libs, so a target machine may
     still need the xcb runtime libs; run with `--appimage-extract-and-run` if FUSE
     is unavailable.

On-demand build **without** a release: Actions → **Build** → *Run workflow*
(uploads the zip artifact only, no Release).

## Local build (to test the package yourself)

Windows, plain **cmd** — NOT the conda shell (see devlog 061):
```
build_desktop_clean.bat
```
→ `dist\PaperMeister\PaperMeister.exe`

## Artifact smoke checklist

Download the release zip on a **clean Windows machine** (no dev env), extract,
run `PaperMeister.exe`, and confirm — these are the "works from source, broken
when frozen" gaps (bundled data files, native libs) that source tests can't prove:

- [ ] Window opens — Qt loads, no "procedure not found" DLL error
- [ ] Library / DB opens — SQLite driver bundled
- [ ] Zotero sync runs — SSL/openssl bundled (needs configured credentials)
- [ ] Open a paper → **PDF** tab renders — PyMuPDF
- [ ] **Search** returns results — FTS5
- [ ] **Text** (OCR) tab renders — image handling / Pillow
- [ ] SVG rail icons show — the one source-relative data dir (`desktop/theme/icons`)

## Future
- App icon / version metadata stamped on the exe.
- macOS **codesigning + notarization** (Apple Developer account) — the DMG builds
  but is unsigned, so Gatekeeper warns. Until then, users open via right-click.
- A real app icon (the AppImage/macOS build currently ship a generated placeholder /
  no custom icon).
- CHANGELOG.md-sourced release notes — currently checksums + commit SHA only.
