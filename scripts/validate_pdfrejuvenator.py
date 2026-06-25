from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
PACKAGE = ROOT / "pdfrejuvenator"

CORE_SCRIPT_IMPORTS = [
    "pdfrejuvenator",
    "pdfrejuvenator.cli",
    "build_consolidated_review_output",
    "build_full_book_review_packet",
    "build_local_search_index",
    "build_pdfrejuvenator_package",
    "build_public_source_export",
    "render_inkscape_visual_comparisons",
    "rollout_chapter_table_cell_editability",
    "run_full_book_rollout_chunks",
    "run_pdf_batch",
    "run_pdf_book",
    "run_pdf_rejuvenation",
    "search_local_index",
    "validate_consolidated_review_output",
]

REQUIRED_RUNTIME_MODULES = [
    "fitz",
    "fontTools",
    "numpy",
    "PIL",
    "reportlab",
]

OPTIONAL_RUNTIME_MODULES = [
    "cv2",
    "rapidocr_onnxruntime",
]

DEV_TOOL_MODULES = [
    "pytest",
    "ruff",
]


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


def iter_python_files() -> list[Path]:
    return sorted([*SCRIPTS.glob("*.py"), *SRC.rglob("*.py"), *PACKAGE.rglob("*.py")])


def compile_python_files() -> list[CheckResult]:
    results: list[CheckResult] = []
    for path in iter_python_files():
        rel = path.relative_to(ROOT)
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            results.append(CheckResult(f"compile {rel}", "FAIL", str(exc)))
        else:
            results.append(CheckResult(f"compile {rel}", "PASS"))
    return results


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def check_modules(module_names: list[str], required: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    missing_status = "FAIL" if required else "WARN"
    for module_name in module_names:
        if module_available(module_name):
            results.append(CheckResult(f"module {module_name}", "PASS"))
        else:
            results.append(CheckResult(f"module {module_name}", missing_status, "not importable"))
    return results


def import_core_scripts() -> list[CheckResult]:
    results: list[CheckResult] = []
    sys.path.insert(0, str(SCRIPTS))
    sys.path.insert(0, str(SRC))
    sys.path.insert(0, str(ROOT))
    for module_name in CORE_SCRIPT_IMPORTS:
        try:
            __import__(module_name)
        except Exception as exc:  # noqa: BLE001 - validation must report all import failures.
            results.append(CheckResult(f"import {module_name}", "FAIL", f"{type(exc).__name__}: {exc}"))
        else:
            results.append(CheckResult(f"import {module_name}", "PASS"))
    return results


def print_results(results: list[CheckResult], verbose: bool) -> None:
    for result in results:
        if result.status == "PASS" and not verbose:
            continue
        line = f"{result.status}: {result.name}"
        if result.detail:
            line += f" - {result.detail}"
        print(line)


def main() -> int:
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description="Run PDFRejuvenator baseline validation checks.")
    parser.add_argument("--verbose", action="store_true", help="Print passing checks as well as failures/warnings.")
    args = parser.parse_args()

    results: list[CheckResult] = []
    results.extend(compile_python_files())
    results.extend(check_modules(REQUIRED_RUNTIME_MODULES, required=True))
    results.extend(check_modules(OPTIONAL_RUNTIME_MODULES, required=False))
    results.extend(check_modules(DEV_TOOL_MODULES, required=False))
    results.extend(import_core_scripts())

    failures = [result for result in results if result.status == "FAIL"]
    warnings = [result for result in results if result.status == "WARN"]

    print_results(results, verbose=args.verbose)
    print(f"SUMMARY: checks={len(results)} failures={len(failures)} warnings={len(warnings)}")

    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"- {warning.name}: {warning.detail}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
