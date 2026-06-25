from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "pdfrejuvenator_rollout" / "pipeline"
DEFAULT_PACKAGE_ROOT = ROOT / "outputs" / "pdfrejuvenator_rollout" / "editable_svg_rollout"
DEFAULT_LOG_ROOT = ROOT / "outputs" / "pdfrejuvenator_rollout" / "acceptance" / "chunked_rollout_logs"
ROLLOUT_SCRIPT = ROOT / "scripts" / "rollout_chapter_table_cell_editability.py"


def parse_pages(value: str) -> list[int]:
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(item.strip()) for item in part.split("-", 1)]
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def make_chunks(pages: list[int], chunk_size: int) -> list[list[int]]:
    return [pages[index : index + chunk_size] for index in range(0, len(pages), chunk_size)]


def chunk_label(chunk: list[int]) -> str:
    if len(chunk) == 1:
        return f"{chunk[0]:03d}"
    return f"{chunk[0]:03d}-{chunk[-1]:03d}"


def page_filter_for_chunk(chunk: list[int]) -> str:
    if len(chunk) == 1:
        return str(chunk[0])
    expected = list(range(chunk[0], chunk[-1] + 1))
    if chunk == expected:
        return f"{chunk[0]}-{chunk[-1]}"
    return ",".join(str(page) for page in chunk)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def chunk_already_complete(report_json: Path, chunk: list[int]) -> bool:
    if not report_json.exists():
        return False
    report = read_json(report_json)
    pages = {int(page["page"]): page for page in report.get("pages", []) if page.get("page") is not None}
    for page_num in chunk:
        page = pages.get(page_num)
        if not page:
            return False
        if page.get("status") != "PASS":
            return False
        for key in ("primary_review_svg", "primary_review_render", "primary_review_diff"):
            value = page.get(key)
            if not value or not Path(value).exists():
                return False
    return True


def compact_chunk_record(label: str, proc: subprocess.CompletedProcess[str], log_path: Path) -> dict[str, Any]:
    stdout_tail = "\n".join(proc.stdout.splitlines()[-20:])
    stderr_tail = "\n".join(proc.stderr.splitlines()[-20:])
    return {
        "chunk": label,
        "returncode": proc.returncode,
        "log": str(log_path),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def chunk_report_stem(report_stem: str, label: str, run_stamp: str) -> str:
    safe_label = label.replace("-", "_")
    return f"{report_stem}_chunk_{safe_label}_{run_stamp}"


def run_chunk(args: argparse.Namespace, chunk: list[int], run_stamp: str) -> dict[str, Any]:
    label = chunk_label(chunk)
    stem = chunk_report_stem(args.report_stem, label, run_stamp)
    log_path = args.log_root / f"rollout_chunk_{label}_{run_stamp}.log"
    cmd = [
        sys.executable,
        str(ROLLOUT_SCRIPT),
        "--output-root",
        str(args.output_root),
        "--package-root",
        str(args.package_root),
        "--report-stem",
        stem,
        "--report-title",
        f"{args.report_title} Chunk {label}",
        "--pages",
        page_filter_for_chunk(chunk),
        "--resume",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            "\n".join(
                [
                    "TIMEOUT",
                    f"chunk={label}",
                    f"timeout_seconds={args.timeout_seconds}",
                    "stdout_tail:",
                    "\n".join((exc.stdout or "").splitlines()[-40:]),
                    "stderr_tail:",
                    "\n".join((exc.stderr or "").splitlines()[-40:]),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "chunk": label,
            "status": "TIMEOUT",
            "log": str(log_path),
            "report_json": str(args.package_root / f"{stem}_report.json"),
        }

    log_path.write_text(
        "\n".join(
            [
                "command:",
                " ".join(cmd),
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
    record = compact_chunk_record(label, proc, log_path)
    record["status"] = "PASS" if proc.returncode == 0 else "FAIL"
    record["report_json"] = str(args.package_root / f"{stem}_report.json")
    return record


def merge_reports(args: argparse.Namespace, report_json: Path, chunk_records: list[dict[str, Any]]) -> dict[str, Any]:
    page_records: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    visual_blockers: list[dict[str, Any]] = []
    template: dict[str, Any] | None = None

    if report_json.exists():
        existing = read_json(report_json)
        template = existing
        for page in existing.get("pages", []):
            if page.get("page") is not None:
                page_records[int(page["page"])] = page

    for record in chunk_records:
        chunk_report = Path(record.get("report_json", ""))
        if not chunk_report.exists():
            continue
        report = read_json(chunk_report)
        template = report
        for page in report.get("pages", []):
            if page.get("page") is not None:
                page_records[int(page["page"])] = page
        failures.extend(report.get("failures", []))
        visual_blockers.extend(report.get("visual_blockers", []))

    pages = [page_records[page_num] for page_num in sorted(page_records)]
    status = "PASS_WITH_VISUAL_BLOCKERS" if visual_blockers and not failures else ("PASS" if not failures else "FAIL")
    report = {
        "status": status,
        "package_root": str(args.package_root),
        "inkscape": (template or {}).get("inkscape", ""),
        "pages_requested": sum(
            len(parse_pages(page_filter_for_chunk(record["pages"])))
            for record in chunk_records
            if record.get("pages")
        ),
        "pages_with_tables": sum(1 for page in pages if page.get("tables")),
        "pages_processed": len(pages),
        "failures": failures,
        "visual_blockers": visual_blockers,
        "pages": pages,
        "notes": (template or {}).get(
            "notes",
            [
                "This is a merged full-book rollout report assembled from parallel chunk reports.",
            ],
        ),
    }
    write_path = args.package_root / f"{args.report_stem}_report.json"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    report_md = args.package_root / f"{args.report_stem}_report.md"
    lines = [
        f"# {args.report_title}",
        "",
        f"Status: `{status}`",
        f"Package root: `{args.package_root}`",
        f"Pages processed: `{len(pages)}`",
        f"Failures: `{len(failures)}`",
        f"Visual blockers: `{len(visual_blockers)}`",
        "",
        "This report was merged from per-chunk rollout reports.",
        "",
    ]
    report_md.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDFRejuvenator editable SVG rollout in resumable chunks.")
    parser.add_argument("--pages", required=True, help="Comma-separated exact pages/ranges to process.")
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument("--log-root", type=Path, default=DEFAULT_LOG_ROOT)
    parser.add_argument("--report-stem", default="full_full_book_promotion_rollout")
    parser.add_argument("--report-title", default="Full Book Promotion Editable SVG Rollout")
    parser.add_argument("--workers", type=int, default=1, help="Number of rollout chunks to run concurrently.")
    parser.add_argument("--force", action="store_true", help="Re-run chunks even if their page records look complete.")
    args = parser.parse_args()

    if args.chunk_size < 1:
        raise SystemExit("--chunk-size must be >= 1")
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    args.log_root.mkdir(parents=True, exist_ok=True)
    report_json = args.package_root / f"{args.report_stem}_report.json"
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chunks = make_chunks(parse_pages(args.pages), args.chunk_size)
    results: list[dict[str, Any]] = []

    pending_chunks: list[list[int]] = []
    for chunk in chunks:
        label = chunk_label(chunk)
        if not args.force and chunk_already_complete(report_json, chunk):
            record = {"chunk": label, "status": "SKIPPED_COMPLETE"}
            print(json.dumps(record, sort_keys=True))
            results.append(record)
            continue
        pending_chunks.append(chunk)

    if pending_chunks:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_chunk = {executor.submit(run_chunk, args, chunk, run_stamp): chunk for chunk in pending_chunks}
            for future in as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                record = future.result()
                record["pages"] = chunk
                printable = {key: record[key] for key in ("chunk", "status", "log") if key in record}
                if "returncode" in record:
                    printable["returncode"] = record["returncode"]
                print(json.dumps(printable, sort_keys=True))
                results.append(record)
                if record["status"] != "PASS":
                    for other in future_to_chunk:
                        other.cancel()
                    summary_path = args.log_root / f"rollout_chunk_summary_{run_stamp}.json"
                    summary_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
                    return 124 if record["status"] == "TIMEOUT" else int(record.get("returncode") or 1)

    merge_reports(args, report_json, [record for record in results if record.get("status") == "PASS"])

    failed = [record for record in results if record.get("status") not in {"PASS", "SKIPPED_COMPLETE"}]
    if failed:
            summary_path = args.log_root / f"rollout_chunk_summary_{run_stamp}.json"
            summary_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
            return 1

    summary_path = args.log_root / f"rollout_chunk_summary_{run_stamp}.json"
    summary_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", "chunks": len(chunks), "summary": str(summary_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
