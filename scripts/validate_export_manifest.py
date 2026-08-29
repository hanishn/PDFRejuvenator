from __future__ import annotations

import argparse
from pathlib import Path


PRIVATE_RUNTIME_JSON_NAMES = {
    "coverage_matrix.json",
    "coverage_boundary.json",
    "private_index_boundary.json",
}

REQUIRED_PUBLIC_VALIDATOR = Path("scripts") / "validate_release_review_summary.py"
REQUIRED_ANSWER_QUERY_FILES = {
    Path("docs") / "ANSWER_QUERY.md",
    Path("pdfrejuvenator") / "answering.py",
    Path("scripts") / "assert_answer_provider_failure.py",
    Path("scripts") / "assert_answer_query_output.py",
    Path("scripts") / "assert_malformed_vector_index.py",
    Path("scripts") / "assert_redacted_answer_query_output.py",
    Path("scripts") / "validate_answer_query.py",
    Path("tests") / "playwright" / "answer-query.spec.js",
}


def _relative_files(root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())


def _private_runtime_matches(files: list[Path]) -> list[str]:
    matches: list[str] = []
    for file_path in files:
        lowered_name = file_path.name.lower()
        if lowered_name in PRIVATE_RUNTIME_JSON_NAMES:
            matches.append(str(file_path))
        elif lowered_name.startswith("answer_query") and file_path.suffix.lower() in {".json", ".jsonl"}:
            matches.append(str(file_path))
        elif lowered_name.startswith("answer_results") and file_path.suffix.lower() in {".json", ".jsonl"}:
            matches.append(str(file_path))
        elif lowered_name.startswith("search_results") and file_path.suffix.lower() == ".jsonl":
            matches.append(str(file_path))
        elif "vector_index" in lowered_name and file_path.suffix.lower() == ".json":
            matches.append(str(file_path))
    return matches


def _bytecode_matches(files: list[Path]) -> list[str]:
    return [
        str(file_path)
        for file_path in files
        if "__pycache__" in file_path.parts or file_path.suffix == ".pyc"
    ]


def validate_export_root(root: Path, label: str) -> list[str]:
    issues: list[str] = []
    if not root.exists() or not root.is_dir():
        return [f"{label} export root does not exist or is not a directory: {root}"]

    files = _relative_files(root)
    if not files:
        issues.append(f"{label} export root is empty: {root}")

    missing_validator = not (root / REQUIRED_PUBLIC_VALIDATOR).exists()
    if missing_validator:
        issues.append(f"{label} export is missing {REQUIRED_PUBLIC_VALIDATOR}")
    for required_answer_file in sorted(REQUIRED_ANSWER_QUERY_FILES):
        if not (root / required_answer_file).exists():
            issues.append(f"{label} export is missing answer-query file {required_answer_file}")

    private_matches = _private_runtime_matches(files)
    if private_matches:
        issues.append(f"{label} export contains private runtime artifact names: {', '.join(private_matches[:5])}")

    bytecode_matches = _bytecode_matches(files)
    if bytecode_matches:
        issues.append(f"{label} export contains bytecode/cache files: {', '.join(bytecode_matches[:5])}")

    return issues


def run_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    public_fixture = [Path("scripts") / "validate_release_review_summary.py", Path("README.md")]
    checks.append(("accept public export fixture", _private_runtime_matches(public_fixture) == [], "fixture should pass"))

    private_index_fixture = [Path("outputs") / "vector_index_ollama.json", *public_fixture]
    private_index_matches = _private_runtime_matches(private_index_fixture)
    checks.append(("reject private vector index artifact", bool(private_index_matches), "negative control should fail"))

    search_results_fixture = [Path("outputs") / "search_results_hidden_text.jsonl", *public_fixture]
    search_results_matches = _private_runtime_matches(search_results_fixture)
    checks.append(("reject vector search result artifact", bool(search_results_matches), "negative control should fail"))

    answer_results_fixture = [Path("outputs") / "answer_query_private.json", *public_fixture]
    answer_results_matches = _private_runtime_matches(answer_results_fixture)
    checks.append(("reject answer query result artifact", bool(answer_results_matches), "negative control should fail"))

    coverage_fixture = [Path("evidence") / "coverage_matrix.json", *public_fixture]
    coverage_matches = _private_runtime_matches(coverage_fixture)
    checks.append(("reject private coverage artifact", bool(coverage_matches), "negative control should fail"))

    bytecode_fixture = [Path("pdfrejuvenator") / "__pycache__" / "cli.cpython-312.pyc", *public_fixture]
    bytecode_matches = _bytecode_matches(bytecode_fixture)
    checks.append(("reject bytecode cache artifact", bool(bytecode_matches), "negative control should fail"))

    missing_validator_fixture = [Path("README.md")]
    missing_validator = REQUIRED_PUBLIC_VALIDATOR not in missing_validator_fixture
    checks.append(("reject missing release summary validator", missing_validator, "negative control should fail"))

    missing_answer_query_fixture = [REQUIRED_PUBLIC_VALIDATOR, Path("README.md")]
    missing_answer_query = any(required not in missing_answer_query_fixture for required in REQUIRED_ANSWER_QUERY_FILES)
    checks.append(("reject answer-query export drift", missing_answer_query, "negative control should fail"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate public/package export manifests for private runtime artifacts.")
    parser.add_argument("public_export", type=Path, nargs="?")
    parser.add_argument("package_export", type=Path, nargs="?")
    args = parser.parse_args()

    checks = run_checks()
    if args.public_export is not None:
        public_issues = validate_export_root(args.public_export.resolve(), "public source")
        checks.append(("actual public source export manifest", public_issues == [], "; ".join(public_issues)))
    if args.package_export is not None:
        package_issues = validate_export_root(args.package_export.resolve(), "package")
        checks.append(("actual package export manifest", package_issues == [], "; ".join(package_issues)))

    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, detail in failures:
        print(f"FAIL: {name} - {detail}")
    print(f"EXPORT MANIFEST VALIDATION: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
