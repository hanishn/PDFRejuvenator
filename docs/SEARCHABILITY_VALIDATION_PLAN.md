# Searchability Validation Plan

Status: internal v0.3.1 proof plan

## Feature Definition

PDFRejuvenator searchability means the consolidated local output contains a private `_search` directory with repeatable JSONL records that can be searched without reopening the source PDF.

Required searchable record types:

- `page`: one record per processed page. Text is the page-level aggregate of extracted PDF text plus OCR text when OCR records exist.
- `text_region`: one record per extracted PDF text region with non-empty text.
- `ocr_text`: one record per OCR region with non-empty text, including OCR engine, confidence when available, fallback state, and bounding box metadata when available.
- `table`: one record per detected table, with text built from table caption/title/text plus rows/cells.
- `image`: one record per embedded image with metadata-only text. This supports discovery that a page is image-only, but it is not a substitute for OCR text.

Current schema:

- `search_index.jsonl` uses `schema_version=pdfrejuvenator.search.v0.3`.
- Each record must include `record_id`, `book_id`, `source_pdf_sha256`, `page`, `page_id`, `record_type`, `text`, `artifact_path`, and `metadata`.
- `search_manifest.json` must report `status=PASS`, `record_count`, `record_counts`, and local/private privacy flags.

User-facing behavior:

- `python -m pdfrejuvenator search "<query>" --output-dir "<consolidated output>"` searches record `text`, `record_type`, and selected metadata classifications.
- Search output must identify page number, record type, score, artifact path, and a short snippet.
- OCR proof requires real `ocr_text` records. `image` records alone do not prove scanned text searchability.
- Table proof requires real `table` records with searchable cell/row text and at least one table-scoped query hit. OCR text that happens to include table-like words is useful but does not prove structured table searchability.

Privacy and path leakage:

- `_search` is local/private and may contain extracted text and internal source references.
- User-facing files at the consolidated output root must not expose internal absolute paths except through `_debug` files.
- `manifest.csv`, `dashboard.html`, `README.md`, and validation reports are treated as user-facing for leakage checks.

## Acceptance Gates

Minimum v0.3.1 GitHub readiness gates:

1. Source validation passes.
2. Search validator passes against a normal text/table sample requiring `page`, `text_region`, and `table` records.
3. Search validator passes against a private scanned-validation proof requiring `page`, `ocr_text`, and `table` records.
4. The private scanned-validation proof includes pages 1-5 and at least one representative scanned table-like page with a real `table` record, non-empty table text, and a table-scoped query hit.
5. Query probes return page-level and OCR/table-level hits for known local-only validation terms.
6. User-facing consolidated output files have no internal absolute path leakage.

## Repeatable Validation Commands

Source checks:

```powershell
python scripts\validate_pdfrejuvenator.py
python -m ruff check --no-cache pdfrejuvenator scripts src
```

Search output checks:

```powershell
python scripts\validate_searchability.py `
  --output-dir "G:\path\to\source_pdfrejuvenator_output" `
  --require-record-type page `
  --require-record-type text_region `
  --require-record-type table `
  --require-nonempty-table-text `
  --query "known sample table term" `
  --query-record-type table="known sample table term" `
  --check-user-facing-paths `
  --report "G:\path\to\evidence\searchability_validation.json"
```

Private scanned/OCR proof:

```powershell
$sourcePdf = "<local scanned validation PDF>"
$outputDir = "<local scanned validation output directory>"
$evidenceDir = "<local evidence directory>"

python -m pdfrejuvenator process `
  $sourcePdf `
  --pages "1-5" `
  --ocr-engine rapidocr `
  --clean `
  --force-rollout `
  --validation-mode external

python scripts\validate_searchability.py `
  --output-dir $outputDir `
  --require-record-type page `
  --require-record-type ocr_text `
  --require-record-type table `
  --min-record-type ocr_text=1 `
  --min-record-type table=1 `
  --require-nonempty-page-text `
  --require-nonempty-table-text `
  --check-user-facing-paths `
  --report "$evidenceDir\scanned_pages_001_005_searchability_validation.json"
```

## Current Risk

The private validation source is scanned/image-only. Pages 1-5 prove OCR searchability only if RapidOCR produces `ocr_text` records and page aggregates include that OCR text. They do not prove structured table searchability unless `table` records are generated from a representative scanned table page. If scanned validation artifacts contain no table records, v0.3.1 GitHub readiness remains not ready until OCR-to-table reconstruction produces searchable table records or Default approves a release-scope change that explicitly excludes scanned structured table search.

## v0.3.1 Table Search Blocker Design

Current table search records are generated from page manifest `tables` entries. Those entries come from PDF table extraction and text-block heuristics. Scanned validation pages currently produce `ocr_text` records but no `table` records, so the missing capability is not search indexing; it is OCR-to-table reconstruction before indexing.

Smallest implementation path:

1. Group OCR boxes by page into line rows using y-axis overlap/tolerance.
2. Detect table candidates using repeated column-like x positions, numeric/stat density, and row count.
3. Emit page manifest `tables` records with `source=ocr_table_reconstruction`, `rows`, `bbox_points`, `classification`, and confidence.
4. Reuse `scripts/build_local_search_index.py` to generate searchable `table` records from those manifest tables.
5. Validate with `--require-record-type table`, `--require-nonempty-table-text`, and `--query-record-type table=<known local validation term>`.
