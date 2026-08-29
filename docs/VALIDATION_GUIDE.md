# PDFRejuvenator Validation Guide

## Baseline Project Gate

Run from the project or package root:

```powershell
python scripts\validate_pdfrejuvenator.py
```

This gate compiles Python files, checks required runtime modules, checks optional dev tools, and imports core scripts.

## Release-Review Summary Gate

Validate a v0.6 machine-readable release-review summary before using it as a
human review or source-control evidence artifact:

```powershell
python scripts\validate_release_review_summary.py "G:\path\to\v060_release_review_summary.json" --check-paths
```

The validator checks required capability, validation, private-data boundary,
coverage-limit, protected-action, and path-existence fields. Its negative
controls reject private runtime vector artifact paths in public export fields,
stored or emitted text in privacy smoke evidence, missing scrub evidence, and
stale vector validation evidence.

## Export Manifest Gate

Validate staged public/package exports before source-control review:

```powershell
python scripts\validate_export_manifest.py "G:\path\to\public_source_export" "G:\path\to\package_export"
```

The validator checks that public/package exports contain the release-summary
validator and do not contain generated private vector indexes, vector-search
logs, private coverage manifests, bytecode files, or cache directories.

## Coverage Boundary Gate

Validate a bounded private coverage boundary manifest before treating private
real-data Ollama evidence as release-review support:

```powershell
python scripts\validate_coverage_boundary.py "G:\path\to\coverage_boundary.json" --check-paths
```

The validator requires the manifest to identify bounded, non-exhaustive,
local-only coverage; preserve the protected source-control/publication
boundary; record the Ollama provider/model/dimensions; and report zero build,
validation, inspection, and search failures.

Validate private coverage matrix rows:

```powershell
python scripts\validate_private_coverage_matrix.py "G:\path\to\coverage_matrix.json" --check-paths
python scripts\validate_private_coverage_matrix.py "G:\path\to\omit_hide_matrix.json" --check-paths --require-redacted
```

The matrix validator checks row count, unique IDs, zero command failures,
expected embedding dimensions, positive chunk/search counts, referenced paths
when requested, and zero text-field matches for omit-text/hide-text evidence.

Validate bounded coverage adequacy and representativeness:

```powershell
python scripts\validate_coverage_adequacy.py "G:\path\to\coverage_adequacy.json" --check-paths
```

The adequacy validator checks that the evidence remains explicitly bounded and
non-exhaustive while covering required strata such as contiguous multi-page
slices, early/middle/late single-page slices, multi-chunk records, single-chunk
records, and omit-text/hide-text redaction evidence.

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
