# Contributing

## Current Project Stage

PDFRejuvenator is in v0.3 internal/private staging.

The public source export intentionally excludes private PDFs, private regression fixtures, generated outputs, and legacy branded test scripts.

## Local Validation

Run before proposing changes:

```powershell
python scripts\validate_pdfrejuvenator.py
```

Expected local development warnings may include:

```text
pytest not importable
ruff not importable
```

Runtime import or syntax failures are not acceptable.

## Private Inputs

Do not commit:

- source PDFs;
- generated review output;
- extracted text indexes from private PDFs;
- private fixture configs;
- local absolute source paths.

## Public Fixtures

Public fixture strategy is not decided yet. Use synthetic or explicitly cleared inputs only.

## Pull Requests

Each pull request should include:

- user-visible behavior changed;
- files changed;
- validation commands run;
- generated artifacts inspected, if any;
- known limitations or skipped checks.
