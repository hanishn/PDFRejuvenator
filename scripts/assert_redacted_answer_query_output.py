from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        records.append(payload)
    return records


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def assert_redacted_output(answer_path: Path, evidence_path: Path, *, forbidden_text: str) -> dict[str, Any]:
    answer = _load_json(answer_path)
    evidence = _load_jsonl(evidence_path)
    serialized_answer = json.dumps(answer, sort_keys=True)
    serialized_evidence = json.dumps(evidence, sort_keys=True)
    citations = answer.get("citations", [])
    checks: list[dict[str, Any]] = []

    _check(checks, "schema", answer.get("schema_version") == "pdfrejuvenator.answer_query.v0.7", str(answer.get("schema_version")))
    _check(checks, "redacted_flag", answer.get("evidence_redacted") is True, str(answer.get("evidence_redacted")))
    _check(checks, "evidence_count", answer.get("evidence_count") == len(evidence) and len(evidence) > 0, f"answer={answer.get('evidence_count')} evidence={len(evidence)}")
    _check(checks, "citation_count", isinstance(citations, list) and len(citations) == len(evidence), str(citations))
    _check(checks, "answer_does_not_copy_forbidden_text", forbidden_text not in serialized_answer, serialized_answer)
    _check(checks, "evidence_does_not_copy_forbidden_text", forbidden_text not in serialized_evidence, serialized_evidence)
    _check(checks, "evidence_omits_text_field", all("text" not in record for record in evidence), serialized_evidence)
    if citations and evidence:
        citation = citations[0]
        record = evidence[0]
        _check(checks, "citation_chunk_exists", citation.get("chunk_id") == record.get("chunk_id"), str(citation))
        _check(checks, "citation_source_matches", citation.get("source_id") == record.get("source_id"), str(citation))
        _check(checks, "citation_claim_metadata_only", citation.get("claim") == "retrieved evidence record", str(citation.get("claim")))

    failures = [check for check in checks if not check["passed"]]
    return {"checks": checks, "check_count": len(checks), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert redacted answer-query output does not copy evidence text.")
    parser.add_argument("answer", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--forbidden-text", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    summary = assert_redacted_output(args.answer.resolve(), args.evidence.resolve(), forbidden_text=args.forbidden_text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REDACTED ANSWER ASSERTIONS: checks={summary['check_count']} failures={len(summary['failures'])}")
    for failure in summary["failures"]:
        print(f"FAIL: {failure['name']} - {failure['detail']}")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
