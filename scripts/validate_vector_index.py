from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_search import write_jsonl  # noqa: E402
from pdfrejuvenator.vector_index import (  # noqa: E402
    DeterministicHashEmbeddingProvider,
    VECTOR_INDEX_SCHEMA_VERSION,
    build_vector_index,
    build_vector_index_payload,
    create_embedding_provider,
    inspect_vector_index_payload,
    list_embedding_providers,
    search_record_to_vector_chunks,
    search_vector_index,
    serialize_vector_search_results,
    validate_vector_index_payload,
    validate_vector_index_provider,
    validate_vector_index_source,
)


PRIVATE_VECTOR_RUNTIME_PATTERNS = (
    "*/coverage_matrix.json",
    "*/coverage_boundary.json",
    "*/private_index_boundary.json",
    "*/search_results*.jsonl",
    "*/*vector_index*.json",
)


def is_private_runtime_vector_artifact(path: str | Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(fnmatchcase(normalized, pattern) for pattern in PRIVATE_VECTOR_RUNTIME_PATTERNS)


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
    chunks = search_record_to_vector_chunks(synthetic_search_records()[0], max_chars=32, overlap_chars=8)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        search_index = root / "search_index.jsonl"
        vector_index = root / "vector_index.json"
        redacted_vector_index = root / "vector_index_redacted.json"
        write_jsonl(search_index, synthetic_search_records())
        payload = build_vector_index_payload(search_index, provider=provider, max_chars=96, overlap_chars=12)
        count = build_vector_index(search_index, vector_index, provider=provider, max_chars=96, overlap_chars=12)
        redacted_count = build_vector_index(
            search_index,
            redacted_vector_index,
            provider=provider,
            max_chars=96,
            overlap_chars=12,
            include_text=False,
        )
        loaded = json.loads(vector_index.read_text(encoding="utf-8"))
        redacted_loaded = json.loads(redacted_vector_index.read_text(encoding="utf-8"))
        issues = validate_vector_index_payload(loaded)
        redacted_issues = validate_vector_index_payload(redacted_loaded)
        source_issues = validate_vector_index_source(loaded)
        results = search_vector_index(vector_index, "beacon vector archive", provider=provider, limit=1)
        redacted_results = search_vector_index(redacted_vector_index, "beacon vector archive", provider=provider, limit=1)
        result_payloads = serialize_vector_search_results(results)
        redacted_result_payloads = serialize_vector_search_results(redacted_results, hide_text=True)
        threshold_results = search_vector_index(
            vector_index,
            "beacon vector archive",
            provider=provider,
            limit=1,
            min_score=-1.0,
        )
        provider_issues = validate_vector_index_provider(loaded, provider)
        mismatch_provider = create_embedding_provider("deterministic-test", dimensions=8)
        mismatch_issues = validate_vector_index_provider(loaded, mismatch_provider)
        inspection = inspect_vector_index_payload(loaded)
        hidden_text_command = subprocess.run(
            [
                sys.executable,
                "-m",
                "pdfrejuvenator",
                "vector-search",
                str(vector_index),
                "beacon vector archive",
                "--provider",
                "deterministic-test",
                "--dimensions",
                "16",
                "--limit",
                "1",
                "--hide-text",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        hidden_text_lines = [line for line in hidden_text_command.stdout.splitlines() if line.startswith("{")]
        hidden_text_payload = json.loads(hidden_text_lines[0]) if hidden_text_lines else {}
        search_index.write_text(search_index.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        stale_issues = validate_vector_index_source(loaded)
    providers = list_embedding_providers()
    public_export_manifest = [
        "README.md",
        "docs/VECTOR_INDEX.md",
        "pdfrejuvenator/vector_index.py",
        "scripts/validate_vector_index.py",
    ]
    private_runtime_manifest = [
        "private_coverage_matrix/coverage_matrix.json",
        "private_omit_text_smoke/private_ollama_vector_index_omit_text.json",
        "private_omit_text_smoke/search_results_hidden_text.jsonl",
    ]
    public_export_private_artifacts = [
        item for item in public_export_manifest if is_private_runtime_vector_artifact(item)
    ]
    classified_private_runtime_artifacts = [
        item for item in private_runtime_manifest if is_private_runtime_vector_artifact(item)
    ]
    return [
        ("schema version", payload.get("schema_version") == VECTOR_INDEX_SCHEMA_VERSION, ""),
        ("provider dimensions", payload.get("embedding_provider", {}).get("dimensions") == 16, ""),
        ("provider name", payload.get("embedding_provider", {}).get("provider") == "deterministic-test", ""),
        ("chunk generation", len(chunks) >= 1, ""),
        ("vector index count", count == len(payload.get("chunks", [])) == 2, ""),
        ("redacted vector index count", redacted_count == 2, ""),
        ("redacted chunks omit text", all("text" not in chunk for chunk in redacted_loaded.get("chunks", [])), ""),
        ("redacted chunks marked", all(chunk.get("text_redacted") is True for chunk in redacted_loaded.get("chunks", [])), ""),
        ("chunk overlap metadata", payload.get("chunking", {}).get("overlap_chars") == 12, ""),
        ("redacted chunking metadata", redacted_loaded.get("chunking", {}).get("include_text") is False, ""),
        ("chunk hashes", all(chunk.get("chunk_sha256") for chunk in payload.get("chunks", [])), ""),
        ("source record count", payload.get("source_index", {}).get("record_count") == 2, ""),
        ("validation issues", issues == [], "; ".join(issues)),
        ("redacted validation issues", redacted_issues == [], "; ".join(redacted_issues)),
        ("source validation issues", source_issues == [], "; ".join(source_issues)),
        ("provider compatibility", provider_issues == [], "; ".join(provider_issues)),
        ("provider mismatch detection", mismatch_issues != [], "dimension mismatch should be reported"),
        ("stale source detection", stale_issues != [], "source mutation should require rebuild"),
        ("search result count", len(results) == 1, ""),
        ("redacted search result count", len(redacted_results) == 1, ""),
        ("redacted search omits result text", "text" not in redacted_result_payloads[0], ""),
        ("threshold search result count", len(threshold_results) == 1, ""),
        ("search result source", result_payloads[0].get("source_record_id") == "synthetic-corpus::synthetic-book::p001::text", ""),
        ("search result metadata", result_payloads[0].get("metadata", {}).get("privacy_scope") == "public_safe_fixture", ""),
        ("hidden text CLI exit", hidden_text_command.returncode == 0, hidden_text_command.stderr),
        ("hidden text CLI omits text", "text" not in hidden_text_payload, ""),
        ("hidden text CLI keeps source", hidden_text_payload.get("source_record_id") == "synthetic-corpus::synthetic-book::p001::text", ""),
        ("inspection summary", inspection.get("validation_issue_count") == 0, ""),
        ("provider registry", providers[0].get("name") == "deterministic-test", ""),
        ("ollama provider registered", any(item.get("name") == "ollama" for item in providers), ""),
        (
            "public export private vector artifact boundary",
            public_export_private_artifacts == [],
            ", ".join(public_export_private_artifacts),
        ),
        (
            "private runtime vector artifact classification",
            classified_private_runtime_artifacts == private_runtime_manifest,
            ", ".join(set(private_runtime_manifest) - set(classified_private_runtime_artifacts)),
        ),
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
