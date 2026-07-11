# PDFRejuvenator v0.4.0 Corpus Intake Architecture

## Scope

This document defines the v0.4.0 private large-book corpus intake foundation. The intake layer registers source files, records source metadata, applies privacy and rights gates, and creates evidence before extraction or indexing work starts.

This document does not approve OCR extraction from copyrighted material, embeddings, public release actions, or external sharing.

## Registry Entry

Each source document is represented by one registry entry.

Required fields:

- `corpus_id`: stable corpus identifier.
- `book_id`: stable internal source identifier.
- `display_name`: public-safe label for local review.
- `source_path`: local source reference.
- `sha256`: source file hash.
- `file_size_bytes`: source file size.
- `page_count`: known page count or null.
- `privacy_class`: `public_sample`, `private_source`, or `restricted_source`.
- `rights_class`: `original`, `licensed_private`, or `unknown_review_required`.
- `intake_state`: current intake state.
- `processing_intent`: allowed processing intent.
- `created_at` and `updated_at`: UTC timestamps.
- `evidence_paths`: local evidence references.
- `blocked_reason`: required when the entry is blocked.

## Intake States

Allowed states:

- `registered`: source is known but not approved for processing.
- `blocked`: source cannot proceed until a recorded issue is resolved.
- `ready_for_probe`: source is approved for metadata or structural probe.
- `ready_for_ocr`: source is approved for OCR processing.
- `processed`: approved processing completed.
- `failed`: processing failed and needs review.
- `quarantined`: source is isolated from release or export paths.

## Processing Intent

Allowed intents:

- `inventory_only`: metadata and hash capture only.
- `structure_probe`: page count, dimensions, and structural metadata only.
- `ocr_pending_approval`: OCR is not approved.
- `ocr_approved_private`: OCR is approved for local private use only.

Private OCR requires a separate recorded approval gate. The default state for private corpus work is inventory-only.

## Manifest

Each batch produces an ingestion manifest with:

- `manifest_version`: `0.4.0-intake-v1`.
- `batch_id`: stable batch identifier.
- `generated_at`: UTC timestamp.
- `entries`: registry entries for the batch.

The manifest is evidence. It must be stored in a private project-owned location when it references private source files.

## Privacy And Rights Gates

Required gates:

- Private source titles and branded corpus names must not appear in public code, public docs, release notes, package metadata, GitHub releases, or public-facing files.
- Public-safe artifacts must use generic language such as `private scanned RPG corpus`, `private large-book corpus`, or `private test corpus`.
- Copyrighted source text must not be quoted in reports, logs, release notes, public docs, or public-facing files.
- Source PDFs must not be placed in public export trees unless they are explicit public sample fixtures.
- Embeddings require a separate privacy/model approval.
- OCR extraction from copyrighted material requires a separate recorded approval.

## Inventory Workflow

The 200+ book inventory workflow should:

1. Walk only approved private source roots.
2. Record file path, size, hash, and page count.
3. Detect duplicate hashes.
4. Assign default `inventory_only` processing intent.
5. Mark unknown or restricted material as blocked.
6. Write manifest and evidence in a private project-owned location.
7. Run the private/public scrub gate before any public-facing report or release action.

## Validation

Run:

```powershell
python scripts\validate_corpus_intake.py
```

Expected result:

```text
CORPUS INTAKE SUMMARY: checks=10 failures=0
```

The validator checks synthetic registry entries, manifest serialization, blocked-entry requirements, duplicate hash detection, the private OCR approval gate, and inventory-only manifest generation against the public sample fixture.

## Inventory Command

Run:

```powershell
python -m pdfrejuvenator inventory ".\samples" --output ".\local_inventory_manifest.json" --privacy-class public_sample --rights-class original
```

The command scans a source root for PDFs and writes a v0.4 intake manifest. Private corpus runs should write manifests to private project-owned output paths, not public release trees.

## Manifest Search Index

Run:

```powershell
python -m pdfrejuvenator index-manifest ".\local_inventory_manifest.json" --output ".\local_inventory_index.jsonl"
```

The command writes a JSONL search index from manifest metadata. This index contains inventory metadata only. It does not extract source text.

## Synthetic Text Search Records

Run:

```powershell
python -m pdfrejuvenator index-text-records ".\synthetic_text_records.json" --output ".\synthetic_text_index.jsonl"
```

The command writes a JSONL search index from synthetic or separately approved text records. It does not run OCR and does not extract source text from PDFs.

## Synthetic Table And Image Metadata Search

Run:

```powershell
python -m pdfrejuvenator index-table-records ".\synthetic_table_records.json" --output ".\synthetic_table_index.jsonl"
python -m pdfrejuvenator index-image-records ".\synthetic_image_records.json" --output ".\synthetic_image_index.jsonl"
```

These commands write JSONL search indexes from synthetic or separately approved metadata records. They do not extract tables or images from copyrighted source PDFs.
