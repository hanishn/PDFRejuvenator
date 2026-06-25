from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_STAGED = ROOT / "source" / "source.pdf"
DEFAULT_OUTPUTS_ROOT = ROOT / "outputs" / "pdf_runs"


def slugify_pdf_stem(path: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").lower()
    return slug[:32] or "source_pdf"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_run_identity(source_pdf: Path) -> tuple[str, str]:
    source_hash = sha256_file(source_pdf)
    slug = slugify_pdf_stem(source_pdf)
    run_id = f"{slug}_{source_hash[:8]}"
    return run_id, source_hash


def assert_existing_pipeline_matches(pipeline_root: Path, source_hash: str, book_id: str) -> None:
    manifest_path = pipeline_root / "book_manifest.json"
    if not manifest_path.exists():
        return
    manifest = read_json(manifest_path)
    existing_hash = manifest.get("source_pdf_sha256")
    existing_book_id = manifest.get("book_id")
    if existing_hash and existing_hash != source_hash:
        raise SystemExit(
            "existing pipeline belongs to a different source PDF. "
            f"Use --clean or a different --run-root. Existing={existing_hash[:12]} requested={source_hash[:12]}"
        )
    if existing_book_id and existing_book_id != book_id:
        raise SystemExit(
            "existing pipeline belongs to a different book id. "
            f"Use --clean or a different --run-root. Existing={existing_book_id} requested={book_id}"
        )


def run_command(command: list[str], timeout: int | None = None) -> None:
    print("RUN " + " ".join(f'"{part}"' if " " in part else part for part in command), flush=True)
    started = time.time()
    proc = subprocess.run(command, cwd=ROOT, text=True, timeout=timeout)
    duration = round(time.time() - started, 1)
    if proc.returncode != 0:
        raise SystemExit(f"command failed with exit code {proc.returncode} after {duration}s")
    print(f"DONE exit=0 seconds={duration}", flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def stage_source_pdf(source_pdf: Path, staged_pdf: Path) -> Path:
    staged_pdf.parent.mkdir(parents=True, exist_ok=True)
    if source_pdf.resolve() != staged_pdf.resolve():
        shutil.copy2(source_pdf, staged_pdf)
    return staged_pdf


def write_gate_report(
    source_pdf: Path,
    page_count: int,
    skip_page_pipeline: bool,
    run_root: Path,
    pipeline_root: Path,
    package_root: Path,
    acceptance_root: Path,
    packet_root: Path,
    report_stem: str,
) -> None:
    rollout_report = read_json(package_root / f"{report_stem}_report.json")
    report = {
        "status": rollout_report.get("status", "UNKNOWN"),
        "mode": "full",
        "source_pdf": {
            "path": str(source_pdf),
            "page_count": page_count,
        },
        "pages_requested": list(range(1, page_count + 1)),
        "pipeline_root": str(pipeline_root),
        "package_root": str(package_root),
        "acceptance_root": str(acceptance_root),
        "skip_page_pipeline": skip_page_pipeline,
        "rollout": {
            "status": rollout_report.get("status"),
            "pages_processed": rollout_report.get("pages_processed"),
            "failures": rollout_report.get("failures", []),
        },
        "audit": {
            "status": "PASS" if rollout_report.get("status") == "PASS" else "FAIL",
            "errors": rollout_report.get("failures", []),
            "warnings": [],
        },
        "review_files": [],
    }
    lines = [
        "# Full Book Promotion Gate",
        "",
        f"Status: `{report['status']}`",
        f"Source PDF: `{source_pdf}`",
        f"PDF page count: `{page_count}`",
        f"Pipeline root: `{pipeline_root}`",
        f"Package root: `{package_root}`",
        f"Review packet: `{packet_root}`",
        "",
    ]
    write_json(run_root / "full_full_book_promotion_gate_report.json", report)
    (run_root / "full_full_book_promotion_gate_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate an editable SVG review packet from a source PDF.")
    parser.add_argument("--source-pdf", type=Path, default=DEFAULT_SOURCE_STAGED, help="Source PDF.")
    parser.add_argument("--run-root", type=Path, default=None, help="Output root for this complete regeneration run. Defaults to outputs\\pdf_runs\\<short-pdf-name>_<hash>\\full.")
    parser.add_argument("--book-id", default=None, help="Stable book id for generated page ids. Defaults to the PDF-derived run id.")
    parser.add_argument("--staged-source-pdf", type=Path, default=None, help="Where to copy the source PDF before processing. Defaults to source\\<pdf-name>_<hash>.pdf.")
    parser.add_argument("--report-stem", default=None, help="Rollout report stem. Defaults to <book-id>_rollout.")
    parser.add_argument("--review-output-dir", type=Path, default=None, help="Clean user-facing output folder. Defaults beside the source PDF.")
    parser.add_argument("--skip-consolidated-output", action="store_true", help="Do not build the clean user-facing output folder.")
    parser.add_argument("--skip-search-index", action="store_true", help="Do not build the local _search index.")
    parser.add_argument("--validation-mode", choices=["internal", "external"], default="internal", help="Internal mode fails hard; external mode keeps output and writes validation reports.")
    parser.add_argument("--pages", default=None, help="Optional page range for testing, e.g. 1-5. Defaults to the full PDF.")
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--workers", type=int, default=1, help="Number of rollout chunks to run concurrently.")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--skip-page-pipeline", action="store_true", help="Reuse existing page pipeline manifests.")
    parser.add_argument("--skip-rollout", action="store_true", help="Reuse existing editable SVG rollout.")
    parser.add_argument("--clean", action="store_true", help="Delete the full output folder before regenerating.")
    parser.add_argument("--force-rollout", action="store_true", help="Force rollout chunks even when complete page records exist.")
    args = parser.parse_args()

    source_pdf = args.source_pdf.resolve()
    if not source_pdf.exists():
        raise SystemExit(f"missing source PDF: {source_pdf}")

    run_id, source_hash = default_run_identity(source_pdf)
    book_id = args.book_id or run_id
    report_stem = args.report_stem or f"{book_id}_rollout"
    staged_source_pdf = (args.staged_source_pdf or (ROOT / "source" / f"{run_id}.pdf")).resolve()
    run_root = (args.run_root or (DEFAULT_OUTPUTS_ROOT / run_id / "full")).resolve()

    pipeline_root = run_root / "pipeline"
    package_root = run_root / "editable_svg_rollout"
    acceptance_root = run_root / "acceptance"
    packet_root = run_root / "PDFREJUVENATOR_REVIEW_PACKET"

    if args.clean and run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    acceptance_root.mkdir(parents=True, exist_ok=True)

    assert_existing_pipeline_matches(pipeline_root, source_hash, book_id)
    staged_pdf = stage_source_pdf(source_pdf, staged_source_pdf)
    with fitz.open(staged_pdf) as doc:
        page_count = doc.page_count
    pages = args.pages or f"1-{page_count}"

    if not args.skip_page_pipeline:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_pdf_book.py"),
            "--source-pdf",
            str(staged_pdf),
            "--output-root",
            str(pipeline_root),
            "--book-id",
            book_id,
            "--page-start",
            pages.split("-", 1)[0] if "-" in pages and "," not in pages else "1",
            "--page-end",
            pages.split("-", 1)[1] if "-" in pages and "," not in pages else str(page_count),
        ]
        if args.clean:
            command.append("--clean")
        run_command(command)
    elif not (pipeline_root / "pages").exists():
        raise SystemExit(f"--skip-page-pipeline requested but no pipeline pages folder exists: {pipeline_root / 'pages'}")

    if not args.skip_rollout:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_full_book_rollout_chunks.py"),
            "--pages",
            pages,
            "--chunk-size",
            str(args.chunk_size),
            "--workers",
            str(args.workers),
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--output-root",
            str(pipeline_root),
            "--package-root",
            str(package_root),
            "--log-root",
            str(acceptance_root / "chunked_rollout_logs"),
            "--report-stem",
            report_stem,
        ]
        if args.force_rollout:
            command.append("--force")
        run_command(command)

    write_gate_report(
        staged_pdf,
        page_count,
        skip_page_pipeline=args.skip_page_pipeline,
        run_root=run_root,
        pipeline_root=pipeline_root,
        package_root=package_root,
        acceptance_root=acceptance_root,
        packet_root=packet_root,
        report_stem=report_stem,
    )
    run_command(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_full_book_review_packet.py"),
            "--run-root",
            str(run_root),
            "--report-stem",
            report_stem,
        ]
    )
    packet_zip = run_root / "PDFREJUVENATOR_REVIEW_PACKET.zip"
    if packet_zip.exists():
        packet_zip.unlink()
    shutil.make_archive(str(packet_zip.with_suffix("")), "zip", packet_root)

    if not args.skip_consolidated_output:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "build_consolidated_review_output.py"),
            "--run-root",
            str(run_root),
            "--source-pdf",
            str(source_pdf),
            "--report-stem",
            report_stem,
        ]
        if args.review_output_dir:
            command.extend(["--output-dir", str(args.review_output_dir.resolve())])
        if args.clean:
            command.append("--clean")
        run_command(command)
        output_dir = args.review_output_dir.resolve() if args.review_output_dir else source_pdf.with_name(f"{source_pdf.stem}_pdfrejuvenator_output")
        if not args.skip_search_index:
            run_command(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_local_search_index.py"),
                    "--run-root",
                    str(run_root),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        run_command(
            [
                sys.executable,
                str(ROOT / "scripts" / "validate_consolidated_review_output.py"),
                str(output_dir),
                "--mode",
                args.validation_mode,
            ]
        )

    print(f"REVIEW_PACKET={packet_root}")
    print(f"REVIEW_PACKET_ZIP={packet_zip}")
    print(f"DASHBOARD={packet_root / 'pdfrejuvenator_review_dashboard.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
