# PDFRejuvenator Validation Guide

## Baseline Project Gate

Run from the project or package root:

```powershell
python scripts\validate_pdfrejuvenator.py
```

This gate compiles Python files, checks required runtime modules, checks optional dev tools, and imports core scripts.

Current expected development warnings:

```text
pytest not importable
ruff not importable
```

Those warnings mean the local dev lint/test tools are not installed. Runtime validation still fails on actual import or syntax errors.

## Process Validation Modes

Internal mode fails hard:

```powershell
python -m pdfrejuvenator process "G:\path\to\source.pdf" --pages "1-5" --clean --force-rollout --validation-mode internal
```

Use internal mode during development and private testing. Missing previews, invalid SVG, broken dashboard links, or bad manifest rows should stop the run.

External mode keeps output and labels problems:

```powershell
python -m pdfrejuvenator process "G:\path\to\source.pdf" --pages "1-5" --clean --force-rollout --validation-mode external
```

Use external mode for noisy user PDFs where partial output is still useful. It writes validation reports and labels failed pages instead of throwing away the whole run.

## Consolidated Output Gate

Validate an existing output folder:

```powershell
python scripts\validate_consolidated_review_output.py "G:\path\to\source_pdfrejuvenator_output" --mode internal
```

The validator checks:

- `manifest.csv` exists and has rows.
- Manifest page rows are `PASS`.
- Editable SVG files exist, parse as XML, and contain editable text nodes.
- Preview PNG files exist and can be opened.
- `dashboard.html` links resolve inside the output folder.
- `README.md` exists.
- `_debug` exists.

External validation additionally writes:

```text
validation_report.json
validation_report.csv
```

and augments:

```text
manifest.csv
dashboard.html
```

with validation status labels.
