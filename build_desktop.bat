@echo off
REM ---------------------------------------------------------------------------
REM Build the PaperMeister desktop app into a standalone Windows folder (.exe).
REM Run from the repo root, in the Python env that has the runtime deps
REM (the same env you use for `python -m desktop`).
REM
REM   build_desktop.bat
REM
REM Output: dist\PaperMeister\PaperMeister.exe  (distribute the whole folder)
REM ---------------------------------------------------------------------------
setlocal

echo [1/3] Ensuring PyInstaller + hooks are up to date...
REM --upgrade matters: a stale PyInstaller/hooks-contrib mis-bundles recent
REM PyQt6 (6.11+), causing "DLL load failed importing QtWidgets" at runtime.
python -m pip install --quiet --upgrade pyinstaller pyinstaller-hooks-contrib || goto :err

echo [2/3] Cleaning previous build...
if exist build\PaperMeister rmdir /s /q build\PaperMeister
if exist dist\PaperMeister rmdir /s /q dist\PaperMeister

echo [3/3] Building (onedir) from PaperMeister.spec...
python -m PyInstaller PaperMeister.spec --noconfirm --clean || goto :err

echo.
echo Done. Launch:  dist\PaperMeister\PaperMeister.exe
goto :eof

:err
echo.
echo BUILD FAILED. See the output above.
exit /b 1
