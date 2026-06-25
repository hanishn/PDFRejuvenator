from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)
