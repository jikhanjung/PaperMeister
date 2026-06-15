# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PaperMeister desktop app (onedir).

Build (on Windows, from the repo root, in the env that has the runtime deps):

    pip install pyinstaller
    pyinstaller PaperMeister.spec --noconfirm

Output: dist/PaperMeister/PaperMeister.exe (+ _internal/ with Qt, fitz, etc.).
Distribute the whole dist/PaperMeister/ folder (zip it).

Notes
-----
- Entry point is run_desktop.py (== `python -m desktop`).
- The only bundled data files are the SVG rail/chevron icons. They are loaded
  at runtime via `Path(__file__).parent / 'icons'` in both desktop/theme/icons.py
  and desktop/theme/qss.py, so they must keep their `desktop/theme/icons/...`
  layout under the bundle — hence the (src, dest) pair below.
- `claude -p` (biblio extraction) is an EXTERNAL CLI shelled out via subprocess;
  it is NOT bundled. The packaged app needs `claude` on PATH for biblio work,
  exactly like `python -m desktop` does today.
- User data (DB / OCR cache / preferences.json) lives in ~/.papermeister and is
  created at runtime — never bundled.
- `excludes` keeps a fat Anaconda base env (numpy/scipy/mkl/etc.) and rival Qt
  bindings out of the bundle. None of these are real dependencies.
"""

block_cipher = None

datas = [
    ('desktop/theme/icons', 'desktop/theme/icons'),
]

hiddenimports = [
    # desktop reuses these frozen dialogs via lazy (in-function) imports.
    'papermeister.ui.process_window',
    'papermeister.ui.preferences_dialog',
]

excludes = [
    # Rival GUI toolkits / Qt bindings.
    'tkinter', 'PySide6', 'PySide2', 'PyQt5',
    # Scientific stack that Anaconda base drags in but we never use.
    'numpy', 'scipy', 'pandas', 'matplotlib', 'sympy', 'numba',
    # Notebook / test / dev tooling.
    'IPython', 'jupyter', 'notebook', 'pytest', 'sphinx',
    # Heavy optional Qt modules we don't touch.
    'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtMultimedia', 'PyQt6.QtQml', 'PyQt6.Qt3DCore',
]


a = Analysis(
    ['run_desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir: binaries go in COLLECT, not the exe
    name='PaperMeister',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX can trip antivirus; keep off
    console=False,              # windowed GUI app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                  # add a .ico path here for a custom app icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PaperMeister',
)
