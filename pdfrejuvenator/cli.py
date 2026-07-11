from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pdfrejuvenator.corpus_intake import (
    PrivacyClass,
    RightsClass,
    build_inventory_manifest,
    manifest_to_json,
    validate_manifest,
)
from pdfrejuvenator.corpus_search import (
    build_index_from_image_records,
    build_index_from_manifest,
    build_index_from_ocr_records,
    build_index_from_table_records,
    build_index_from_text_records,
)
from pdfrejuvenator.ocr_records import build_ocr_records_from_manifest
from pdfrejuvenator.private_workspace import (
    init_private_workspace,
    validate_private_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


def run_process(args: argparse.Namespace) -> int:
    source_pdf = args.source_pdf.resolve()
    if not source_pdf.exists():
        print(f"ERROR: source PDF not found: {source_pdf}", file=sys.stderr)
        return 2

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_pdf_rejuvenation.py"),
        "--source-pdf",
        str(source_pdf),
    ]
    if args.pages:
        command.extend(["--pages", args.pages])
    if args.chunk_size is not None:
        command.extend(["--chunk-size", str(args.chunk_size)])
    if args.workers is not None:
        command.extend(["--workers", str(args.workers)])
    if args.timeout_seconds is not None:
        command.extend(["--timeout-seconds", str(args.timeout_seconds)])
    if args.run_root:
        command.extend(["--run-root", str(args.run_root.resolve())])
    if args.review_output_dir:
        command.extend(["--review-output-dir", str(args.review_output_dir.resolve())])
    if args.book_id:
        command.extend(["--book-id", args.book_id])
    if args.clean:
        command.append("--clean")
    if args.force_rollout:
        command.append("--force-rollout")
    if args.skip_page_pipeline:
        command.append("--skip-page-pipeline")
    if args.skip_rollout:
        command.append("--skip-rollout")
    if args.skip_consolidated_output:
        command.append("--skip-consolidated-output")
    if args.skip_search_index:
        command.append("--skip-search-index")
    if args.validation_mode:
        command.extend(["--validation-mode", args.validation_mode])
    if args.ocr_engine:
        command.extend(["--ocr-engine", args.ocr_engine])

    return subprocess.run(command, cwd=ROOT).returncode


def run_search(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "search_local_index.py"),
        args.query,
        "--limit",
        str(args.limit),
    ]
    if args.output_dir:
        command.extend(["--output-dir", str(args.output_dir.resolve())])
    if args.index:
        command.extend(["--index", str(args.index.resolve())])
    return subprocess.run(command, cwd=ROOT).returncode


def run_inventory(args: argparse.Namespace) -> int:
    source_root = args.source_root.resolve()
    if not source_root.exists() or not source_root.is_dir():
        print(f"ERROR: source root not found or not a directory: {source_root}", file=sys.stderr)
        return 2

    manifest = build_inventory_manifest(
        source_root,
        corpus_id=args.corpus_id,
        batch_id=args.batch_id,
        privacy_class=PrivacyClass(args.privacy_class),
        rights_class=RightsClass(args.rights_class),
    )
    issues = validate_manifest(manifest)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue.path}: {issue.message}", file=sys.stderr)
        return 1

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(manifest_to_json(manifest), encoding="utf-8")
    print(f"INVENTORY MANIFEST: {output}")
    print(f"INVENTORY SUMMARY: entries={len(manifest.entries)} failures=0")
    return 0


def run_index_manifest(args: argparse.Namespace) -> int:
    manifest = args.manifest.resolve()
    if not manifest.exists():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 2
    output = args.output.resolve()
    count = build_index_from_manifest(manifest, output)
    print(f"CORPUS SEARCH INDEX: {output}")
    print(f"CORPUS SEARCH SUMMARY: records={count} failures=0")
    return 0


def run_index_text_records(args: argparse.Namespace) -> int:
    source = args.text_records.resolve()
    if not source.exists():
        print(f"ERROR: text records not found: {source}", file=sys.stderr)
        return 2
    output = args.output.resolve()
    count = build_index_from_text_records(source, output)
    print(f"TEXT SEARCH INDEX: {output}")
    print(f"TEXT SEARCH SUMMARY: records={count} failures=0")
    return 0


def run_index_table_records(args: argparse.Namespace) -> int:
    source = args.table_records.resolve()
    if not source.exists():
        print(f"ERROR: table records not found: {source}", file=sys.stderr)
        return 2
    output = args.output.resolve()
    count = build_index_from_table_records(source, output)
    print(f"TABLE SEARCH INDEX: {output}")
    print(f"TABLE SEARCH SUMMARY: records={count} failures=0")
    return 0


def run_index_image_records(args: argparse.Namespace) -> int:
    source = args.image_records.resolve()
    if not source.exists():
        print(f"ERROR: image records not found: {source}", file=sys.stderr)
        return 2
    output = args.output.resolve()
    count = build_index_from_image_records(source, output)
    print(f"IMAGE SEARCH INDEX: {output}")
    print(f"IMAGE SEARCH SUMMARY: records={count} failures=0")
    return 0


def run_index_ocr_records(args: argparse.Namespace) -> int:
    source = args.ocr_records.resolve()
    if not source.exists():
        print(f"ERROR: OCR records not found: {source}", file=sys.stderr)
        return 2
    output = args.output.resolve()
    count = build_index_from_ocr_records(source, output)
    print(f"OCR SEARCH INDEX: {output}")
    print(f"OCR SEARCH SUMMARY: records={count} failures=0")
    return 0


def run_init_private_workspace(args: argparse.Namespace) -> int:
    workspace_root = args.workspace_root.resolve()
    config = init_private_workspace(workspace_root, corpus_id=args.corpus_id)
    print(f"PRIVATE WORKSPACE: {config.workspace_root}")
    print(f"PRIVATE WORKSPACE CONFIG: {workspace_root / 'pdfrejuvenator_private_workspace.json'}")
    print("PRIVATE WORKSPACE SUMMARY: failures=0")
    return 0


def run_validate_private_workspace(args: argparse.Namespace) -> int:
    workspace_root = args.workspace_root.resolve()
    public_repo_root = args.public_repo_root.resolve() if args.public_repo_root else ROOT
    issues = validate_private_workspace(workspace_root, public_repo_root=public_repo_root)
    for issue in issues:
        print(f"ERROR: {issue.path}: {issue.message}", file=sys.stderr)
    print(f"PRIVATE WORKSPACE VALIDATION SUMMARY: issues={len(issues)} failures={len(issues)}")
    return 1 if issues else 0


def run_extract_ocr_records(args: argparse.Namespace) -> int:
    manifest = args.manifest.resolve()
    source_root = args.source_root.resolve()
    private_workspace_root = args.private_workspace_root.resolve()
    output = args.output.resolve()
    if not manifest.exists():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 2
    if not source_root.exists() or not source_root.is_dir():
        print(f"ERROR: source root not found or not a directory: {source_root}", file=sys.stderr)
        return 2
    issues = validate_private_workspace(private_workspace_root, public_repo_root=ROOT)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue.path}: {issue.message}", file=sys.stderr)
        return 1
    try:
        count = build_ocr_records_from_manifest(
            manifest,
            source_root=source_root,
            private_workspace_root=private_workspace_root,
            output=output,
        )
    except (KeyError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OCR RECORDS: {output}")
    print(f"OCR RECORDS SUMMARY: records={count} failures=0")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfrejuvenator",
        description="Convert PDF pages into editable SVG review output.",
    )
    subparsers = parser.add_subparsers(dest="command")

    process = subparsers.add_parser(
        "process",
        help="process one source PDF",
        description="Process one source PDF into editable SVG review output.",
    )
    process.add_argument("source_pdf", type=Path, help="Path to the source PDF.")
    process.add_argument("--pages", help='Optional page range for testing, e.g. "1-5".')
    process.add_argument("--clean", action="store_true", help="Delete prior output for this run before processing.")
    process.add_argument("--force-rollout", action="store_true", help="Regenerate editable SVG rollout artifacts.")
    process.add_argument("--chunk-size", type=int, default=None, help="Pages per rollout chunk.")
    process.add_argument("--workers", type=int, default=None, help="Rollout chunks to process concurrently.")
    process.add_argument("--timeout-seconds", type=int, default=None, help="Per-chunk timeout.")
    process.add_argument("--run-root", type=Path, default=None, help="Advanced: explicit internal run root.")
    process.add_argument("--review-output-dir", type=Path, default=None, help="Clean user-facing output folder. Defaults beside the source PDF.")
    process.add_argument("--book-id", default=None, help="Advanced: stable internal document id.")
    process.add_argument("--skip-page-pipeline", action="store_true", help="Advanced: reuse existing page pipeline output.")
    process.add_argument("--skip-rollout", action="store_true", help="Advanced: reuse existing rollout output.")
    process.add_argument("--skip-consolidated-output", action="store_true", help="Advanced: do not build clean user-facing output.")
    process.add_argument("--skip-search-index", action="store_true", help="Advanced: do not build the local _search index.")
    process.add_argument("--validation-mode", choices=["internal", "external"], default="internal", help="Internal fails hard; external keeps output and writes validation reports.")
    process.add_argument("--ocr-engine", choices=["pymupdf_text_blocks", "rapidocr"], default=None, help="Advanced: OCR engine for image-only or scanned PDFs.")
    process.set_defaults(func=run_process)

    search = subparsers.add_parser(
        "search",
        help="search a local PDFRejuvenator output",
        description="Search a local _search index created by PDFRejuvenator.",
    )
    search.add_argument("query", help="Search text.")
    search.add_argument("--output-dir", type=Path, default=None, help="Consolidated output directory containing _search.")
    search.add_argument("--index", type=Path, default=None, help="Explicit search_index.jsonl path.")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=run_search)

    inventory = subparsers.add_parser(
        "inventory",
        help="create an inventory-only corpus intake manifest",
        description="Scan a source root for PDFs and write a v0.4 inventory-only manifest.",
    )
    inventory.add_argument("source_root", type=Path, help="Directory containing source PDFs.")
    inventory.add_argument("--output", type=Path, required=True, help="Manifest JSON output path.")
    inventory.add_argument("--corpus-id", default="local-corpus", help="Stable corpus identifier.")
    inventory.add_argument("--batch-id", default="inventory-batch", help="Stable batch identifier.")
    inventory.add_argument(
        "--privacy-class",
        choices=[item.value for item in PrivacyClass],
        default=PrivacyClass.PRIVATE_SOURCE.value,
    )
    inventory.add_argument(
        "--rights-class",
        choices=[item.value for item in RightsClass],
        default=RightsClass.UNKNOWN_REVIEW_REQUIRED.value,
    )
    inventory.set_defaults(func=run_inventory)

    index_manifest = subparsers.add_parser(
        "index-manifest",
        help="build a local search index from a v0.4 intake manifest",
        description="Build a local JSONL search index from public-safe v0.4 intake manifest metadata.",
    )
    index_manifest.add_argument("manifest", type=Path, help="v0.4 intake manifest JSON.")
    index_manifest.add_argument("--output", type=Path, required=True, help="Search index JSONL output path.")
    index_manifest.set_defaults(func=run_index_manifest)

    index_text = subparsers.add_parser(
        "index-text-records",
        help="build a local search index from synthetic/public-safe text records",
        description="Build a local JSONL search index from synthetic or separately approved text records.",
    )
    index_text.add_argument("text_records", type=Path, help="Synthetic/public-safe text records JSON.")
    index_text.add_argument("--output", type=Path, required=True, help="Search index JSONL output path.")
    index_text.set_defaults(func=run_index_text_records)

    index_table = subparsers.add_parser(
        "index-table-records",
        help="build a local search index from synthetic/public-safe table records",
        description="Build a local JSONL search index from synthetic or separately approved table metadata records.",
    )
    index_table.add_argument("table_records", type=Path, help="Synthetic/public-safe table records JSON.")
    index_table.add_argument("--output", type=Path, required=True, help="Search index JSONL output path.")
    index_table.set_defaults(func=run_index_table_records)

    index_image = subparsers.add_parser(
        "index-image-records",
        help="build a local search index from synthetic/public-safe image records",
        description="Build a local JSONL search index from synthetic or separately approved image metadata records.",
    )
    index_image.add_argument("image_records", type=Path, help="Synthetic/public-safe image records JSON.")
    index_image.add_argument("--output", type=Path, required=True, help="Search index JSONL output path.")
    index_image.set_defaults(func=run_index_image_records)

    index_ocr = subparsers.add_parser(
        "index-ocr-records",
        help="build a local search index from private OCR records",
        description="Build a local JSONL search index from private OCR records.",
    )
    index_ocr.add_argument("ocr_records", type=Path, help="Private OCR records JSON.")
    index_ocr.add_argument("--output", type=Path, required=True, help="Search index JSONL output path.")
    index_ocr.set_defaults(func=run_index_ocr_records)

    init_private = subparsers.add_parser(
        "init-private-workspace",
        help="initialize a private local processing workspace",
        description="Create a private local workspace layout for non-public corpus processing artifacts.",
    )
    init_private.add_argument("workspace_root", type=Path, help="Private workspace root outside the public repo.")
    init_private.add_argument("--corpus-id", default="private-corpus", help="Stable private corpus identifier.")
    init_private.set_defaults(func=run_init_private_workspace)

    validate_private = subparsers.add_parser(
        "validate-private-workspace",
        help="validate a private local processing workspace",
        description="Validate the private workspace layout and public/private separation controls.",
    )
    validate_private.add_argument("workspace_root", type=Path, help="Private workspace root to validate.")
    validate_private.add_argument("--public-repo-root", type=Path, default=ROOT, help="Public repository root for separation checks.")
    validate_private.set_defaults(func=run_validate_private_workspace)

    extract_ocr = subparsers.add_parser(
        "extract-ocr-records",
        help="extract page-level OCR records into a private workspace",
        description="Extract page-level OCR text records from an intake manifest into a validated private workspace.",
    )
    extract_ocr.add_argument("manifest", type=Path, help="Intake manifest JSON.")
    extract_ocr.add_argument("--source-root", type=Path, required=True, help="Root used to resolve manifest source_path values.")
    extract_ocr.add_argument("--private-workspace-root", type=Path, required=True, help="Validated private workspace root.")
    extract_ocr.add_argument("--output", type=Path, required=True, help="Private workspace OCR records JSON output.")
    extract_ocr.set_defaults(func=run_extract_ocr_records)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)
