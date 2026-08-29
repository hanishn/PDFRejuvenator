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


def assert_smoke_output(
    answer_path: Path,
    evidence_path: Path,
    *,
    expected_question: str,
    expected_fact: str,
    expected_evidence_count: int,
    expected_page: int | None,
    expected_doc_id: str | None,
) -> dict[str, Any]:
    answer = _load_json(answer_path)
    evidence = _load_jsonl(evidence_path)
    checks: list[dict[str, Any]] = []

    _check(checks, "schema", answer.get("schema_version") == "pdfrejuvenator.answer_query.v0.7", str(answer.get("schema_version")))
    _check(checks, "question", answer.get("question") == expected_question, str(answer.get("question")))
    _check(
        checks,
        "evidence_count",
        answer.get("evidence_count") == expected_evidence_count and len(evidence) == expected_evidence_count,
        f"answer={answer.get('evidence_count')} evidence={len(evidence)} expected={expected_evidence_count}",
    )
    _check(checks, "insufficient_false", answer.get("insufficient_evidence") is False, str(answer.get("insufficient_evidence")))
    _check(checks, "confidence_low", answer.get("confidence") == "low", str(answer.get("confidence")))
    _check(checks, "unsupported_empty", answer.get("unsupported_claims") == [], str(answer.get("unsupported_claims")))
    _check(
        checks,
        "answer_boundary",
        answer.get("answer") == f"Retrieved {expected_evidence_count} evidence records. Generation provider not enabled.",
        str(answer.get("answer")),
    )

    citations = answer.get("citations", [])
    _check(checks, "citation_count", isinstance(citations, list) and len(citations) == expected_evidence_count, str(citations))
    citation = citations[0] if isinstance(citations, list) and citations else {}
    record = evidence[0] if evidence else {}
    _check(
        checks,
        "citation_chunk_exists",
        citation.get("chunk_id") == record.get("chunk_id"),
        f"citation={citation.get('chunk_id')} evidence={record.get('chunk_id')}",
    )
    _check(
        checks,
        "citation_source_matches",
        citation.get("source_id") == record.get("source_id"),
        f"citation={citation.get('source_id')} evidence={record.get('source_id')}",
    )
    _check(
        checks,
        "citation_page_matches",
        expected_page is None or citation.get("page") == record.get("page") == expected_page,
        f"citation={citation.get('page')} evidence={record.get('page')}",
    )
    if expected_doc_id is not None:
        _check(checks, "doc_id_metadata", record.get("metadata", {}).get("doc_id") == expected_doc_id, str(record.get("metadata")))

    text = str(record.get("text", ""))
    claim = str(citation.get("claim", ""))
    _check(checks, "evidence_contains_expected_fact", expected_fact in text, text)
    _check(checks, "claim_grounded_in_evidence", bool(claim) and claim in text, claim)
    _check(
        checks,
        "no_closed_overclaim",
        "closed" not in str(answer.get("answer", "")).lower() and "closed" not in claim.lower(),
        f"{answer.get('answer', '')} / {claim}",
    )

    failures = [check for check in checks if not check["passed"]]
    return {"checks": checks, "check_count": len(checks), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert consumed answer-query smoke output fields and citation linkage.")
    parser.add_argument("answer", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--expected-question", default="What does the smoke test evidence say?")
    parser.add_argument("--expected-fact", default="archive valve is open")
    parser.add_argument("--expected-evidence-count", type=int, default=1)
    parser.add_argument("--expected-page", type=int, default=1)
    parser.add_argument("--expected-doc-id", default="smoke-doc")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON assertion report path.")
    args = parser.parse_args()

    summary = assert_smoke_output(
        args.answer.resolve(),
        args.evidence.resolve(),
        expected_question=args.expected_question,
        expected_fact=args.expected_fact,
        expected_evidence_count=args.expected_evidence_count,
        expected_page=args.expected_page,
        expected_doc_id=args.expected_doc_id or None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"CONSUMED ANSWER ASSERTIONS: checks={summary['check_count']} failures={len(summary['failures'])}")
    for failure in summary["failures"]:
        print(f"FAIL: {failure['name']} - {failure['detail']}")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
