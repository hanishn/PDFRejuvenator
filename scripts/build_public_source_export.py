from __future__ import annotations

import argparse
import shutil
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
    "scrub_public_export.py",
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
    "GITHUB_PUBLICATION_CHECKLIST.md",
    "OUTPUT_GUIDE.md",
    "PRIVATE_OCR_RECORDS.md",
    "PRIVATE_TABLE_RECORDS.md",
    "PRIVATE_WORKSPACE_ARCHITECTURE.md",
    "PUBLICATION_GUIDE.md",
    "SEARCHABILITY_VALIDATION_PLAN.md",
    "VALIDATION_GUIDE.md",
]

REQUIREMENT_FILES = [
    "pdfrejuvenator_requirements.txt",
]

GITIGNORE = """# Python
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/
venv/

# PDFRejuvenator generated/local data
outputs/
source/
source_pdfs/
*_pdfrejuvenator_output/
PDFREJUVENATOR_REVIEW_PACKET/
PDFREJUVENATOR_REVIEW_PACKET.zip

# Private/local fixtures
configs/private/
private_fixtures/
*.pdf
!samples/**/*.pdf

# OS/editor noise
.DS_Store
Thumbs.db
"""


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
            raise SystemExit(f"missing public export source file: {source}")
        shutil.copy2(source, target_dir / name)


def build_export(output_dir: Path, clean: bool) -> Path:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copy_tree(ROOT / "pdfrejuvenator", output_dir / "pdfrejuvenator")
    copy_tree(ROOT / "src", output_dir / "src")
    copy_tree(ROOT / ".github", output_dir / ".github")
    copy_files(ROOT / "scripts", output_dir / "scripts", SCRIPT_ALLOWLIST)
    copy_files(ROOT, output_dir, ROOT_FILES)
    copy_files(ROOT / "docs", output_dir / "docs", DOC_FILES)
    copy_files(ROOT / "requirements", output_dir / "requirements", REQUIREMENT_FILES)
    copy_samples(ROOT / "samples", output_dir / "samples")

    (output_dir / "configs").mkdir(exist_ok=True)
    (output_dir / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a public-source PDFRejuvenator export for GitHub staging.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    output_dir = build_export(args.output_dir.resolve(), clean=args.clean)
    print(f"PUBLIC_EXPORT_DIR={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
