from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


HREF_OR_SRC_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""", re.IGNORECASE)
VALIDATION_SUMMARY_RE = re.compile(r"""<div class="validation-summary">.*?</div>""", re.DOTALL)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_svg(path: Path, errors: list[str]) -> None:
    if not path.exists():
        fail(errors, f"missing SVG: {path}")
        return
    if path.stat().st_size <= 0:
        fail(errors, f"empty SVG: {path}")
        return
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        fail(errors, f"invalid SVG XML: {path}: {exc}")
        return
    text_nodes = [
        element
        for element in root.iter()
        if element.tag.endswith("text") or element.tag.endswith("tspan")
    ]
    if not text_nodes:
        fail(errors, f"SVG has no editable text/tspan nodes: {path}")


def validate_png(path: Path, errors: list[str]) -> None:
    if not path.exists():
        fail(errors, f"missing preview PNG: {path}")
        return
    if path.stat().st_size <= 0:
        fail(errors, f"empty preview PNG: {path}")
        return
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001 - report image validation failures.
        fail(errors, f"invalid preview PNG: {path}: {type(exc).__name__}: {exc}")


def validate_dashboard_links(output_dir: Path, errors: list[str]) -> None:
    dashboard = output_dir / "dashboard.html"
    if not dashboard.exists():
        fail(errors, f"missing dashboard: {dashboard}")
        return
    text = dashboard.read_text(encoding="utf-8")
    links = sorted(set(HREF_OR_SRC_RE.findall(text)))
    if not links:
        fail(errors, f"dashboard has no href/src links: {dashboard}")
        return
    for link in links:
        if "://" in link or link.startswith("#"):
            continue
        target = (output_dir / link.replace("/", "\\")).resolve()
        try:
            target.relative_to(output_dir.resolve())
        except ValueError:
            fail(errors, f"dashboard link escapes output folder: {link}")
            continue
        if not target.exists():
            fail(errors, f"dashboard link target missing: {link}")


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def annotate_dashboard(output_dir: Path, page_errors: dict[str, list[str]], global_errors: list[str]) -> None:
    dashboard = output_dir / "dashboard.html"
    if not dashboard.exists():
        return
    text = dashboard.read_text(encoding="utf-8")
    failed_pages = sorted(page for page, errors in page_errors.items() if errors)
    status = "PASS" if not failed_pages and not global_errors else "VALIDATION ISSUES"
    summary = (
        f'<div class="validation-summary"><strong>Validation:</strong> {status}. '
        f'Failed/uncertain pages: {", ".join(failed_pages) if failed_pages else "none"}. '
        f'Global issues: {len(global_errors)}.</div>'
    )
    if "validation-summary" in text:
        text = VALIDATION_SUMMARY_RE.sub(summary, text, count=1)
    else:
        text = text.replace("<section class=\"grid\">", summary + "\n<section class=\"grid\">", 1)
    for page in failed_pages:
        text = text.replace(
            f"<strong>Page {page}</strong><span>PASS</span>",
            f"<strong>Page {page}</strong><span>VALIDATION_FAILED</span>",
        )
    dashboard.write_text(text, encoding="utf-8")


def write_validation_reports(
    output_dir: Path,
    rows: list[dict[str, str]],
    page_errors: dict[str, list[str]],
    global_errors: list[str],
) -> None:
    report = {
        "status": "PASS" if not global_errors and not any(page_errors.values()) else "FAIL",
        "global_errors": global_errors,
        "pages": [
            {
                "page": row.get("page", ""),
                "validation_status": "PASS" if not page_errors.get(row.get("page", ""), []) else "FAIL",
                "errors": page_errors.get(row.get("page", ""), []),
            }
            for row in rows
        ],
    }
    (output_dir / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_csv(
        output_dir / "validation_report.csv",
        [
            {
                "page": page["page"],
                "validation_status": page["validation_status"],
                "validation_errors": " | ".join(page["errors"]),
            }
            for page in report["pages"]
        ],
        ["page", "validation_status", "validation_errors"],
    )

    if rows:
        augmented = []
        for row in rows:
            page = row.get("page", "")
            errors = page_errors.get(page, [])
            copy = dict(row)
            copy["validation_status"] = "PASS" if not errors else "FAIL"
            copy["validation_errors"] = " | ".join(errors)
            augmented.append(copy)
        fieldnames = list(rows[0].keys())
        for extra in ["validation_status", "validation_errors"]:
            if extra not in fieldnames:
                fieldnames.append(extra)
        write_csv(output_dir / "manifest.csv", augmented, fieldnames)

    annotate_dashboard(output_dir, page_errors, global_errors)


def validate_output(output_dir: Path) -> tuple[list[str], list[dict[str, str]], dict[str, list[str]]]:
    global_errors: list[str] = []
    page_errors: dict[str, list[str]] = {}
    manifest = output_dir / "manifest.csv"
    readme = output_dir / "README.md"
    debug_root = output_dir / "_debug"

    if not readme.exists():
        fail(global_errors, f"missing README: {readme}")
    if not debug_root.exists():
        fail(global_errors, f"missing _debug folder: {debug_root}")
    if not manifest.exists():
        fail(global_errors, f"missing manifest: {manifest}")
        return global_errors, [], page_errors

    rows = read_manifest(manifest)
    if not rows:
        fail(global_errors, f"manifest has no rows: {manifest}")
        return global_errors, rows, page_errors

    required_columns = {"page", "status", "editable_svg", "preview_png"}
    missing_columns = required_columns - set(rows[0])
    if missing_columns:
        fail(global_errors, f"manifest missing columns: {', '.join(sorted(missing_columns))}")
        return global_errors, rows, page_errors

    for row in rows:
        page = row.get("page", "")
        errors: list[str] = []
        svg = output_dir / row.get("editable_svg", "")
        png = output_dir / row.get("preview_png", "")
        if not page:
            fail(errors, "manifest row missing page")
        if row.get("status") != "PASS":
            fail(errors, f"page {page} status is not PASS: {row.get('status')}")
        validate_svg(svg, errors)
        validate_png(png, errors)
        page_errors[page or "unknown"] = errors

    validate_dashboard_links(output_dir, global_errors)
    return global_errors, rows, page_errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate consolidated PDFRejuvenator review output.")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--mode", choices=["internal", "external"], default="internal")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    global_errors, rows, page_errors = validate_output(output_dir)
    write_validation_reports(output_dir, rows, page_errors, global_errors)
    errors = [*global_errors]
    for page, page_error_list in page_errors.items():
        errors.extend([f"page {page}: {message}" for message in page_error_list])
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"SUMMARY: status=FAIL mode={args.mode} errors={len(errors)}")
        return 1 if args.mode == "internal" else 0
    print("SUMMARY: status=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
