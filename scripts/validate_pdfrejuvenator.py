from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
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
    "validate_corpus_intake",
    "validate_corpus_search",
    "validate_ocr_records",
    "validate_ocr_search",
    "validate_private_workspace",
    "validate_table_records",
    "validate_vector_index",
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


def synthetic_ocr_record(region_id: str, text: str, bbox: tuple[float, float, float, float]) -> dict[str, object]:
    return {
        "region_id": region_id,
        "text": text,
        "bbox_points": list(bbox),
    }


def check_ocr_table_structural_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SRC))
    from doc_pipeline import export_ocr_table_csvs  # noqa: PLC0415

    false_positive_records = [
        synthetic_ocr_record("fp_title", "Damage Table", (34.0, 100.0, 112.0, 112.0)),
        synthetic_ocr_record("fp_l1", "left column prose", (34.0, 124.0, 210.0, 136.0)),
        synthetic_ocr_record("fp_r1", "right column unrelated prose", (430.0, 124.0, 578.0, 136.0)),
        synthetic_ocr_record("fp_l2", "left column prose", (35.0, 146.0, 211.0, 158.0)),
        synthetic_ocr_record("fp_r2", "right column unrelated prose", (428.0, 146.0, 577.0, 158.0)),
        synthetic_ocr_record("fp_l3", "left column prose", (35.0, 168.0, 212.0, 180.0)),
        synthetic_ocr_record("fp_r3", "right column unrelated prose", (429.0, 168.0, 576.0, 180.0)),
    ]
    compact_table_records = [
        synthetic_ocr_record("ok_title", "Experience Table", (318.0, 100.0, 420.0, 112.0)),
        synthetic_ocr_record("ok_l1", "1", (318.0, 124.0, 334.0, 136.0)),
        synthetic_ocr_record("ok_r1", "100", (430.0, 124.0, 462.0, 136.0)),
        synthetic_ocr_record("ok_l2", "2", (318.0, 146.0, 334.0, 158.0)),
        synthetic_ocr_record("ok_r2", "200", (430.0, 146.0, 462.0, 158.0)),
        synthetic_ocr_record("ok_l3", "3", (318.0, 168.0, 334.0, 180.0)),
        synthetic_ocr_record("ok_r3", "300", (430.0, 168.0, 462.0, 180.0)),
    ]
    numeric_eof_records = [
        synthetic_ocr_record("num_l1", "10-19", (40.0, 100.0, 80.0, 112.0)),
        synthetic_ocr_record("num_r1", "result one", (128.0, 100.0, 220.0, 112.0)),
        synthetic_ocr_record("num_l2", "20-29", (40.0, 122.0, 80.0, 134.0)),
        synthetic_ocr_record("num_r2", "result two", (128.0, 122.0, 220.0, 134.0)),
        synthetic_ocr_record("num_l3", "30-39", (40.0, 144.0, 80.0, 156.0)),
        synthetic_ocr_record("num_r3", "result three", (128.0, 144.0, 220.0, 156.0)),
    ]
    config = {"tables": {"ocr_reconstruction_enabled": True, "ocr_row_tolerance_points": 5.0}}
    results: list[CheckResult] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        false_tables = export_ocr_table_csvs(false_positive_records, "fixture_false", temp_path / "false", config)
        compact_tables = export_ocr_table_csvs(compact_table_records, "fixture_table", temp_path / "compact", config)
        numeric_tables = export_ocr_table_csvs(numeric_eof_records, "fixture_numeric", temp_path / "numeric", config)
    results.append(CheckResult(
        "ocr table structural negative fixture",
        "PASS" if len(false_tables) == 0 else "FAIL",
        f"expected 0 false tables, got {len(false_tables)}",
    ))
    results.append(CheckResult(
        "ocr compact title table fixture",
        "PASS" if len(compact_tables) == 1 else "FAIL",
        f"expected 1 compact table, got {len(compact_tables)}",
    ))
    results.append(CheckResult(
        "ocr numeric eof flush fixture",
        "PASS" if len(numeric_tables) == 1 else "FAIL",
        f"expected 1 numeric table, got {len(numeric_tables)}",
    ))
    return results


def check_page_selection_helpers() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from run_pdf_book import parse_pages  # noqa: PLC0415
    from run_pdf_rejuvenation import page_pipeline_bounds  # noqa: PLC0415

    checks = [
        ("page parse range", parse_pages("1-3") == [1, 2, 3], "1-3 should parse to [1, 2, 3]"),
        ("page parse sparse", parse_pages("1,5") == [1, 5], "1,5 should parse to [1, 5]"),
        ("page bounds single", page_pipeline_bounds("31", 100) == ("31", "31"), "single page should stay bounded"),
        ("page bounds sparse", page_pipeline_bounds("1,5", 100) == (None, None), "sparse pages should route to --pages"),
    ]
    return [CheckResult(name, "PASS" if passed else "FAIL", detail) for name, passed, detail in checks]


def check_corpus_intake_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_corpus_intake import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"corpus intake {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_corpus_search_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_corpus_search import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"corpus search {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_private_workspace_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_private_workspace import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"private workspace {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_ocr_records_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_ocr_records import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"ocr records {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_ocr_search_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_ocr_search import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"ocr search {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_table_records_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_table_records import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"table records {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


def check_vector_index_validation() -> list[CheckResult]:
    sys.path.insert(0, str(SCRIPTS))
    from validate_vector_index import run_checks  # noqa: PLC0415

    checks = run_checks()
    return [
        CheckResult(f"vector index {name}", "PASS" if passed else "FAIL", detail)
        for name, passed, detail in checks
    ]


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
    results.extend(check_ocr_table_structural_validation())
    results.extend(check_page_selection_helpers())
    results.extend(check_corpus_intake_validation())
    results.extend(check_corpus_search_validation())
    results.extend(check_private_workspace_validation())
    results.extend(check_ocr_records_validation())
    results.extend(check_ocr_search_validation())
    results.extend(check_table_records_validation())
    results.extend(check_vector_index_validation())

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
