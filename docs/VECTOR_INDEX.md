# PDFRejuvenator Vector Index Contract

Version: 0.6 draft
Revision: vector-index-contract-20260717

PDFRejuvenator v0.6 extends the local vector index that can be built from an existing
JSONL corpus search index. The vector index is a local retrieval artifact for
future RAG workflows. It is not a public corpus, and it must not contain private
source data in committed fixtures or public package artifacts.

## File Format

The vector index is a JSON object with schema version:

```text
pdfrejuvenator.vector_index.v0.6
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
pdfrejuvenator.vector_chunk.v0.6
```

Chunk fields:

- `chunk_id`: stable chunk identifier derived from the source record id.
- `chunk_index`: zero-based index within the source record.
- `chunk_sha256`: SHA-256 digest of the chunk text.
- `source_record_id`: original search index record id.
- `source_schema_version`: original search index schema version.
- `record_type`: original record type.
- `text`: retrieval text for this chunk.
- `page`: source page number when available.
- `artifact_path`: source artifact path when available.
- `metadata`: source metadata copied from the search record.
- `embedding`: numeric vector with the provider's configured dimensions.

## Provider Contract

The default provider is `deterministic-test`, a deterministic hash provider for tests,
offline smoke checks, and public-safe fixtures. The provider is not intended to
be semantically strong. It gives stable vectors without network access or
credentials, which lets validators and command-line workflows run anywhere.

The v0.6 semantic provider is `ollama`. It calls a local Ollama server through
`/api/embed` and records the Ollama model name, vector dimensions, and provider
fingerprint in the index. Ollama indexes are local artifacts and are intended
for private on-machine retrieval tests. Public fixtures and committed examples
must remain synthetic.

Future provider adapters must record:

- provider name
- model name
- vector dimensions
- model/configuration fingerprint

Indexes built with different provider fingerprints are separate artifacts and
should be rebuilt rather than mixed.

The command line exposes provider selection and compatibility checks:

```powershell
python -m pdfrejuvenator list-embedding-providers
python -m pdfrejuvenator build-vector-index search_index.jsonl --output vector_index.json --provider deterministic-test
python -m pdfrejuvenator build-vector-index private_search_index.jsonl --output private_vector_index.json --provider ollama --model nomic-embed-text
python -m pdfrejuvenator build-vector-index private_search_index.jsonl --output private_vector_index_redacted.json --provider ollama --model nomic-embed-text --omit-text
python -m pdfrejuvenator validate-vector-index vector_index.json --provider deterministic-test
python -m pdfrejuvenator validate-vector-index private_vector_index.json --provider ollama
python -m pdfrejuvenator inspect-vector-index vector_index.json
python -m pdfrejuvenator vector-search private_vector_index.json "query text" --provider ollama --model nomic-embed-text --hide-text
```

## Chunking Controls

The v0.6 index records chunk size and optional character overlap:

- `max_chars`: maximum retrieval text per chunk.
- `overlap_chars`: optional overlap carried into the next chunk.

The validator checks chunk counts, chunk schemas, embedding dimensions, chunk
text hashes, provider metadata, and source-index staleness.

Use `vector-search --hide-text` for private review evidence when matched text
should not be copied into logs or handoff files.

Use `build-vector-index --omit-text` when a private vector index should retain
embeddings, source ids, metadata, and chunk hashes without retaining copied
chunk text. Redacted indexes still require local-only handling because
embeddings and metadata remain derived private artifacts.

## Privacy Boundary

Vector indexes inherit the privacy scope of their source search index. Private
OCR, table, image, or text records remain private local artifacts. Public test
fixtures must use synthetic content only.

Generated vector indexes, vector search result logs, private coverage matrices,
and private boundary manifests are runtime artifacts. Keep those files in local
evidence or private workspace folders. Do not include them in public source
exports, package exports, committed fixtures, release notes, or public review
surfaces.

The validator treats common runtime artifact names such as vector index JSON
files, search result JSONL files, and coverage matrix JSON files as local-only
artifacts. Public exports may include vector index code, validators, and docs,
but not generated private index or retrieval evidence files.

Public release checks must scan docs, handoffs, package exports, and generated
artifacts for private corpus strings before GitHub promotion.
