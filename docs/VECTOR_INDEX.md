# PDFRejuvenator Vector Index Contract

Version: 0.5 draft
Revision: vector-index-contract-20260713

PDFRejuvenator v0.5 adds a local vector index that can be built from an existing
JSONL corpus search index. The vector index is a local retrieval artifact for
future RAG workflows. It is not a public corpus, and it must not contain private
source data in committed fixtures or public package artifacts.

## File Format

The vector index is a JSON object with schema version:

```text
pdfrejuvenator.vector_index.v0.5
```

Top-level fields:

- `schema_version`: vector index schema identifier.
- `source_index`: path, SHA-256 digest, and record count for the input search index.
- `embedding_provider`: provider, model, dimension count, and fingerprint.
- `chunking`: chunk strategy and maximum character count.
- `chunk_count`: number of embedded chunks.
- `chunks`: embedded retrieval chunks.

Each chunk uses schema version:

```text
pdfrejuvenator.vector_chunk.v0.5
```

Chunk fields:

- `chunk_id`: stable chunk identifier derived from the source record id.
- `chunk_index`: zero-based index within the source record.
- `source_record_id`: original search index record id.
- `source_schema_version`: original search index schema version.
- `record_type`: original record type.
- `text`: retrieval text for this chunk.
- `page`: source page number when available.
- `artifact_path`: source artifact path when available.
- `metadata`: source metadata copied from the search record.
- `embedding`: numeric vector with the provider's configured dimensions.

## Provider Contract

The first implementation includes a deterministic hash provider for tests,
offline smoke checks, and public-safe fixtures. The provider is not intended to
be semantically strong. It gives stable vectors without network access or
credentials, which lets validators and command-line workflows run anywhere.

Future provider adapters must record:

- provider name
- model name
- vector dimensions
- model/configuration fingerprint

Indexes built with different provider fingerprints are separate artifacts and
should be rebuilt rather than mixed.

## Privacy Boundary

Vector indexes inherit the privacy scope of their source search index. Private
OCR, table, image, or text records remain private local artifacts. Public test
fixtures must use synthetic content only.

Public release checks must scan docs, handoffs, package exports, and generated
artifacts for private corpus strings before GitHub promotion.
