from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_search import write_jsonl  # noqa: E402
from pdfrejuvenator.vector_index import (  # noqa: E402
    DeterministicHashEmbeddingProvider,
    VECTOR_INDEX_SCHEMA_VERSION,
    build_vector_index,
    build_vector_index_payload,
    search_record_to_vector_chunks,
    search_vector_index,
    validate_vector_index_payload,
    validate_vector_index_source,
)


def synthetic_search_records() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "pdfrejuvenator.corpus_search.v0.4",
            "record_id": "synthetic-corpus::synthetic-book::p001::text",
            "batch_id": "synthetic-corpus",
            "book_id": "synthetic-book",
            "record_type": "synthetic_text",
            "text": "Synthetic beacon archive text for deterministic vector search.",
            "page": 1,
            "artifact_path": "synthetic/page-001.svg",
            "metadata": {
                "privacy_scope": "public_safe_fixture",
                "section": "synthetic vector fixture",
            },
        },
        {
            "schema_version": "pdfrejuvenator.corpus_search.v0.4",
            "record_id": "synthetic-corpus::synthetic-book::p002::text",
            "batch_id": "synthetic-corpus",
            "book_id": "synthetic-book",
            "record_type": "synthetic_text",
            "text": "Public-safe table notes mention index rebuild behavior.",
            "page": 2,
            "artifact_path": "synthetic/page-002.svg",
            "metadata": {
                "privacy_scope": "public_safe_fixture",
                "section": "synthetic rebuild fixture",
            },
        },
    ]


def run_checks() -> list[tuple[str, bool, str]]:
    provider = DeterministicHashEmbeddingProvider(dimensions=16)
    chunks = search_record_to_vector_chunks(synthetic_search_records()[0], max_chars=32)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        search_index = root / "search_index.jsonl"
        vector_index = root / "vector_index.json"
        write_jsonl(search_index, synthetic_search_records())
        payload = build_vector_index_payload(search_index, provider=provider, max_chars=96)
        count = build_vector_index(search_index, vector_index, provider=provider, max_chars=96)
        loaded = json.loads(vector_index.read_text(encoding="utf-8"))
        issues = validate_vector_index_payload(loaded)
        source_issues = validate_vector_index_source(loaded)
        results = search_vector_index(vector_index, "beacon vector archive", provider=provider, limit=1)
        search_index.write_text(search_index.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        stale_issues = validate_vector_index_source(loaded)
    return [
        ("schema version", payload.get("schema_version") == VECTOR_INDEX_SCHEMA_VERSION, ""),
        ("provider dimensions", payload.get("embedding_provider", {}).get("dimensions") == 16, ""),
        ("chunk generation", len(chunks) >= 1, ""),
        ("vector index count", count == len(payload.get("chunks", [])) == 2, ""),
        ("source record count", payload.get("source_index", {}).get("record_count") == 2, ""),
        ("validation issues", issues == [], "; ".join(issues)),
        ("source validation issues", source_issues == [], "; ".join(source_issues)),
        ("stale source detection", stale_issues != [], "source mutation should require rebuild"),
        ("search result count", len(results) == 1, ""),
        ("search result source", results[0].get("source_record_id") == "synthetic-corpus::synthetic-book::p001::text", ""),
        ("search result metadata", results[0].get("metadata", {}).get("privacy_scope") == "public_safe_fixture", ""),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"VECTOR INDEX SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
