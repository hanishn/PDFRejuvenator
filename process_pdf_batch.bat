@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUNBUFFERED=1"

if "%~1"=="--help" goto help
if "%~1"=="-h" goto help

python "scripts\run_pdf_batch.py" %*
exit /b %ERRORLEVEL%

:help
echo Usage:
echo   process_pdf_batch.bat [optional flags]
echo.
echo Default batch:
echo   process_pdf_batch.bat --pdf "source_pdfs" --clean --force-rollout --book-workers 2 --rollout-workers 2
echo.
echo Smoke test:
echo   process_pdf_batch.bat --pdf "source_pdfs" --pages "1-3" --clean --force-rollout --book-workers 2 --rollout-workers 2
echo.
echo What would run:
echo   process_pdf_batch.bat --dry-run
echo.
echo Useful flags:
echo   --pdf PATH             PDF file or directory. Can be repeated.
echo   --book-workers 2       Number of PDFs/books to run at once.
echo   --rollout-workers 2    Number of rollout chunks per book.
echo   --chunk-size 5         Pages per rollout chunk.
echo   --pages "1-3"          Same page range for every PDF smoke test.
echo   --clean                Delete each PDF-specific run folder before processing.
echo   --force-rollout        Re-run rollout even where records exist.
echo   --dry-run              Print commands without running them.
exit /b 0
