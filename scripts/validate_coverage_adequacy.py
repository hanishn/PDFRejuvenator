from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "pdfrejuvenator.coverage_adequacy.v0.6"
RELEASE_LINE = "PDFRejuvenator v0.6.0 local implementation"
REQUIRED_STRATA = {
    "contiguous_front_matter",
    "early_body",
    "middle_body",
    "late_body",
    "multi_chunk_records",
    "single_chunk_records",
    "omit_text_hide_text_redaction",
    "table_ocr_heavy_records",
}


def validate_payload(payload: dict[str, Any], *, check_paths: bool = False) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        issues.append("unsupported schema_version")
    if payload.get("release_line") != RELEASE_LINE:
        issues.append("release_line must name PDFRejuvenator v0.6.0 local implementation")
    if payload.get("coverage_is_exhaustive") is not False:
        issues.append("coverage_is_exhaustive must be false")
    if payload.get("public_release_artifact") is not False:
        issues.append("public_release_artifact must be false")
    if payload.get("adequacy_decision") != "bounded_local_release_review_support":
        issues.append("adequacy_decision must be bounded_local_release_review_support")

    matrix = payload.get("matrix_summary")
    if not isinstance(matrix, dict):
        issues.append("matrix_summary must be an object")
        matrix = {}
    if int(matrix.get("input_count", 0)) < 7:
        issues.append("matrix_summary.input_count must be at least 7")
    if int(matrix.get("total_vector_chunks", 0)) < 15:
        issues.append("matrix_summary.total_vector_chunks must be at least 15")
    if int(matrix.get("provider_dimensions", 0)) != 768:
        issues.append("matrix_summary.provider_dimensions must be 768")
    if matrix.get("provider") != "ollama":
        issues.append("matrix_summary.provider must be ollama")
    if matrix.get("model") != "nomic-embed-text":
        issues.append("matrix_summary.model must be nomic-embed-text")

    strata = payload.get("strata")
    if not isinstance(strata, dict):
        issues.append("strata must be an object")
        strata = {}
    missing_strata = sorted(REQUIRED_STRATA - set(strata))
    if missing_strata:
        issues.append(f"missing required strata: {', '.join(missing_strata)}")
    for name, value in strata.items():
        if name not in REQUIRED_STRATA:
            issues.append(f"unexpected stratum: {name}")
        if not isinstance(value, dict):
            issues.append(f"strata.{name} must be an object")
            continue
        row_ids = value.get("row_ids")
        if not isinstance(row_ids, list) or not row_ids:
            issues.append(f"strata.{name}.row_ids must be a non-empty list")

    limits = payload.get("known_limits")
    if not isinstance(limits, list) or not limits:
        issues.append("known_limits must be a non-empty list")
    elif not any("not exhaustive" in str(limit).lower() for limit in limits):
        issues.append("known_limits must explicitly state not exhaustive")

    for field in ("coverage_matrix_path", "omit_hide_matrix_path", "coverage_boundary_path"):
        path_value = str(payload.get(field, ""))
        if not path_value:
            issues.append(f"{field} is required")
        if check_paths and path_value and not Path(path_value).exists():
            issues.append(f"{field} does not exist")

    supplemental = payload.get("supplemental_matrices")
    if not isinstance(supplemental, list) or not supplemental:
        issues.append("supplemental_matrices must be a non-empty list")
    else:
        table_matrix = next(
            (item for item in supplemental if isinstance(item, dict) and item.get("id") == "table_ocr_heavy_records"),
            None,
        )
        if not isinstance(table_matrix, dict):
            issues.append("supplemental_matrices must include table_ocr_heavy_records")
        else:
            if int(table_matrix.get("input_count", 0)) < 3:
                issues.append("table_ocr_heavy_records.input_count must be at least 3")
            if int(table_matrix.get("total_vector_chunks", 0)) < 100:
                issues.append("table_ocr_heavy_records.total_vector_chunks must be at least 100")
            if table_matrix.get("redacted") is not True:
                issues.append("table_ocr_heavy_records.redacted must be true")
            path_value = str(table_matrix.get("matrix_path", ""))
            if not path_value:
                issues.append("table_ocr_heavy_records.matrix_path is required")
            if check_paths and path_value and not Path(path_value).exists():
                issues.append("table_ocr_heavy_records.matrix_path does not exist")

    protected_boundary = str(payload.get("protected_boundary", ""))
    if "No commit, tag, push" not in protected_boundary:
        issues.append("protected_boundary must preserve source-control/publication blocker")

    return issues


def positive_fixture() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "release_line": RELEASE_LINE,
        "coverage_is_exhaustive": False,
        "public_release_artifact": False,
        "adequacy_decision": "bounded_local_release_review_support",
        "matrix_summary": {
            "input_count": 7,
            "total_vector_chunks": 15,
            "provider": "ollama",
            "model": "nomic-embed-text",
            "provider_dimensions": 768,
        },
        "strata": {
            name: {"row_ids": ["case_001"]}
            for name in REQUIRED_STRATA
        },
        "supplemental_matrices": [
            {
                "id": "table_ocr_heavy_records",
                "input_count": 3,
                "total_vector_chunks": 519,
                "redacted": True,
                "matrix_path": "G:\\Evidence\\private_expanded_coverage_matrix\\expanded_coverage_matrix.json",
            }
        ],
        "known_limits": ["This is not exhaustive full-corpus quality coverage."],
        "coverage_matrix_path": "G:\\Evidence\\private_coverage_matrix\\coverage_matrix.json",
        "omit_hide_matrix_path": "G:\\Evidence\\private_omit_hide_matrix\\omit_hide_matrix.json",
        "coverage_boundary_path": "G:\\Evidence\\coverage_boundary.json",
        "protected_boundary": "No commit, tag, push, package publication, GitHub release, external sharing, remote mutation, or public action is authorized by this evidence.",
    }


def run_checks() -> list[tuple[str, bool, str]]:
    base = positive_fixture()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("valid coverage adequacy fixture", validate_payload(base) == [], "fixture should pass"))

    exhaustive_claim = copy.deepcopy(base)
    exhaustive_claim["coverage_is_exhaustive"] = True
    checks.append(("reject exhaustive adequacy claim", bool(validate_payload(exhaustive_claim)), "negative control should fail"))

    missing_stratum = copy.deepcopy(base)
    del missing_stratum["strata"]["late_body"]
    checks.append(("reject missing required stratum", bool(validate_payload(missing_stratum)), "negative control should fail"))

    weak_sample = copy.deepcopy(base)
    weak_sample["matrix_summary"]["input_count"] = 3
    checks.append(("reject weak matrix row count", bool(validate_payload(weak_sample)), "negative control should fail"))

    provider_mismatch = copy.deepcopy(base)
    provider_mismatch["matrix_summary"]["provider"] = "deterministic-test"
    checks.append(("reject provider mismatch", bool(validate_payload(provider_mismatch)), "negative control should fail"))

    missing_limit = copy.deepcopy(base)
    missing_limit["known_limits"] = ["bounded coverage"]
    checks.append(("reject missing non-exhaustive limit", bool(validate_payload(missing_limit)), "negative control should fail"))

    missing_supplemental = copy.deepcopy(base)
    missing_supplemental["supplemental_matrices"] = []
    checks.append(("reject missing supplemental matrix", bool(validate_payload(missing_supplemental)), "negative control should fail"))

    weak_supplemental = copy.deepcopy(base)
    weak_supplemental["supplemental_matrices"][0]["total_vector_chunks"] = 1
    checks.append(("reject weak supplemental chunk count", bool(validate_payload(weak_supplemental)), "negative control should fail"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PDFRejuvenator v0.6 coverage adequacy manifest.")
    parser.add_argument("manifest", type=Path, nargs="?", help="Optional coverage adequacy JSON to validate.")
    parser.add_argument("--check-paths", action="store_true", help="Require referenced local evidence paths to exist.")
    args = parser.parse_args()

    checks = run_checks()
    if args.manifest:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        issues = validate_payload(payload, check_paths=args.check_paths)
        checks.append((f"coverage adequacy {args.manifest}", issues == [], "; ".join(issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, detail in failures:
        print(f"FAIL: {name} - {detail}")
    print(f"COVERAGE ADEQUACY VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
