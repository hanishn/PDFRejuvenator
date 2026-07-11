# PDFRejuvenator Private Workspace Architecture

Version: 0.5.0
Revision: 2026-07-11 private workspace foundation

PDFRejuvenator v0.5 introduces a private local workspace boundary for scanned-document corpus processing. The workspace is for source PDFs and derived local processing artifacts that must not be included in public release packages.

## Workspace Layout

The private workspace initializer creates this layout:

```text
source_private/
manifests/
derived/ocr/
derived/tables/
derived/images/
indexes/
evidence/
pdfrejuvenator_private_workspace.json
.gitignore
```

The workspace `.gitignore` ignores private artifacts by default. The config file records the layout version, workspace root, corpus id, release scope, and relative artifact paths.

## Commands

Initialize a private workspace:

```bash
python -m pdfrejuvenator init-private-workspace G:\PrivateCorpus\PDFRejuvenator --corpus-id private-corpus
```

Validate a private workspace:

```bash
python -m pdfrejuvenator validate-private-workspace G:\PrivateCorpus\PDFRejuvenator --public-repo-root G:\PublicRepos\PDFRejuvenator
```

## Release Boundary

The private workspace config is explicitly marked:

```text
public_export_allowed: false
release_scope: private_local_only
```

Validation fails if the private workspace is inside the public repository. This is a release-blocking control.

## Validation

The dedicated validator is:

```bash
python scripts\validate_private_workspace.py
```

The baseline validator also runs the private workspace checks:

```bash
python scripts\validate_pdfrejuvenator.py
```

## Public Documentation Rule

Public documentation must describe private corpora generically. Do not put private source titles, extracted source text, proprietary tables, or proprietary image content in public code, public docs, release notes, package metadata, or GitHub release text.
