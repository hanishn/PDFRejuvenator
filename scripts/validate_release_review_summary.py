from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any


SUMMARY_SCHEMA_VERSION = "pdfrejuvenator.release_review_summary.v0.6"
EXPECTED_VECTOR_VALIDATION = "VECTOR INDEX SUMMARY: checks=32 failures=0"
EXPECTED_PROJECT_VALIDATION = "SUMMARY: checks=213 failures=0 warnings=0"
REQUIRED_CAPABILITIES = {
    "local Ollama semantic embedding provider",
    "build-vector-index --omit-text privacy control",
    "vector-search --hide-text privacy control",
    "private runtime vector artifact boundary validation",
    "installed public/package export smoke validation",
}
REQUIRED_CHANGED_FILE_CATEGORIES = {
    "documentation",
    "runtime_code",
    "version_metadata",
    "export_builders",
    "validators",
}
REQUIRED_VALIDATION_COMMANDS = {
    "python scripts\\validate_vector_index.py",
    "python scripts\\validate_pdfrejuvenator.py",
    "python scripts\\validate_release_review_summary.py v060_release_review_summary.json --check-paths",
    "python scripts\\validate_export_manifest.py public_source_export_release_summary_guard_final package_export_release_summary_guard_final",
    "python scripts\\validate_coverage_boundary.py coverage_boundary.json --check-paths",
    "python scripts\\validate_coverage_adequacy.py coverage_adequacy.json --check-paths",
    "python scripts\\validate_private_coverage_matrix.py private_coverage_matrix\\coverage_matrix.json --check-paths",
    "python scripts\\validate_private_coverage_matrix.py private_omit_hide_matrix\\omit_hide_matrix.json --check-paths --require-redacted",
    "python scripts\\validate_private_coverage_matrix.py private_expanded_coverage_matrix\\expanded_coverage_matrix.json --check-paths --require-redacted --min-rows 3",
    "python -m ruff check --no-cache pdfrejuvenator scripts src",
    "python scripts\\scrub_public_export.py --root .",
    "python scripts\\scrub_public_export.py --root public_source_export_release_summary_guard_final",
    "python scripts\\scrub_public_export.py --root package_export_release_summary_guard_final",
    "targeted private/IP term scan on public surfaces",
    "private runtime artifact name scan on public/package exports",
    "installed package functional vector smoke",
    "installed package validator smoke",
    "source functional vector smoke",
    "release-review summary path audit",
}
PUBLIC_EXPORT_KEYS = {"public_source_export", "package_export"}
PRIVATE_RUNTIME_NAME_FRAGMENTS = (
    "vector_index",
    "search_results",
    "coverage_matrix",
    "coverage_boundary",
    "private_index_boundary",
)
PRIVATE_TITLE_TERMS = tuple(
    term.strip().lower()
    for term in os.environ.get("PDFREJUVENATOR_PRIVATE_TERM_SCAN", "").split("|")
    if term.strip()
)


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_all_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_all_strings(item))
        return strings
    return []


def _validation_by_command(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("validation_results", [])
    if not isinstance(results, list):
        return {}
    return {
        str(item.get("command", "")): item
        for item in results
        if isinstance(item, dict)
    }


def _normalize_path(value: Any) -> str:
    return str(value).replace("/", "\\")


def _validate_changed_file_categories(payload: dict[str, Any], changed_files: list[Any]) -> list[str]:
    issues: list[str] = []
    changed = {_normalize_path(item) for item in changed_files if isinstance(item, str)}
    categories = payload.get("changed_file_categories")
    if not isinstance(categories, dict):
        return ["changed_file_categories must be an object"]

    missing_categories = sorted(REQUIRED_CHANGED_FILE_CATEGORIES - set(categories))
    if missing_categories:
        issues.append(f"missing changed file categories: {', '.join(missing_categories)}")

    categorized: list[str] = []
    for category, files in categories.items():
        if category not in REQUIRED_CHANGED_FILE_CATEGORIES:
            issues.append(f"unexpected changed file category: {category}")
        if not isinstance(files, list) or not files:
            issues.append(f"changed_file_categories.{category} must be a non-empty list")
            continue
        categorized.extend(_normalize_path(file_path) for file_path in files)

    categorized_set = set(categorized)
    missing_from_categories = sorted(changed - categorized_set)
    if missing_from_categories:
        issues.append(f"changed files missing from categories: {', '.join(missing_from_categories)}")

    unknown_in_categories = sorted(categorized_set - changed)
    if unknown_in_categories:
        issues.append(f"category files not listed in changed_files: {', '.join(unknown_in_categories)}")

    duplicates = sorted({file_path for file_path in categorized if categorized.count(file_path) > 1})
    if duplicates:
        issues.append(f"changed files appear in multiple categories: {', '.join(duplicates)}")

    required_validator_files = {
        "scripts\\validate_coverage_boundary.py",
        "scripts\\validate_coverage_adequacy.py",
        "scripts\\validate_export_manifest.py",
        "scripts\\validate_private_coverage_matrix.py",
        "scripts\\validate_release_review_summary.py",
        "scripts\\validate_pdfrejuvenator.py",
        "scripts\\validate_vector_index.py",
    }
    validator_files = {_normalize_path(file_path) for file_path in categories.get("validators", [])}
    missing_validators = sorted(required_validator_files - validator_files)
    if missing_validators:
        issues.append(f"validator category missing required files: {', '.join(missing_validators)}")

    return issues


def validate_payload(payload: dict[str, Any], *, check_paths: bool = False) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        issues.append("unsupported schema_version")
    if payload.get("release_line") != "PDFRejuvenator v0.6.0 local implementation":
        issues.append("release_line must name PDFRejuvenator v0.6.0 local implementation")

    changed_files = payload.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        issues.append("changed_files must be a non-empty list")
        changed_files = []
    issues.extend(_validate_changed_file_categories(payload, changed_files))

    capabilities = set(payload.get("capability_areas", []))
    missing_capabilities = sorted(REQUIRED_CAPABILITIES - capabilities)
    if missing_capabilities:
        issues.append(f"missing required capabilities: {', '.join(missing_capabilities)}")

    branch = payload.get("branch_checkpoint")
    if not isinstance(branch, dict):
        issues.append("branch_checkpoint must be an object")
    elif branch.get("protected_actions_performed") is not False:
        issues.append("protected_actions_performed must be false")

    evidence_paths = payload.get("evidence_paths")
    if not isinstance(evidence_paths, dict):
        issues.append("evidence_paths must be an object")
        evidence_paths = {}

    for key in PUBLIC_EXPORT_KEYS:
        path_value = str(evidence_paths.get(key, "")).replace("\\", "/").lower()
        path_name = Path(path_value).name.lower()
        if not path_value:
            issues.append(f"evidence_paths.{key} is required")
        if any(fragment in path_name for fragment in PRIVATE_RUNTIME_NAME_FRAGMENTS):
            issues.append(f"evidence_paths.{key} must not point to a private runtime artifact")

    if check_paths:
        for key, value in evidence_paths.items():
            if not Path(str(value)).exists():
                issues.append(f"evidence_paths.{key} does not exist")

    validations = _validation_by_command(payload)
    missing_validations = sorted(REQUIRED_VALIDATION_COMMANDS - set(validations))
    if missing_validations:
        issues.append(f"missing validation result commands: {', '.join(missing_validations)}")
    for command, item in validations.items():
        if item.get("result") != "pass":
            issues.append(f"validation result must be pass: {command}")
        summary_text = str(item.get("summary", "")).lower()
        if ("text fields=" in summary_text or "text field matches=" in summary_text) and not (
            "text fields=0" in summary_text or "text field matches=0" in summary_text
        ):
            issues.append(f"validation result reports stored or emitted text fields: {command}")

    vector_summary = validations.get("python scripts\\validate_vector_index.py", {}).get("summary")
    if vector_summary != EXPECTED_VECTOR_VALIDATION:
        issues.append("vector validation summary is stale or missing")
    project_summary = validations.get("python scripts\\validate_pdfrejuvenator.py", {}).get("summary")
    if project_summary != EXPECTED_PROJECT_VALIDATION:
        issues.append("project validation summary is stale or missing")

    scrub_commands = [
        "python scripts\\scrub_public_export.py --root .",
        "python scripts\\scrub_public_export.py --root public_source_export_release_summary_guard_final",
        "python scripts\\scrub_public_export.py --root package_export_release_summary_guard_final",
    ]
    for command in scrub_commands:
        summary = validations.get(command, {}).get("summary", "")
        if "findings=0" not in str(summary):
            issues.append(f"scrub evidence missing findings=0: {command}")

    boundaries = payload.get("private_data_boundaries")
    if not isinstance(boundaries, dict):
        issues.append("private_data_boundaries must be an object")
    else:
        if boundaries.get("real_data_test_distribution") != "not distributed":
            issues.append("real_data_test_distribution must be not distributed")
        if boundaries.get("private_runtime_artifacts_are_public_release_artifacts") is not False:
            issues.append("private runtime artifacts must not be public release artifacts")
        if boundaries.get("redacted_indexes_still_private") is not True:
            issues.append("redacted indexes must remain private")

    coverage = payload.get("coverage_limits")
    if not isinstance(coverage, dict):
        issues.append("coverage_limits must be an object")
    else:
        if coverage.get("coverage_is_exhaustive") is not False:
            issues.append("coverage_is_exhaustive must be false for current v0.6 evidence")
        if int(coverage.get("private_input_cases", 0)) < 7:
            issues.append("private_input_cases must be at least 7")

    blockers = payload.get("protected_action_blockers")
    if not isinstance(blockers, dict):
        issues.append("protected_action_blockers must be an object")
    else:
        for action in ("commit", "tag", "push", "package_publication", "github_release", "external_sharing", "remote_mutation"):
            if "exact human-only passcode" not in str(blockers.get(action, "")):
                issues.append(f"protected action blocker missing exact passcode boundary: {action}")

    for value in _all_strings(payload):
        lowered = value.lower()
        if any(term in lowered for term in PRIVATE_TITLE_TERMS):
            issues.append("summary contains private title or branded corpus term")
            break
    return issues


def positive_fixture() -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "release_line": "PDFRejuvenator v0.6.0 local implementation",
        "changed_files": [
            "README.md",
            "docs\\VALIDATION_GUIDE.md",
            "pdfrejuvenator\\cli.py",
            "pyproject.toml",
            "scripts\\build_public_source_export.py",
            "scripts\\validate_coverage_adequacy.py",
            "scripts\\validate_coverage_boundary.py",
            "scripts\\validate_export_manifest.py",
            "scripts\\validate_private_coverage_matrix.py",
            "scripts\\validate_release_review_summary.py",
            "scripts\\validate_pdfrejuvenator.py",
            "scripts\\validate_vector_index.py",
        ],
        "changed_file_categories": {
            "documentation": ["README.md", "docs\\VALIDATION_GUIDE.md"],
            "runtime_code": ["pdfrejuvenator\\cli.py"],
            "version_metadata": ["pyproject.toml"],
            "export_builders": ["scripts\\build_public_source_export.py"],
            "validators": [
                "scripts\\validate_coverage_adequacy.py",
                "scripts\\validate_coverage_boundary.py",
                "scripts\\validate_export_manifest.py",
                "scripts\\validate_private_coverage_matrix.py",
                "scripts\\validate_release_review_summary.py",
                "scripts\\validate_pdfrejuvenator.py",
                "scripts\\validate_vector_index.py",
            ],
        },
        "capability_areas": sorted(REQUIRED_CAPABILITIES),
        "branch_checkpoint": {"protected_actions_performed": False},
        "evidence_paths": {
            "public_source_export": "G:\\Evidence\\public_source_export_release_summary_guard_final",
            "package_export": "G:\\Evidence\\package_export_release_summary_guard_final",
        },
        "validation_results": [
            {"command": "python scripts\\validate_vector_index.py", "result": "pass", "summary": EXPECTED_VECTOR_VALIDATION},
            {"command": "python scripts\\validate_pdfrejuvenator.py", "result": "pass", "summary": EXPECTED_PROJECT_VALIDATION},
            {
                "command": "python scripts\\validate_release_review_summary.py v060_release_review_summary.json --check-paths",
                "result": "pass",
                "summary": "RELEASE REVIEW SUMMARY VALIDATION: checks=6 failures=0",
            },
            {
                "command": "python scripts\\validate_export_manifest.py public_source_export_release_summary_guard_final package_export_release_summary_guard_final",
                "result": "pass",
                "summary": "EXPORT MANIFEST VALIDATION: checks=8 failures=0",
            },
            {
                "command": "python scripts\\validate_coverage_boundary.py coverage_boundary.json --check-paths",
                "result": "pass",
                "summary": "COVERAGE BOUNDARY VALIDATION: checks=7 failures=0",
            },
            {
                "command": "python scripts\\validate_coverage_adequacy.py coverage_adequacy.json --check-paths",
                "result": "pass",
                "summary": "COVERAGE ADEQUACY VALIDATION: checks=9 failures=0",
            },
            {
                "command": "python scripts\\validate_private_coverage_matrix.py private_coverage_matrix\\coverage_matrix.json --check-paths",
                "result": "pass",
                "summary": "PRIVATE COVERAGE MATRIX VALIDATION: checks=8 failures=0",
            },
            {
                "command": "python scripts\\validate_private_coverage_matrix.py private_omit_hide_matrix\\omit_hide_matrix.json --check-paths --require-redacted",
                "result": "pass",
                "summary": "PRIVATE COVERAGE MATRIX VALIDATION: checks=8 failures=0",
            },
            {
                "command": "python scripts\\validate_private_coverage_matrix.py private_expanded_coverage_matrix\\expanded_coverage_matrix.json --check-paths --require-redacted --min-rows 3",
                "result": "pass",
                "summary": "PRIVATE COVERAGE MATRIX VALIDATION: checks=8 failures=0",
            },
            {"command": "python -m ruff check --no-cache pdfrejuvenator scripts src", "result": "pass", "summary": "All checks passed"},
            {"command": "python scripts\\scrub_public_export.py --root .", "result": "pass", "summary": "findings=0"},
            {"command": "python scripts\\scrub_public_export.py --root public_source_export_release_summary_guard_final", "result": "pass", "summary": "findings=0"},
            {"command": "python scripts\\scrub_public_export.py --root package_export_release_summary_guard_final", "result": "pass", "summary": "findings=0"},
            {"command": "targeted private/IP term scan on public surfaces", "result": "pass", "summary": "no matches"},
            {"command": "private runtime artifact name scan on public/package exports", "result": "pass", "summary": "no matches"},
            {"command": "installed package functional vector smoke", "result": "pass", "summary": "search results=2; vector text fields=0; search text fields=0"},
            {"command": "installed package validator smoke", "result": "pass", "summary": "coverage adequacy pass; private coverage matrix pass; omit-hide matrix pass; coverage boundary pass"},
            {"command": "source functional vector smoke", "result": "pass", "summary": "search results=2; vector text fields=0; search text fields=0"},
            {"command": "release-review summary path audit", "result": "pass", "summary": "evidence paths=14 missing=0; changed files=8 missing=0"},
        ],
        "private_data_boundaries": {
            "real_data_test_distribution": "not distributed",
            "private_runtime_artifacts_are_public_release_artifacts": False,
            "redacted_indexes_still_private": True,
        },
        "coverage_limits": {
            "coverage_is_exhaustive": False,
            "private_input_cases": 7,
        },
        "protected_action_blockers": {
            "commit": "blocked until exact human-only passcode for commit",
            "tag": "blocked until exact human-only passcode for tag",
            "push": "blocked until exact human-only passcode for push",
            "package_publication": "blocked until exact human-only passcode for package publication",
            "github_release": "blocked until exact human-only passcode for GitHub release",
            "external_sharing": "blocked until exact human-only passcode for external sharing",
            "remote_mutation": "blocked until exact human-only passcode for the specific remote mutation",
        },
    }


def run_checks() -> list[tuple[str, bool, str]]:
    base = positive_fixture()
    checks: list[tuple[str, bool, str]] = []
    positive_issues = validate_payload(base)
    checks.append(("valid release summary fixture", positive_issues == [], "; ".join(positive_issues)))

    private_export = copy.deepcopy(base)
    private_export["evidence_paths"]["public_source_export"] = "G:\\Evidence\\private_vector_index.json"
    private_export_issues = validate_payload(private_export)
    checks.append(("reject private index path in public export", bool(private_export_issues), "negative control should fail"))

    stored_text = copy.deepcopy(base)
    _validation_by_command(stored_text)["installed package functional vector smoke"]["summary"] = "search results=2; text fields=1"
    stored_text_issues = validate_payload(stored_text)
    checks.append(("reject stored chunk text evidence", bool(stored_text_issues), "negative control should fail"))

    missing_scrub = copy.deepcopy(base)
    _validation_by_command(missing_scrub)["python scripts\\scrub_public_export.py --root ."]["summary"] = "not run"
    missing_scrub_issues = validate_payload(missing_scrub)
    checks.append(("reject missing scrub evidence", bool(missing_scrub_issues), "negative control should fail"))

    stale_validation = copy.deepcopy(base)
    _validation_by_command(stale_validation)["python scripts\\validate_vector_index.py"]["summary"] = "VECTOR INDEX SUMMARY: checks=30 failures=0"
    stale_validation_issues = validate_payload(stale_validation)
    checks.append(("reject stale vector validation evidence", bool(stale_validation_issues), "negative control should fail"))

    uncategorized_change = copy.deepcopy(base)
    uncategorized_change["changed_files"].append("docs\\PUBLICATION_GUIDE.md")
    uncategorized_change_issues = validate_payload(uncategorized_change)
    checks.append(("reject uncategorized changed file", bool(uncategorized_change_issues), "negative control should fail"))

    missing_validator_category = copy.deepcopy(base)
    missing_validator_category["changed_file_categories"]["validators"].remove("scripts\\validate_export_manifest.py")
    missing_validator_category_issues = validate_payload(missing_validator_category)
    checks.append(("reject missing validator category coverage", bool(missing_validator_category_issues), "negative control should fail"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PDFRejuvenator v0.6 release-review summary.")
    parser.add_argument("summary", type=Path, nargs="?", help="Optional release-review summary JSON to validate.")
    parser.add_argument("--check-paths", action="store_true", help="Require evidence paths in the summary to exist.")
    args = parser.parse_args()

    checks = run_checks()
    if args.summary:
        payload = json.loads(args.summary.read_text(encoding="utf-8"))
        issues = validate_payload(payload, check_paths=args.check_paths)
        checks.append((f"summary file {args.summary}", issues == [], "; ".join(issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"RELEASE REVIEW SUMMARY VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
