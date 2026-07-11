# PDFRejuvenator Private OCR Records

Version: 0.5.0
Revision: 2026-07-11 private OCR records foundation

PDFRejuvenator v0.5 adds page-level OCR records for private local corpus processing. OCR records are written only inside a validated private workspace.

## Record Fields

Each page record contains:

- schema version
- corpus id
- book id
- source SHA-256
- page number
- extraction method
- OCR text
- OCR text SHA-256
- character count
- confidence value

The OCR text field is private local data. Do not place OCR record files in public release artifacts unless the source and extracted text are separately cleared for public release.

## Command

Extract OCR records from an intake manifest:

```powershell
python -m pdfrejuvenator extract-ocr-records ".\manifest.json" --source-root ".\samples" --private-workspace-root "G:\PrivateCorpus\PDFRejuvenator" --output "G:\PrivateCorpus\PDFRejuvenator\derived\ocr\ocr_records.json"
```

The command validates the private workspace before writing output.

## Validation

Run the focused validator:

```powershell
python scripts\validate_ocr_records.py
```

The baseline validator includes the OCR record checks:

```powershell
python scripts\validate_pdfrejuvenator.py
```

## OCR Search Index

Build a private local search index from OCR records:

```powershell
python -m pdfrejuvenator index-ocr-records "G:\PrivateCorpus\PDFRejuvenator\derived\ocr\ocr_records.json" --output "G:\PrivateCorpus\PDFRejuvenator\indexes\ocr_index.jsonl"
```

Run the OCR search validator:

```powershell
python scripts\validate_ocr_search.py
```

## Release Boundary

Public release artifacts may include schema, validators, and generic documentation. Public release artifacts must not include private OCR text, private source titles, proprietary tables, proprietary image content, or private workspace artifacts.
