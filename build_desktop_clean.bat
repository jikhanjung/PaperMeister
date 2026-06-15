@echo off
REM ---------------------------------------------------------------------------
REM Build PaperMeister.exe in a CLEAN, conda-free virtualenv.
REM
REM This is the VERIFIED recipe (see devlog P02). Building from the activated
REM conda env mixed conda's Qt-dependency DLLs into the bundle and the frozen
REM app died with:
REM   "ImportError: DLL load failed while importing QtWidgets:
REM    the specified procedure could not be found"
REM A venv with conda OFF PATH eliminates that. The spec then pulls the few
REM stdlib-support DLLs conda hides in Library\bin (sqlite3 / openssl / ...).
REM
REM HOW TO RUN
REM   1. Open a PLAIN cmd window (Win+R -> cmd). NOT an Anaconda Prompt, and
REM      NOT a shell whose prompt shows "(base)"/"(PaperMeister)". conda's
REM      Library\bin must NOT be on PATH during the build.
REM   2. Pass the path to the conda env's python.exe (used only as the venv's
REM      base interpreter; conda itself stays off PATH):
REM
REM        build_desktop_clean.bat "C:\Users\<you>\anaconda3\envs\PaperMeister\python.exe"
REM
REM      Omit the arg to use whatever `python` is on PATH (only if that is a
REM      non-conda Python).
REM ---------------------------------------------------------------------------
setlocal
set VENV=.build-venv
set BASEPY=%~1
if "%BASEPY%"=="" set BASEPY=python

if defined CONDA_PREFIX (
    echo [!] CONDA_PREFIX is set ^(%CONDA_PREFIX%^) -- conda looks ACTIVE.
    echo     Open a plain cmd with conda NOT activated, then re-run. Otherwise
    echo     conda's Qt-dependency DLLs may contaminate the bundle again.
    echo.
)

echo [1/5] Creating clean venv (%VENV%) from: %BASEPY%
if exist %VENV% rmdir /s /q %VENV%
"%BASEPY%" -m venv %VENV% || goto :err
call %VENV%\Scripts\activate.bat || goto :err

echo [2/5] Confirming conda is NOT on PATH (these should be empty / venv only)...
where Qt6Core.dll
where python

echo [3/5] Installing pip-only deps...
python -m pip install --upgrade pip --quiet || goto :err
python -m pip install -r requirements.txt --quiet || goto :err
python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib --quiet || goto :err

echo [4/5] Clean + build from PaperMeister.spec...
if exist build\PaperMeister rmdir /s /q build\PaperMeister
if exist dist\PaperMeister rmdir /s /q dist\PaperMeister
python -m PyInstaller PaperMeister.spec --noconfirm --clean || goto :err

echo.
echo [5/5] Done. Launch:  dist\PaperMeister\PaperMeister.exe
goto :eof

:err
echo.
echo BUILD FAILED. See the output above.
exit /b 1
