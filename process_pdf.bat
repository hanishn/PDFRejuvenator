@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUNBUFFERED=1"
set "USAGE_EXIT=2"

if /i "%~1"=="--help" set "USAGE_EXIT=0" & goto usage
if /i "%~1"=="-h" set "USAGE_EXIT=0" & goto usage

if "%~1"=="" (
:usage
  echo Usage:
  echo   process_pdf.bat "PATH\TO\SOURCE.pdf" [optional regeneration flags]
  echo.
  echo Examples:
  echo   process_pdf.bat "source_pdfs\example_book.pdf"
  echo   process_pdf.bat "source_pdfs\example_book.pdf" --clean --force-rollout
  echo   process_pdf.bat "source_pdfs\example_book.pdf" --pages "1-5" --clean --force-rollout
  echo.
  echo Optional flags are passed through to the PDFRejuvenator process command.
  echo Common flags:
  echo   --clean              Delete prior full output before regenerating.
  echo   --force-rollout      Re-run rollout chunks even if outputs already exist.
  echo   --pages "1-5"        Process a page range for testing.
  echo   --chunk-size 5       Pages per rollout chunk.
  echo   --workers 4          Rollout chunks to process concurrently.
  echo   --timeout-seconds 900  Per-chunk timeout.
  exit /b %USAGE_EXIT%
)

set "SOURCE_PDF=%~1"
shift /1
if not exist "%SOURCE_PDF%" (
  if "%SOURCE_PDF:~-1%"=="\" (
    set "SOURCE_PDF=%SOURCE_PDF:~0,-1%"
  )
)
set "OPTION_ARGS="
set "HELP_ONLY=0"

:collect_args
if "%~1"=="" goto args_done
if "%~1"=="""" (
  shift /1
  goto collect_args
)
if "%~1"=="\" (
  shift /1
  goto collect_args
)
if /i "%~1"=="--help" set "HELP_ONLY=1"
if /i "%~1"=="-h" set "HELP_ONLY=1"
set "OPTION_ARGS=%OPTION_ARGS% "%~1""
shift /1
goto collect_args

:args_done

if not exist "%SOURCE_PDF%" (
  echo ERROR: Source PDF not found:
  echo   "%SOURCE_PDF%"
  exit /b 2
)

if not exist "pdfrejuvenator\__main__.py" (
  echo ERROR: Missing pdfrejuvenator\__main__.py
  echo Run this batch file from the PDFRejuvenator packet root.
  exit /b 2
)

python -m pdfrejuvenator process "%SOURCE_PDF%" %OPTION_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"

if "%HELP_ONLY%"=="1" (
  exit /b %EXIT_CODE%
)

if not "%EXIT_CODE%"=="0" (
  echo.
  echo FAILED: full-book regeneration exited with code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

echo.
echo DONE.
echo The exact REVIEW_PACKET, REVIEW_PACKET_ZIP, and DASHBOARD paths are printed above.
exit /b 0
