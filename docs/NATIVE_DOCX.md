# Native Word conversion

Run `python -m pdfrejuvenator convert-docx INPUT.pdf --output-root /path/to/private/new-run`.

The output directory must be new, outside any Git repository and outside Clairvoyance directories. It contains document.docx, extracted image assets and a hash receipt. Keep inputs, outputs, corrections, source text, source fonts, screenshots and comparisons outside the repository.

The deterministic converter retains native editable text, source-font size signals, geometry-based left/right reading order, separate image placements, and composite scan layers. Dense prose uses ordinary paragraphs to permit reflow. Explicit coordinate grids emit every detected row without a fixed row cap.

Optional `--pages 1-4,8` selects one-based source pages. Optional `--corrections /private/rules.json` accepts a private JSON object with `sourceSha256` and `pages` keyed by page number. Each page rule can declare `columnBounds`, `rowTolerance`, `headerTextRegions`, `catalogRegions`, `footerTextRegions`, `excludeTextRegions`, `replacements`, `includeXrefs`, `excludeXrefs`, and `compositeRegions`. Coordinates use PDF points. A mismatched source hash fails before output is created.

No source-specific text, templates, manifests, inventories, font files or corrections are bundled. Source-specific forms and numeric reference reconstructions are excluded. This command does not run OCR or model inference. Raster-only text remains an image and is flagged in the receipt. Word reflows content; pixel parity and complete semantic recovery are not guaranteed. PDF rendering and source/output visual review remain separate tasks.

## Publication review

Build into a fresh directory outside the repository using scripts/build_public_source_export.py. Run scripts/scrub_public_export.py on that export with an external private denylist. The scrubber rejects unapproved binary assets and checks text and PDF text; it cannot establish ownership of arbitrary prose or text embedded in images.

Before committing or pushing, manually review the entire proposed diff, file list, sample provenance, generated export and every outgoing commit relative to the remote base. Scan with the private denylist kept outside the repo. Do not include private findings, excerpts, local paths or the denylist in commits, PR text, attachments, screenshots or CI logs. A scrub pass is a screening result, not publication approval.
