from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_pdf_rejuvenation.py"


def discover_pdfs(paths: list[Path], recursive: bool) -> list[Path]:
    pdfs: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and resolved.suffix.lower() == ".pdf":
            pdfs[str(resolved).lower()] = resolved
        elif resolved.is_dir():
            iterator = resolved.rglob("*.pdf") if recursive else resolved.glob("*.pdf")
            for pdf in iterator:
                pdfs[str(pdf.resolve()).lower()] = pdf.resolve()
        else:
            raise SystemExit(f"PDF path does not exist or is not a PDF/directory: {path}")
    return [pdfs[key] for key in sorted(pdfs)]


def build_command(args: argparse.Namespace, pdf: Path) -> list[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--source-pdf",
        str(pdf),
        "--chunk-size",
        str(args.chunk_size),
        "--workers",
        str(args.rollout_workers),
        "--timeout-seconds",
        str(args.timeout_seconds),
    ]
    if args.pages:
        command.extend(["--pages", args.pages])
    if args.clean:
        command.append("--clean")
    if args.force_rollout:
        command.append("--force-rollout")
    if args.skip_rollout:
        command.append("--skip-rollout")
    if args.skip_page_pipeline:
        command.append("--skip-page-pipeline")
    return command


def run_one(args: argparse.Namespace, pdf: Path, log_root: Path) -> dict[str, Any]:
    label = pdf.stem[:80]
    started = time.time()
    log_path = log_root / f"{started:.0f}_{label}.log"
    command = build_command(args, pdf)
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    duration = round(time.time() - started, 1)
    log_path.write_text(
        "\n".join(
            [
                "command:",
                " ".join(command),
                "",
                f"duration_seconds={duration}",
                f"returncode={proc.returncode}",
                "",
                "stdout:",
                proc.stdout,
                "",
                "stderr:",
                proc.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return {
        "pdf": str(pdf),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "duration_seconds": duration,
        "log": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDFRejuvenator complete regeneration for a batch of PDFs.")
    parser.add_argument("--pdf", type=Path, action="append", default=[], help="PDF file or directory. Can be repeated.")
    parser.add_argument("--recursive", action="store_true", help="Search supplied directories recursively.")
    parser.add_argument("--book-workers", type=int, default=2, help="Number of books to process concurrently.")
    parser.add_argument("--rollout-workers", type=int, default=2, help="Per-book rollout chunks to process concurrently.")
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--pages", default=None, help="Optional smoke-test page range applied to every PDF, e.g. 1-3.")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--force-rollout", action="store_true")
    parser.add_argument("--skip-page-pipeline", action="store_true")
    parser.add_argument("--skip-rollout", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-root", type=Path, default=ROOT / "outputs" / "batch_runs")
    args = parser.parse_args()

    if args.book_workers < 1:
        raise SystemExit("--book-workers must be >= 1")
    if args.rollout_workers < 1:
        raise SystemExit("--rollout-workers must be >= 1")

    inputs = list(args.pdf)
    if not inputs:
        raise SystemExit("no PDFs supplied. Use --pdf with a PDF file or directory.")

    pdfs = discover_pdfs(inputs, recursive=args.recursive)
    if not pdfs:
        raise SystemExit("no PDFs discovered")

    run_stamp = time.strftime("%Y%m%d_%H%M%S")
    log_root = (args.log_root / run_stamp).resolve()
    log_root.mkdir(parents=True, exist_ok=True)

    print(json.dumps({"status": "START", "pdfs": len(pdfs), "book_workers": args.book_workers, "rollout_workers": args.rollout_workers, "log_root": str(log_root)}, sort_keys=True), flush=True)
    for pdf in pdfs:
        print(json.dumps({"pdf": str(pdf), "command": build_command(args, pdf)}, sort_keys=True), flush=True)

    if args.dry_run:
        return 0

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.book_workers) as executor:
        future_to_pdf = {executor.submit(run_one, args, pdf, log_root): pdf for pdf in pdfs}
        for future in as_completed(future_to_pdf):
            result = future.result()
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)

    summary = {
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "pdfs": len(pdfs),
        "passed": sum(1 for item in results if item["status"] == "PASS"),
        "failed": sum(1 for item in results if item["status"] != "PASS"),
        "results": sorted(results, key=lambda item: item["pdf"]),
    }
    summary_path = log_root / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "summary": str(summary_path)}, sort_keys=True), flush=True)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
