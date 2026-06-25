@echo off
REM ==========================================================================
REM Reprocess references after the multi-article journal-issue detection fix
REM (devlog 065). Run from the Windows Anaconda Prompt (with the project's conda
REM env active) -- the live DB, OCR cache and Qwen server are all on Windows.
REM
REM   1. Reset the wrongly-extracted Kaseki (化石) journal volumes
REM      (delete their Reference rows + clear references_checked).
REM   2. Extract references for every pending paper (the reset 11 + all others).
REM   3. Reconcile CitedWork cite_counts (deterministic pass-1, no LLM).
REM
REM Each step writes to the DB (--execute). Run reset_references.py /
REM extract_references.py WITHOUT --execute first if you want a dry-run preview.
REM ==========================================================================

setlocal
cd /d "%~dp0.."

echo === [1/3] Reset wrongly-extracted Kaseki volumes (16,17,19,20,22,24,25,26,27,28,29) ===
python scripts\reset_references.py --execute || exit /b 1

echo.
echo === [2/3] Extract references for all pending papers (workers=3) ===
python scripts\extract_references.py --scope all --workers 3 --execute || exit /b 1

echo.
echo === [3/3] Reconcile CitedWork cite_counts (pass 1, deterministic) ===
python scripts\normalize_works.py --pass 1 --execute || exit /b 1

echo.
echo === DONE ===
endlocal
