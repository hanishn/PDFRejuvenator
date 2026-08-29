# Answer Query

PDFRejuvenator v0.7 adds local evidence-based answer packets on top of the v0.6 vector index.

## Capability

`answer-query` retrieves ranked vector evidence for a question, then emits a citation-validated JSON answer.

Two modes are available:

- `--no-generate`: retrieval-only answer packet. This does not call a language model.
- `--answer-provider ollama`: local Ollama chat answer generation constrained to retrieved evidence.

## Retrieval-Only Packet

```bat
python -m pdfrejuvenator answer-query vector_index.json "Who validates the bridge?" --provider deterministic-test --no-generate --output answer_query.json --evidence-output answer_query_evidence.jsonl
```

The output JSON uses schema `pdfrejuvenator.answer_query.v0.7`.

## Local Ollama Answering

```bat
python -m pdfrejuvenator answer-query vector_index.json "Who validates the bridge?" --provider ollama --model nomic-embed-text --answer-provider ollama --answer-model llama3.1 --output answer_query.json --evidence-output answer_query_evidence.jsonl
```

The command fails closed when:

- retrieved evidence is invalid;
- the answer provider returns invalid JSON;
- a citation references a chunk outside the retrieved evidence;
- a sufficient-evidence answer has no citations.

## Privacy Boundary

Generated answer outputs and retrieved evidence JSONL files are local runtime artifacts. Do not include them in public source exports, package exports, release notes, or public evidence packets when they reference private corpora.

Use `--hide-evidence-text` with `--no-generate` when the saved evidence file must retain citation metadata without copied source text. Generated answers require evidence text and therefore reject `--hide-evidence-text`.

## Validation

Validate an answer packet against its retrieved evidence:

```bat
python scripts\validate_answer_query.py answer_query.json answer_query_evidence.jsonl
```

Run the Playwright command-level suite:

```bat
npx playwright test
```
