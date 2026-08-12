# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PaperMeister desktop app (onedir).

Build (on Windows, from the repo root, in the env that has the runtime deps):

    pip install pyinstaller
    pyinstaller PaperMeister.spec --noconfirm

Output: dist/PaperMeister/PaperMeister.exe (+ _internal/ with Qt, pymupdf, etc.).
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
- User data (DB / OCR cache / preferences.json) lives in ~/PaleoBytes/PaperMeister and is
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

# --- Fix MSVC runtime DLL shadowing -----------------------------------------
# PyQt6's Qt6\bin ships a current MSVC runtime (e.g. 14.44). Building inside a
# conda env, PyInstaller ALSO drops conda's older runtime (e.g. 14.29) at the
# bundle ROOT, where it shadows PyQt6's copy at load time and makes Qt 6.11
# fail with "DLL load failed importing QtWidgets: the specified procedure
# could not be found". For any root-level binary that PyQt6 also ships under
# Qt6\bin, re-point the root copy at PyQt6's (newer) source so both PyMuPDF
# (root search path) and Qt resolve the same, current runtime.
import os

_pyqt_bin = {}
for _dest, _src, _typ in a.binaries:
    _d = _dest.replace('\\', '/').lower()
    if _d.startswith('pyqt6/qt6/bin/'):
        _pyqt_bin[os.path.basename(_d)] = _src

_patched = []
for _dest, _src, _typ in a.binaries:
    _d = _dest.replace('\\', '/')
    _base = os.path.basename(_d).lower()
    if '/' not in _d and _base in _pyqt_bin:   # root-level dup of a PyQt6 DLL
        _patched.append((_dest, _pyqt_bin[_base], _typ))
    else:
        _patched.append((_dest, _src, _typ))
a.binaries = _patched
# ----------------------------------------------------------------------------

# --- Pull conda's stdlib-support DLLs from Library\bin ----------------------
# Conda relocates DLLs that Python's C extensions need (sqlite3, openssl, ...)
# into <env>\Library\bin instead of DLLs\. When we build with conda OFF PATH
# (required to keep conda's Qt-conflicting DLLs out of the bundle), PyInstaller
# can't find them, so _sqlite3 / _ssl / _hashlib / _lzma / _bz2 fail at runtime
# ("SQLite driver not installed!", ssl import errors, ...). Add just the ones
# we need straight from the base env's Library\bin. None of these touch Qt.
import sys
import glob as _glob

_libbin = os.path.join(sys.base_prefix, 'Library', 'bin')
if os.path.isdir(_libbin):
    _have = {os.path.basename(d).lower() for d, _s, _t in a.binaries}
    _wanted = [
        'sqlite3.dll',
        'libssl-3-x64.dll', 'libssl-3.dll',
        'libcrypto-3-x64.dll', 'libcrypto-3.dll',
        'libffi-8.dll', 'libffi.dll',
        'liblzma.dll',
        'libbz2.dll', 'bzip2.dll',
    ]
    _patterns = ['libssl-*.dll', 'libcrypto-*.dll', 'libffi*.dll']
    _paths = [os.path.join(_libbin, n) for n in _wanted]
    for _pat in _patterns:
        _paths += _glob.glob(os.path.join(_libbin, _pat))
    for _p in sorted(set(_paths)):
        _name = os.path.basename(_p)
        if os.path.isfile(_p) and _name.lower() not in _have:
            a.binaries.append((_name, _p, 'BINARY'))
            _have.add(_name.lower())
# ----------------------------------------------------------------------------

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir by default; set env PM_ONEFILE=1 to build a single-file .exe.
ONEFILE = os.environ.get('PM_ONEFILE') == '1'

# Flip to True (or set env PM_CONSOLE=1) for a console build that prints the
# full traceback to the terminal instead of a dialog — useful while debugging.
CONSOLE = os.environ.get('PM_CONSOLE') == '1'

_exe_common = dict(
    name='PaperMeister',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX can trip antivirus; keep off
    console=CONSOLE,            # windowed GUI app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                  # add a .ico path here for a custom app icon
)

if ONEFILE:
    # Everything embedded in one PaperMeister.exe (extracted to a temp dir at
    # launch). dist/PaperMeister.exe
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        runtime_tmpdir=None,
        **_exe_common,
    )
else:
    # onedir: exe + _internal/ folder. dist/PaperMeister/PaperMeister.exe
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_exe_common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='PaperMeister',
    )
