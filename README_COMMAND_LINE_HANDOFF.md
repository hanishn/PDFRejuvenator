# PDFRejuvenator Command-Line Handoff

## Install

Open PowerShell or Command Prompt in the package folder.

Install Python requirements:

```powershell
.\install_pdfrejuvenator.bat
```

## Process A PDF

Put the PDF under:

```text
source_pdfs\
```

Run:

```powershell
.\process_pdf.bat ".\source_pdfs\YOUR_FILE.pdf" --pages "1-5" --clean --force-rollout
```

What the command does:

- `.\process_pdf.bat` starts PDFRejuvenator from the package folder.
- `".\source_pdfs\YOUR_FILE.pdf"` chooses the PDF to process.
- `--pages "1-5"` runs only pages 1 through 5 for a short test. Remove this option for a full PDF.
- `--clean` clears the prior output for this run before rebuilding it.
- `--force-rollout` regenerates editable SVG review files even if prior rollout files exist.

## Full PDF Run

```powershell
.\process_pdf.bat ".\source_pdfs\YOUR_FILE.pdf" --clean --force-rollout
```

## Output

By default, output appears beside the source PDF:

```text
source_pdfs\YOUR_FILE_pdfrejuvenator_output\
```

Open first:

```text
dashboard.html
```

The file someone usually wants to edit is:

```text
pages\page_###_edit_this_page.svg
```

Example:

```text
pages\page_005_edit_this_page.svg
```

The matching preview image is:

```text
pages\page_005_preview.png
```

## Search The Output

After processing, search the local output:

```powershell
python -m pdfrejuvenator search "search terms" --output-dir ".\source_pdfs\YOUR_FILE_pdfrejuvenator_output"
```

The search index is local/private because it contains extracted text from the PDF.

## Help

```powershell
.\process_pdf.bat --help
python -m pdfrejuvenator --help
python -m pdfrejuvenator search --help
```
