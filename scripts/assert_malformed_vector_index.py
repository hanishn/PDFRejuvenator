from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _provider_payload() -> dict[str, Any]:
    return {
        "provider": "deterministic-test",
        "model": "blake2b-token-buckets",
        "dimensions": 32,
        "fingerprint": "deterministic-test:32:v1",
    }


def _valid_chunk(chunk_id: str = "valid::chunk0000") -> dict[str, Any]:
    return {
        "schema_version": "pdfrejuvenator.vector_chunk.v0.6",
        "chunk_id": chunk_id,
        "chunk_sha256": "0e60577aef6c241c984279df260545708713ece8a2676773241a6d0dfb5fac64",
        "source_record_id": "valid-source",
        "record_type": "text",
        "page": 1,
        "artifact_path": "synthetic/source.md",
        "metadata": {"doc_id": "valid-doc"},
        "text": "Valid mixed fixture text.",
        "embedding": [1.0] + [0.0] * 31,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_case(
    *,
    python_exe: Path,
    vector_index: Path,
    output_dir: Path,
    case_name: str,
    expected_error: str,
) -> dict[str, Any]:
    answer_path = output_dir / f"{case_name}_answer_query.json"
    evidence_path = output_dir / f"{case_name}_answer_query_evidence.jsonl"
    for path in (answer_path, evidence_path):
        if path.exists():
            path.unlink()
    command = [
        str(python_exe),
        "-m",
        "pdfrejuvenator",
        "answer-query",
        str(vector_index),
        "What does the malformed index say?",
        "--provider",
        "deterministic-test",
        "--no-generate",
        "--output",
        str(answer_path),
        "--evidence-output",
        str(evidence_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20.0, check=False)
    stdout_path = output_dir / f"{case_name}_stdout.txt"
    stderr_path = output_dir / f"{case_name}_stderr.txt"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    passed = result.returncode == 1 and expected_error in result.stderr and not answer_path.exists() and not evidence_path.exists()
    return {
        "case": case_name,
        "passed": passed,
        "returncode": result.returncode,
        "expected_error": expected_error,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "answer_exists": answer_path.exists(),
        "evidence_exists": evidence_path.exists(),
        "stderr": result.stderr.strip(),
    }


def run_checks(python_exe: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    invalid_json = output_dir / "invalid_json_vector_index.json"
    invalid_json.write_text("{not valid json\n", encoding="utf-8")

    missing_chunks = output_dir / "missing_chunks_vector_index.json"
    _write_json(
        missing_chunks,
        {
            "schema_version": "pdfrejuvenator.vector_index.v0.6",
            "chunk_count": 0,
            "embedding_provider": _provider_payload(),
        },
    )

    bad_embedding = output_dir / "bad_embedding_vector_index.json"
    _write_json(
        bad_embedding,
        {
            "schema_version": "pdfrejuvenator.vector_index.v0.6",
            "chunk_count": 1,
            "embedding_provider": _provider_payload(),
            "chunks": [
                {
                    "schema_version": "pdfrejuvenator.vector_chunk.v0.6",
                    "chunk_id": "bad::chunk0000",
                    "chunk_sha256": "placeholder",
                    "source_record_id": "bad",
                    "text": "Malformed vector index fixture text.",
                    "embedding": ["not-number"],
                }
            ],
        },
    )

    missing_chunk_id = output_dir / "missing_chunk_id_vector_index.json"
    chunk_without_id = _valid_chunk()
    chunk_without_id.pop("chunk_id")
    _write_json(
        missing_chunk_id,
        {
            "schema_version": "pdfrejuvenator.vector_index.v0.6",
            "chunk_count": 1,
            "embedding_provider": _provider_payload(),
            "chunks": [chunk_without_id],
        },
    )

    missing_source_record_id = output_dir / "missing_source_record_id_vector_index.json"
    chunk_without_source = _valid_chunk()
    chunk_without_source.pop("source_record_id")
    _write_json(
        missing_source_record_id,
        {
            "schema_version": "pdfrejuvenator.vector_index.v0.6",
            "chunk_count": 1,
            "embedding_provider": _provider_payload(),
            "chunks": [chunk_without_source],
        },
    )

    mixed_valid_invalid = output_dir / "mixed_valid_invalid_vector_index.json"
    mixed_invalid_chunk = _valid_chunk("mixed-invalid::chunk0001")
    mixed_invalid_chunk["embedding"] = [1.0, "bad-value"] + [0.0] * 30
    _write_json(
        mixed_valid_invalid,
        {
            "schema_version": "pdfrejuvenator.vector_index.v0.6",
            "chunk_count": 2,
            "embedding_provider": _provider_payload(),
            "chunks": [_valid_chunk("mixed-valid::chunk0000"), mixed_invalid_chunk],
        },
    )

    checks = [
        _run_case(
            python_exe=python_exe,
            vector_index=invalid_json,
            output_dir=output_dir,
            case_name="invalid_json",
            expected_error="Expecting property name enclosed in double quotes",
        ),
        _run_case(
            python_exe=python_exe,
            vector_index=missing_chunks,
            output_dir=output_dir,
            case_name="missing_chunks",
            expected_error="chunks must be a list",
        ),
        _run_case(
            python_exe=python_exe,
            vector_index=bad_embedding,
            output_dir=output_dir,
            case_name="bad_embedding",
            expected_error="embedding length must match provider dimensions",
        ),
        _run_case(
            python_exe=python_exe,
            vector_index=missing_chunk_id,
            output_dir=output_dir,
            case_name="missing_chunk_id",
            expected_error="chunk_id is required",
        ),
        _run_case(
            python_exe=python_exe,
            vector_index=missing_source_record_id,
            output_dir=output_dir,
            case_name="missing_source_record_id",
            expected_error="source_record_id is required",
        ),
        _run_case(
            python_exe=python_exe,
            vector_index=mixed_valid_invalid,
            output_dir=output_dir,
            case_name="mixed_valid_invalid",
            expected_error="embedding values must be numeric",
        ),
    ]
    failures = [check for check in checks if not check["passed"]]
    return {"checks": checks, "check_count": len(checks), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert answer-query fails closed for malformed vector indexes.")
    parser.add_argument("--python-exe", type=Path, default=Path(sys.executable))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    summary = run_checks(args.python_exe.resolve(), args.output_dir.resolve())
    report_path = args.report or args.output_dir / "malformed_vector_index_assertions.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"MALFORMED VECTOR INDEX ASSERTIONS: checks={summary['check_count']} failures={len(summary['failures'])}")
    for failure in summary["failures"]:
        print(f"FAIL: {failure['case']} - {failure}")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
