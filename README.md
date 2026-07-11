# PDFRejuvenator

PDFRejuvenator converts PDFs into editable SVG review packets.

## Current v0.3 Command

Process a short page range:

```powershell
python -m pdfrejuvenator process "G:\path\to\source.pdf" --pages "1-5" --clean --force-rollout
```

Process through the batch wrapper:

```powershell
.\process_pdf.bat "G:\path\to\source.pdf" --pages "1-5" --clean --force-rollout
```

Run the full PDF by removing `--pages`:

```powershell
python -m pdfrejuvenator process "G:\path\to\source.pdf" --clean --force-rollout
```

## Output

By default, the clean user-facing output is created beside the source PDF:

```text
source_pdf_name_pdfrejuvenator_output\
```

Open first:

```text
dashboard.html
```

The file to edit for each page is:

```text
pages\page_###_edit_this_page.svg
```

The matching preview is:

```text
pages\page_###_preview.png
```

Debug pointers and internal run paths are under `_debug\`. Local search data is under `_search\`.

The main `manifest.csv` is user-facing. Internal source artifact paths are kept in `_debug\debug_manifest.csv`.

## Search

```powershell
python -m pdfrejuvenator search "search terms" --output-dir "G:\path\to\source_pdfrejuvenator_output"
```

The `_search` index contains extracted text, OCR text for image-only pages, and metadata from the source PDF. Treat it as local/private data unless the source PDF and extracted text are cleared for sharing.

## v0.4 Corpus Intake

The v0.4 intake layer adds schema and validation primitives for private large-book corpus registration before extraction or indexing starts.

Run the intake validator:

```powershell
python scripts\validate_corpus_intake.py
```

The intake layer records source metadata, hash evidence, privacy class, rights class, processing intent, and batch state. Private OCR, embeddings, and public release actions require separate approval gates.

Create an inventory-only manifest:

```powershell
python -m pdfrejuvenator inventory ".\samples" --output ".\local_inventory_manifest.json" --privacy-class public_sample --rights-class original
```

Build a metadata-only search index from a manifest:

```powershell
python -m pdfrejuvenator index-manifest ".\local_inventory_manifest.json" --output ".\local_inventory_index.jsonl"
```

Build a text search index from synthetic or separately approved text records:

```powershell
python -m pdfrejuvenator index-text-records ".\synthetic_text_records.json" --output ".\synthetic_text_index.jsonl"
```

Build table and image metadata indexes from synthetic or separately approved records:

```powershell
python -m pdfrejuvenator index-table-records ".\synthetic_table_records.json" --output ".\synthetic_table_index.jsonl"
python -m pdfrejuvenator index-image-records ".\synthetic_image_records.json" --output ".\synthetic_image_index.jsonl"
```

## Validation

Project validation:

```powershell
python scripts\validate_pdfrejuvenator.py
```

Validate an existing consolidated output folder:

```powershell
python scripts\validate_consolidated_review_output.py "G:\path\to\source_pdfrejuvenator_output" --mode internal
```

Internal mode fails hard. External mode preserves partial/noisy output and writes validation labels/reports:

```powershell
python -m pdfrejuvenator process "G:\path\to\source.pdf" --pages "1-5" --clean --force-rollout --validation-mode external
```

## Public Sample

The repository includes a synthetic sample PDF:

```text
samples\shadow_power_play_sample.pdf
```

It is original placeholder adventure material designed to exercise PDFRejuvenator layout conversion: headings, body text, tables, boxed text, placeholder art, and page footers.

Run it with:

```powershell
python -m pdfrejuvenator process ".\samples\shadow_power_play_sample.pdf" --pages "1-3" --clean --force-rollout
```

## Build A Handoff Package

Build a scrubbed command-line package:

```powershell
python scripts\build_pdfrejuvenator_package.py --output-dir "G:\path\to\PDFRejuvenator_v0.3" --zip --clean
```

Optionally include one or more private PDFs under `source_pdfs\` for a local handoff:

```powershell
python scripts\build_pdfrejuvenator_package.py --output-dir "G:\path\to\PDFRejuvenator_v0.3" --source-pdf "G:\path\to\private-test.pdf" --zip --clean
```

The scrubbed package includes only the v0.3 runtime scripts and docs. Private regression configs and legacy fixture scripts are not copied.

## License

PDFRejuvenator v0.3 is released under the Apache License 2.0.

This public version is open source. Future commercial products or hosted services may use different packaging, support terms, or licensing.

## Guides

- `README_COMMAND_LINE_HANDOFF.md`
- `docs\GITHUB_PUBLICATION_CHECKLIST.md`
- `docs\CORPUS_INTAKE_ARCHITECTURE.md`
- `docs\OUTPUT_GUIDE.md`
- `docs\PUBLICATION_GUIDE.md`
- `docs\VALIDATION_GUIDE.md`

Private validation PDFs and legacy fixture scripts are retained locally for regression testing. They are not public fixtures and are not part of a public GitHub release surface.
