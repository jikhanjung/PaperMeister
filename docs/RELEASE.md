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
3. `release.yml` runs: **test** (ruff + mypy + Linux/Windows pytest) → **build**
   (windows-latest: `pyinstaller PaperMeister.spec` → portable zip) →
   **GitHub Release** with the zip + `SHA256SUMS.txt`.
   - Pre-release: use a `-alpha` / `-beta` / `-rc` suffix (auto-marked prerelease).

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
- Installer (Inno Setup) — currently portable zip only.
- App icon / version metadata stamped on the exe.
- macOS / Linux legs — add to `reusable_build.yml` the same way as Modan2.
- CHANGELOG.md-sourced release notes — currently checksums + commit SHA only.
