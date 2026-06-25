# PDFRejuvenator Output Guide

## Start Here

Open:

```text
dashboard.html
```

The dashboard links to each page preview and editable SVG.

## File To Edit

For each page, edit:

```text
pages\page_###_edit_this_page.svg
```

Example:

```text
pages\page_005_edit_this_page.svg
```

The preview image beside it is:

```text
pages\page_###_preview.png
```

## Manifest

The main page list is:

```text
manifest.csv
```

It records each page, output status, editable SVG path, preview PNG path, validation status, and validation errors if any.

## Search Data

Local search data is stored separately from review files:

```text
_search\search_index.jsonl
_search\search_manifest.json
```

The search index contains extracted text and page/image/table metadata from the source PDF. Treat it as local/private data unless the source PDF and extracted text are cleared for sharing.

Search command:

```powershell
python -m pdfrejuvenator search "search terms" --output-dir "G:\path\to\source_pdfrejuvenator_output"
```

## Internal Files

Debug pointers are stored here:

```text
_debug\
```

Normal reviewers should not need `_debug` unless a page fails validation or a developer asks for the internal run root.
