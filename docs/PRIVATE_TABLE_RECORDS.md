# PDFRejuvenator Private Table Records

Version: 0.5.0
Revision: 2026-07-11 private table records foundation

PDFRejuvenator v0.5 adds a normalized table record schema for private local corpus processing. The schema supports deterministic validation and local search indexing without making private table artifacts public.

## Record Fields

Each table record contains:

- schema version
- corpus id
- book id
- source SHA-256
- page number
- table id
- caption
- normalized cells
- confidence value
- extraction method

Rows are normalized to a consistent width. Cell values are stored as strings.

## Validation

Run the focused validator:

```powershell
python scripts\validate_table_records.py
```

The baseline validator includes table record checks:

```powershell
python scripts\validate_pdfrejuvenator.py
```

## Search

The existing table index command accepts synthetic/public-safe table records and v0.5 private table records:

```powershell
python -m pdfrejuvenator index-table-records "G:\PrivateCorpus\PDFRejuvenator\derived\tables\table_records.json" --output "G:\PrivateCorpus\PDFRejuvenator\indexes\table_index.jsonl"
```

## Release Boundary

Public release artifacts may include schema, validators, and generic documentation. Public release artifacts must not include private source titles, private table payloads, extracted private text, proprietary image content, or private workspace artifacts.
