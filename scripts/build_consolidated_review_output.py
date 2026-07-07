from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def default_output_dir(source_pdf: Path) -> Path:
    return source_pdf.with_name(f"{source_pdf.stem}_pdfrejuvenator_output")


def copy_file(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"missing artifact: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def relative_link(from_dir: Path, target: Path) -> str:
    return target.relative_to(from_dir).as_posix()


def build_dashboard(output_dir: Path, rows: list[dict[str, str]]) -> str:
    cards = []
    for row in rows:
        page = row["page"]
        svg = html.escape(relative_link(output_dir, output_dir / row["editable_svg"]), quote=True)
        preview = html.escape(relative_link(output_dir, output_dir / row["preview_png"]), quote=True)
        status = html.escape(row["status"])
        cards.append(
            f"""
      <article class="card" data-status="{status}">
        <header><strong>Page {page}</strong><span>{status}</span></header>
        <a href="{preview}"><img src="{preview}" alt="Page {page} preview"></a>
        <nav><a class="primary" href="{svg}">Open editable SVG</a><a href="{preview}">Preview PNG</a></nav>
      </article>"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PDFRejuvenator Review Output</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f7f5; color: #151515; }}
h1 {{ margin: 0 0 8px; font-size: 24px; }}
.meta {{ color: #444; margin-bottom: 18px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }}
.card {{ background: white; border: 1px solid #ccc; padding: 10px; }}
.card header {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
.card img {{ display: block; width: 100%; border: 1px solid #ddd; background: #eee; }}
.card nav {{ display: flex; gap: 10px; margin-top: 8px; font-size: 13px; }}
.card nav .primary {{ font-weight: 700; }}
a {{ color: #064f8a; }}
</style>
</head>
<body>
<h1>PDFRejuvenator Review Output</h1>
<div class="meta">{len(rows)} pages. The file named <code>page_###_edit_this_page.svg</code> is the one to edit. Preview PNG files are only for checking the page visually.</div>
<section class="grid">
{''.join(cards)}
</section>
</body>
</html>
"""


def write_manifest(output_dir: Path, rows: list[dict[str, str]]) -> None:
    path = output_dir / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "page",
                "status",
                "editable_svg",
                "preview_png",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "page": row["page"],
                    "status": row["status"],
                    "editable_svg": row["editable_svg"],
                    "preview_png": row["preview_png"],
                }
            )


def write_debug_manifest(debug_dir: Path, rows: list[dict[str, str]]) -> None:
    path = debug_dir / "debug_manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "page",
                "status",
                "editable_svg",
                "preview_png",
                "source_primary_review_svg",
                "source_primary_review_render",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_readme(output_dir: Path, source_pdf: Path, rows: list[dict[str, str]], run_root: Path) -> None:
    lines = [
        "# PDFRejuvenator Review Output",
        "",
        f"Source PDF: `{source_pdf.name}`",
        f"Pages: `{len(rows)}`",
        "",
        "Open first:",
        "",
        "```text",
        "dashboard.html",
        "```",
        "",
        "Editable page files are in:",
        "",
        "```text",
        "pages\\page_###_edit_this_page.svg",
        "```",
        "",
        "Preview PNG files are in:",
        "",
        "```text",
        "pages\\page_###_preview.png",
        "```",
        "",
        "The SVG file is the one to edit. The PNG file is only a preview/check image.",
        "",
        "Internal/debug artifacts are not part of the normal review flow. The internal run root is recorded in:",
        "",
        "```text",
        "_debug\\INTERNAL_RUN_ROOT.txt",
        "```",
        "",
        "Detailed internal source artifact paths are recorded in:",
        "",
        "```text",
        "_debug\\debug_manifest.csv",
        "```",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build consolidated PDFRejuvenator review output.")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-pdf", type=Path, required=True)
    parser.add_argument("--report-stem", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    source_pdf = args.source_pdf.resolve()
    output_dir = (args.output_dir or default_output_dir(source_pdf)).resolve()
    rollout_report_path = run_root / "editable_svg_rollout" / f"{args.report_stem}_report.json"
    rollout = read_json(rollout_report_path)

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for page in sorted(rollout.get("pages", []), key=lambda item: int(item["page"])):
        page_number = int(page["page"])
        page_label = f"{page_number:03d}"
        source_svg = Path(page.get("primary_review_svg") or "")
        source_preview = Path(page.get("primary_review_render") or "")
        target_svg = pages_dir / f"page_{page_label}_edit_this_page.svg"
        target_preview = pages_dir / f"page_{page_label}_preview.png"
        copy_file(source_svg, target_svg)
        copy_file(source_preview, target_preview)
        rows.append(
            {
                "page": page_label,
                "status": page.get("status", "UNKNOWN"),
                "editable_svg": str(target_svg.relative_to(output_dir)),
                "preview_png": str(target_preview.relative_to(output_dir)),
                "source_primary_review_svg": str(source_svg),
                "source_primary_review_render": str(source_preview),
            }
        )

    (output_dir / "dashboard.html").write_text(build_dashboard(output_dir, rows), encoding="utf-8")
    write_manifest(output_dir, rows)
    write_debug_manifest(debug_dir, rows)
    write_readme(output_dir, source_pdf, rows, run_root)
    (debug_dir / "INTERNAL_RUN_ROOT.txt").write_text(str(run_root) + "\n", encoding="utf-8")
    (debug_dir / "SOURCE_PDF.txt").write_text(str(source_pdf) + "\n", encoding="utf-8")
    (debug_dir / "ROLLOUT_REPORT.txt").write_text(str(rollout_report_path) + "\n", encoding="utf-8")

    print(f"CONSOLIDATED_OUTPUT={output_dir}")
    print(f"DASHBOARD={output_dir / 'dashboard.html'}")
    print(f"MANIFEST={output_dir / 'manifest.csv'}")
    print(f"PAGES={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
