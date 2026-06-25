# PDFRejuvenator Publication Guide

## Current Rule

Do not publish the working project tree directly.

The working tree contains private regression fixtures, historical scripts, local output references, and internal reports. Use the public-source export script before creating a GitHub project.

## Build Public Source Export

Run from the working project root:

```powershell
python scripts\build_public_source_export.py --output-dir "<export-folder>" --clean
```

The export includes:

- `.github\` issue, pull request, and validation workflow files
- `CONTRIBUTING.md`
- `LICENSE`
- `pyproject.toml`
- `pdfrejuvenator\`
- `src\`
- `samples\shadow_power_play_sample.pdf`
- selected public runtime scripts under `scripts\`
- public docs under `docs\`
- command-line wrappers
- runtime requirements
- `.gitignore`

The export excludes:

- private PDFs
- `source_pdfs\`
- generated `outputs\`
- private fixture configs
- legacy branded regression scripts
- internal planning reports

## Validation

Run from the exported tree:

```powershell
python scripts\validate_pdfrejuvenator.py
```

Run a reference scan before using the export as a GitHub source:

```powershell
python scripts\scrub_public_export.py
```

Expected result:

```text
findings=0
```

## Public Release Decisions

Current public repository decisions:

- Repository name: `PDFRejuvenator`.
- Repository description: `Convert PDFs into editable SVG review packets.`
- License: Apache License 2.0.
- Copyright holder: Nathan Hanish.
- Public fixture: synthetic sample PDF `samples\shadow_power_play_sample.pdf`.
- Windows batch wrappers stay in the repository root for v0.3.
- GitHub Pages is deferred; v0.3 is README-first.
- Private regression PDFs stay outside the repository.
- Local validation and GitHub Actions validation must pass before and after publishing.

Current license decision:

- Apache License 2.0.
- Copyright 2026 Nathan Hanish.
- This public version is open source; later commercial versions, hosted services, support offerings, or packaged products may have separate terms.

Current public fixture decision:

- Include a synthetic sample PDF: `samples\shadow_power_play_sample.pdf`.
- The sample is original placeholder tabletop adventure material generated from `scripts\generate_public_sample_pdf.py`.
- The scrub gate scans PDF text as well as source files.

The project now exposes a `dev` install extra for validation tooling:

```powershell
python -m pip install -e .[dev]
python scripts\validate_pdfrejuvenator.py
python scripts\scrub_public_export.py
python -m ruff check --no-cache pdfrejuvenator scripts src
```
