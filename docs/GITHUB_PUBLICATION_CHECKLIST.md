# GitHub Publication Checklist

Repository name:

```text
PDFRejuvenator
```

Repository description:

```text
Convert PDFs into editable SVG review packets.
```

## Before Creating The Repository

- Use the clean public export directory, not the working project tree.
- Create the GitHub repository as public when ready.
- Do not initialize the GitHub repository with README, license, or `.gitignore`; this export already contains them.
- Do not enable GitHub Pages for v0.3.

## Local Verification

Run from the clean export directory:

```powershell
python scripts\validate_pdfrejuvenator.py
python -m ruff check --no-cache pdfrejuvenator scripts src
python scripts\scrub_public_export.py
python -m pdfrejuvenator --help
```

Expected:

```text
failures=0
All checks passed!
findings=0
```

## First Commit

```powershell
git init
git status
python scripts\scrub_public_export.py
git add .
git commit -m "Initial PDFRejuvenator v0.3 public release"
git branch -M main
git remote add origin <public-github-repo-url>
git push -u origin main
```

## First GitHub Checks

- Confirm GitHub Actions validation passes.
- Confirm the README shows the sample command.
- Confirm `LICENSE` displays Apache License 2.0.
- Confirm no generated output directories were pushed.
- Confirm `samples\shadow_power_play_sample.pdf` is present.
