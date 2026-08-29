from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.answering import ANSWER_SCHEMA_VERSION, validate_answer_payload  # noqa: E402


def load_evidence_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"evidence line {line_number} must be a JSON object")
        records.append(payload)
    return records


def validate_answer_file(answer_path: Path, evidence_path: Path) -> list[str]:
    payload = json.loads(answer_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return ["answer file must contain a JSON object"]
    evidence = load_evidence_jsonl(evidence_path)
    return validate_answer_payload(payload, evidence)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def run_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        evidence_path = root / "evidence.jsonl"
        answer_path = root / "answer.json"
        evidence = [
            {
                "chunk_id": "record-001::chunk0000",
                "source_id": "record-001",
                "source_record_id": "record-001",
                "score": 0.91,
                "record_type": "text",
                "page": 7,
                "text": "The city engineer validates the bridge.",
            }
        ]
        valid_answer = {
            "schema_version": ANSWER_SCHEMA_VERSION,
            "question": "Who validates the bridge?",
            "answer": "The city engineer validates the bridge.",
            "confidence": "high",
            "citations": [
                {
                    "claim": "The city engineer validates the bridge.",
                    "source_id": "record-001",
                    "chunk_id": "record-001::chunk0000",
                    "score": 0.91,
                    "page": 7,
                    "record_type": "text",
                }
            ],
            "unsupported_claims": [],
            "evidence_count": 1,
            "insufficient_evidence": False,
        }
        _write_jsonl(evidence_path, evidence)
        _write_json(answer_path, valid_answer)
        checks.append(("accept grounded answer", validate_answer_file(answer_path, evidence_path) == [], "valid fixture should pass"))

        missing_citation = dict(valid_answer)
        missing_citation["citations"] = [dict(valid_answer["citations"][0], chunk_id="missing")]
        _write_json(answer_path, missing_citation)
        checks.append(
            (
                "reject stale retrieval or missing citation chunk",
                any("chunk_id does not reference retrieved evidence" in issue for issue in validate_answer_file(answer_path, evidence_path)),
                "negative control should fail",
            )
        )

        ungrounded = dict(valid_answer)
        ungrounded["answer"] = "The archive pilot approved the solar treaty."
        ungrounded["citations"] = [
            dict(
                valid_answer["citations"][0],
                claim="The archive pilot approved the solar treaty.",
            )
        ]
        _write_json(answer_path, ungrounded)
        checks.append(
            (
                "reject ungrounded cited claim",
                any("does not share grounded terms" in issue for issue in validate_answer_file(answer_path, evidence_path)),
                "negative control should fail",
            )
        )

        overclaim = dict(valid_answer)
        overclaim["answer"] = "The city engineer validates the bridge and approved the solar treaty."
        overclaim["citations"] = [dict(valid_answer["citations"][0])]
        _write_json(answer_path, overclaim)
        checks.append(
            (
                "reject unsupported answer overclaim",
                any("unsupported terms" in issue for issue in validate_answer_file(answer_path, evidence_path)),
                "negative control should fail",
            )
        )

        uncited = dict(valid_answer)
        uncited["citations"] = []
        _write_json(answer_path, uncited)
        checks.append(
            (
                "reject sufficient answer without citations",
                any("require at least one citation" in issue for issue in validate_answer_file(answer_path, evidence_path)),
                "negative control should fail",
            )
        )

        insufficient = dict(valid_answer)
        insufficient["answer"] = "Insufficient evidence."
        insufficient["confidence"] = "low"
        insufficient["citations"] = []
        insufficient["evidence_count"] = 0
        insufficient["insufficient_evidence"] = True
        _write_jsonl(evidence_path, [])
        _write_json(answer_path, insufficient)
        checks.append(("accept insufficient evidence answer", validate_answer_file(answer_path, evidence_path) == [], "empty evidence can pass only as insufficient"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PDFRejuvenator answer-query JSON against retrieved evidence.")
    parser.add_argument("answer", type=Path, nargs="?")
    parser.add_argument("evidence", type=Path, nargs="?")
    args = parser.parse_args()

    checks = run_checks()
    if args.answer is not None or args.evidence is not None:
        if args.answer is None or args.evidence is None:
            print("FAIL: answer and evidence paths must be provided together")
            print(f"ANSWER QUERY VALIDATION: checks={len(checks) + 1} failures=1")
            return 1
        issues = validate_answer_file(args.answer.resolve(), args.evidence.resolve())
        checks.append(("actual answer-query output", issues == [], "; ".join(issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, detail in failures:
        print(f"FAIL: {name} - {detail}")
    print(f"ANSWER QUERY VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
