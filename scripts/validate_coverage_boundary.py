from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


COVERAGE_BOUNDARY_SCHEMA_VERSION = "pdfrejuvenator.coverage_boundary.v0.6"
EXPECTED_RELEASE_LINE = "PDFRejuvenator v0.6.0 local implementation"


def validate_payload(payload: dict[str, Any], *, check_paths: bool = False) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != COVERAGE_BOUNDARY_SCHEMA_VERSION:
        issues.append("unsupported schema_version")
    if payload.get("release_line") != EXPECTED_RELEASE_LINE:
        issues.append("release_line must name PDFRejuvenator v0.6.0 local implementation")
    if payload.get("coverage_type") != "bounded_private_real_data_matrix":
        issues.append("coverage_type must be bounded_private_real_data_matrix")
    if payload.get("coverage_is_exhaustive") is not False:
        issues.append("coverage_is_exhaustive must be false")
    if payload.get("coverage_is_public_release_artifact") is not False:
        issues.append("coverage_is_public_release_artifact must be false")
    if payload.get("provider") != "ollama":
        issues.append("provider must be ollama for current v0.6 evidence")
    if payload.get("model") != "nomic-embed-text":
        issues.append("model must be nomic-embed-text for current v0.6 evidence")
    if int(payload.get("observed_dimensions", 0)) != 768:
        issues.append("observed_dimensions must be 768 for current v0.6 evidence")
    if int(payload.get("input_count", 0)) < 7:
        issues.append("input_count must be at least 7")
    if int(payload.get("total_vector_chunks", 0)) < int(payload.get("input_count", 0)):
        issues.append("total_vector_chunks must be at least input_count")

    for field in (
        "build_failures",
        "validation_command_failures",
        "validation_issue_count",
        "inspect_command_failures",
        "search_command_failures",
    ):
        if int(payload.get(field, -1)) != 0:
            issues.append(f"{field} must be 0")

    coverage_matrix_path = str(payload.get("coverage_matrix_path", ""))
    if not coverage_matrix_path:
        issues.append("coverage_matrix_path is required")
    if check_paths and coverage_matrix_path and not Path(coverage_matrix_path).exists():
        issues.append("coverage_matrix_path does not exist")

    boundary_statement = str(payload.get("boundary_statement", "")).lower()
    if "not full-corpus" not in boundary_statement and "not full corpus" not in boundary_statement:
        issues.append("boundary_statement must explicitly state non-exhaustive coverage")

    protected_boundary = str(payload.get("protected_boundary", ""))
    if "No commit, tag, push" not in protected_boundary:
        issues.append("protected_boundary must preserve source-control/publication blocker")

    return issues


def positive_fixture() -> dict[str, Any]:
    return {
        "schema_version": COVERAGE_BOUNDARY_SCHEMA_VERSION,
        "release_line": EXPECTED_RELEASE_LINE,
        "coverage_type": "bounded_private_real_data_matrix",
        "coverage_is_exhaustive": False,
        "coverage_is_public_release_artifact": False,
        "provider": "ollama",
        "model": "nomic-embed-text",
        "observed_dimensions": 768,
        "input_count": 7,
        "total_vector_chunks": 15,
        "build_failures": 0,
        "validation_command_failures": 0,
        "validation_issue_count": 0,
        "inspect_command_failures": 0,
        "search_command_failures": 0,
        "coverage_matrix_path": "G:\\Evidence\\private_coverage_matrix\\coverage_matrix.json",
        "boundary_statement": "This is bounded coverage, not full-corpus performance or quality coverage.",
        "protected_boundary": "No commit, tag, push, package publication, GitHub release, external sharing, remote mutation, or public action is authorized by this evidence.",
    }


def run_checks() -> list[tuple[str, bool, str]]:
    base = positive_fixture()
    checks: list[tuple[str, bool, str]] = []
    positive_issues = validate_payload(base)
    checks.append(("valid coverage boundary fixture", positive_issues == [], "; ".join(positive_issues)))

    exhaustive_claim = copy.deepcopy(base)
    exhaustive_claim["coverage_is_exhaustive"] = True
    checks.append(("reject exhaustive coverage claim", bool(validate_payload(exhaustive_claim)), "negative control should fail"))

    public_artifact_claim = copy.deepcopy(base)
    public_artifact_claim["coverage_is_public_release_artifact"] = True
    checks.append(("reject public release artifact claim", bool(validate_payload(public_artifact_claim)), "negative control should fail"))

    weak_sample = copy.deepcopy(base)
    weak_sample["input_count"] = 1
    checks.append(("reject weak private sample count", bool(validate_payload(weak_sample)), "negative control should fail"))

    provider_mismatch = copy.deepcopy(base)
    provider_mismatch["provider"] = "deterministic-test"
    checks.append(("reject provider mismatch", bool(validate_payload(provider_mismatch)), "negative control should fail"))

    failure_counts = copy.deepcopy(base)
    failure_counts["validation_issue_count"] = 1
    checks.append(("reject validation issues", bool(validate_payload(failure_counts)), "negative control should fail"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PDFRejuvenator v0.6 coverage-boundary manifest.")
    parser.add_argument("manifest", type=Path, nargs="?", help="Optional coverage-boundary JSON to validate.")
    parser.add_argument("--check-paths", action="store_true", help="Require referenced local evidence paths to exist.")
    args = parser.parse_args()

    checks = run_checks()
    if args.manifest:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        issues = validate_payload(payload, check_paths=args.check_paths)
        checks.append((f"coverage boundary {args.manifest}", issues == [], "; ".join(issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, detail in failures:
        print(f"FAIL: {name} - {detail}")
    print(f"COVERAGE BOUNDARY VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
