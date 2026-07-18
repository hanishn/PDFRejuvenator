from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCRIPT_ALLOWLIST = [
    "build_consolidated_review_output.py",
    "build_full_book_review_packet.py",
    "build_local_search_index.py",
    "build_pdfrejuvenator_package.py",
    "build_public_source_export.py",
    "render_inkscape_visual_comparisons.py",
    "rollout_chapter_table_cell_editability.py",
    "run_full_book_rollout_chunks.py",
    "run_pdf_batch.py",
    "run_pdf_book.py",
    "run_pdf_rejuvenation.py",
    "search_local_index.py",
    "generate_public_sample_pdf.py",
    "validate_consolidated_review_output.py",
    "validate_corpus_intake.py",
    "validate_corpus_search.py",
    "validate_ocr_records.py",
    "validate_ocr_search.py",
    "validate_pdfrejuvenator.py",
    "validate_private_workspace.py",
    "validate_table_records.py",
    "validate_vector_index.py",
]

ROOT_FILES = [
    "CONTRIBUTING.md",
    "install_pdfrejuvenator.bat",
    "LICENSE",
    "process_pdf.bat",
    "process_pdf_batch.bat",
    "pyproject.toml",
    "README.md",
    "README_COMMAND_LINE_HANDOFF.md",
]

DOC_FILES = [
    "CORPUS_INTAKE_ARCHITECTURE.md",
    "OUTPUT_GUIDE.md",
    "PRIVATE_OCR_RECORDS.md",
    "PRIVATE_TABLE_RECORDS.md",
    "PRIVATE_WORKSPACE_ARCHITECTURE.md",
    "SEARCHABILITY_VALIDATION_PLAN.md",
    "VALIDATION_GUIDE.md",
    "VECTOR_INDEX.md",
]

REQUIREMENT_FILES = [
    "pdfrejuvenator_requirements.txt",
]


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def copy_samples(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*_pdfrejuvenator_output",
        ),
    )


def copy_files(source_dir: Path, target_dir: Path, names: list[str]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        source = source_dir / name
        if not source.exists():
            raise SystemExit(f"missing package source file: {source}")
        shutil.copy2(source, target_dir / name)


def build_package(output_dir: Path, source_pdfs: list[Path], clean: bool) -> Path:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copy_tree(ROOT / "pdfrejuvenator", output_dir / "pdfrejuvenator")
    copy_tree(ROOT / "src", output_dir / "src")
    copy_files(ROOT / "scripts", output_dir / "scripts", SCRIPT_ALLOWLIST)
    copy_files(ROOT, output_dir, ROOT_FILES)
    copy_files(ROOT / "docs", output_dir / "docs", DOC_FILES)
    copy_files(ROOT / "requirements", output_dir / "requirements", REQUIREMENT_FILES)
    copy_samples(ROOT / "samples", output_dir / "samples")

    (output_dir / "configs").mkdir(exist_ok=True)
    source_dir = output_dir / "source_pdfs"
    source_dir.mkdir(exist_ok=True)
    for source_pdf in source_pdfs:
        resolved = source_pdf.resolve()
        if not resolved.exists() or resolved.suffix.lower() != ".pdf":
            raise SystemExit(f"source PDF not found or not a PDF: {source_pdf}")
        shutil.copy2(resolved, source_dir / resolved.name)

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a scrubbed PDFRejuvenator command-line package.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--source-pdf", type=Path, action="append", default=[], help="Optional PDF to include under source_pdfs. Can be repeated.")
    parser.add_argument("--zip", action="store_true", help="Create a ZIP next to the package directory.")
    parser.add_argument("--clean", action="store_true", help="Delete existing output directory before building.")
    args = parser.parse_args()

    if args.output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ROOT / "outputs" / "delivery_packages" / f"PDFRejuvenator_v0.5_{stamp}"
    else:
        output_dir = args.output_dir.resolve()

    package_dir = build_package(output_dir, args.source_pdf, clean=args.clean)
    print(f"PACKAGE_DIR={package_dir}")

    if args.zip:
        archive = shutil.make_archive(str(package_dir), "zip", package_dir)
        print(f"PACKAGE_ZIP={archive}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
