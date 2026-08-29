from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


EXPECTED_PROVIDER_DIMENSIONS = 768
MINIMUM_PRIVATE_INPUTS = 7


def _int_value(row: dict[str, Any], field: str, default: int = -1) -> int:
    try:
        return int(row.get(field, default))
    except (TypeError, ValueError):
        return default


def validate_rows(
    rows: list[dict[str, Any]],
    *,
    check_paths: bool = False,
    require_redacted: bool = False,
    min_rows: int = MINIMUM_PRIVATE_INPUTS,
) -> list[str]:
    issues: list[str] = []
    if len(rows) < min_rows:
        issues.append(f"matrix must contain at least {min_rows} private input rows")

    ids = [str(row.get("id", "")) for row in rows]
    if any(not item for item in ids):
        issues.append("each matrix row must include id")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        issues.append(f"duplicate matrix ids: {', '.join(duplicates)}")

    total_chunks = 0
    for row in rows:
        row_id = str(row.get("id", "<missing>"))
        for field in ("build_exit", "validate_exit", "inspect_exit", "search_exit"):
            if _int_value(row, field) != 0:
                issues.append(f"{row_id}.{field} must be 0")
        if (not require_redacted or "validation_issues" in row) and _int_value(row, "validation_issues") != 0:
            issues.append(f"{row_id}.validation_issues must be 0")
        if (not require_redacted or "dimensions" in row) and _int_value(row, "dimensions") != EXPECTED_PROVIDER_DIMENSIONS:
            issues.append(f"{row_id}.dimensions must be {EXPECTED_PROVIDER_DIMENSIONS}")
        chunks = _int_value(row, "chunks", 0)
        if chunks <= 0:
            issues.append(f"{row_id}.chunks must be greater than 0")
        total_chunks += max(chunks, 0)
        if (not require_redacted or "search_results_count" in row) and _int_value(row, "search_results_count", 0) <= 0:
            issues.append(f"{row_id}.search_results_count must be greater than 0")

        if require_redacted:
            if _int_value(row, "omit_text_vector_text_field_matches") != 0:
                issues.append(f"{row_id}.omit_text_vector_text_field_matches must be 0")
            if _int_value(row, "hide_text_search_text_field_matches") != 0:
                issues.append(f"{row_id}.hide_text_search_text_field_matches must be 0")

        for field in ("vector_index", "inspect", "search_results"):
            path_value = row.get(field)
            if path_value and check_paths and not Path(str(path_value)).exists():
                issues.append(f"{row_id}.{field} does not exist")

    if total_chunks < len(rows):
        issues.append("total chunks must be at least row count")
    return issues


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("matrix JSON must be a list")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError("matrix JSON rows must be objects")
    return payload


def positive_fixture() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(MINIMUM_PRIVATE_INPUTS):
        rows.append({
            "id": f"case_{index + 1:03d}",
            "vector_index": f"G:\\Evidence\\case_{index + 1:03d}\\vector_index.json",
            "inspect": f"G:\\Evidence\\case_{index + 1:03d}\\inspect.json",
            "search_results": f"G:\\Evidence\\case_{index + 1:03d}\\search_results.jsonl",
            "chunks": 1,
            "dimensions": EXPECTED_PROVIDER_DIMENSIONS,
            "validation_issues": 0,
            "search_results_count": 1,
            "build_exit": 0,
            "validate_exit": 0,
            "inspect_exit": 0,
            "search_exit": 0,
            "omit_text_vector_text_field_matches": 0,
            "hide_text_search_text_field_matches": 0,
        })
    return rows


def run_checks() -> list[tuple[str, bool, str]]:
    base = positive_fixture()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("valid private coverage matrix fixture", validate_rows(base, require_redacted=True) == [], "fixture should pass"))

    weak_sample = base[:1]
    checks.append(("reject weak sample count", bool(validate_rows(weak_sample)), "negative control should fail"))

    duplicate_id = copy.deepcopy(base)
    duplicate_id[1]["id"] = duplicate_id[0]["id"]
    checks.append(("reject duplicate matrix id", bool(validate_rows(duplicate_id)), "negative control should fail"))

    bad_exit = copy.deepcopy(base)
    bad_exit[0]["search_exit"] = 1
    checks.append(("reject command failure", bool(validate_rows(bad_exit)), "negative control should fail"))

    bad_dimensions = copy.deepcopy(base)
    bad_dimensions[0]["dimensions"] = 128
    checks.append(("reject dimension mismatch", bool(validate_rows(bad_dimensions)), "negative control should fail"))

    stored_text = copy.deepcopy(base)
    stored_text[0]["omit_text_vector_text_field_matches"] = 1
    checks.append(("reject redacted vector text field", bool(validate_rows(stored_text, require_redacted=True)), "negative control should fail"))

    emitted_text = copy.deepcopy(base)
    emitted_text[0]["hide_text_search_text_field_matches"] = 1
    checks.append(("reject hidden search text field", bool(validate_rows(emitted_text, require_redacted=True)), "negative control should fail"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a private PDFRejuvenator v0.6 coverage matrix.")
    parser.add_argument("matrix", type=Path, nargs="?", help="Optional matrix JSON to validate.")
    parser.add_argument("--check-paths", action="store_true", help="Require referenced local evidence paths to exist.")
    parser.add_argument("--require-redacted", action="store_true", help="Require omit-text/hide-text zero text-field evidence.")
    parser.add_argument("--min-rows", type=int, default=MINIMUM_PRIVATE_INPUTS, help="Minimum matrix row count.")
    args = parser.parse_args()

    checks = run_checks()
    if args.matrix:
        rows = load_rows(args.matrix)
        issues = validate_rows(
            rows,
            check_paths=args.check_paths,
            require_redacted=args.require_redacted,
            min_rows=args.min_rows,
        )
        checks.append((f"private coverage matrix {args.matrix}", issues == [], "; ".join(issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, detail in failures:
        print(f"FAIL: {name} - {detail}")
    print(f"PRIVATE COVERAGE MATRIX VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
