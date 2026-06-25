from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doc_pipeline import read_json, write_json, write_text  # noqa: E402


DEFAULT_INKSCAPE = Path(r"C:\Program Files\Inkscape\bin\inkscape.exe")


def find_inkscape(explicit: str | None = None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    found = shutil.which("inkscape") or shutil.which("inkscape.exe")
    if found:
        candidates.append(Path(found))
    candidates.extend([
        DEFAULT_INKSCAPE,
        Path(r"C:\Program Files\Inkscape\inkscape.exe"),
        Path(r"C:\Program Files\Inkscape\bin\inkscape.exe"),
        Path(r"C:\Program Files (x86)\Inkscape\inkscape.exe"),
        Path(r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe"),
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Inkscape executable was not found")


def load_pages(output_root: Path) -> list[dict[str, Any]]:
    selected_path = output_root / "selected_pages_manifest.json"
    book_path = output_root / "book_manifest.json"
    if selected_path.exists():
        return read_json(selected_path)["pages"]
    if book_path.exists():
        return read_json(book_path)["pages"]
    raise FileNotFoundError(f"missing selected_pages_manifest.json or book_manifest.json under {output_root}")


def render_svg(inkscape: Path, svg_path: Path, png_path: Path, width: int, height: int) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.unlink(missing_ok=True)
    proc = subprocess.run(
        [
            str(inkscape),
            str(svg_path),
            "--export-type=png",
            f"--export-filename={png_path}",
            f"--export-width={width}",
            f"--export-height={height}",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0 or not png_path.exists():
        raise RuntimeError(
            f"Inkscape failed to render SVG: {svg_path}\nstdout={proc.stdout.strip()}\nstderr={proc.stderr.strip()}"
        )


def compare_images(source_path: Path, rendered_path: Path, side_by_side_path: Path, diff_path: Path) -> float:
    source = Image.open(source_path).convert("RGB")
    rendered = Image.open(rendered_path).convert("RGB")
    if rendered.size != source.size:
        rendered = rendered.resize(source.size, Image.Resampling.LANCZOS)
        rendered.save(rendered_path)
    diff = ImageChops.difference(source, rendered)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff.save(diff_path)
    side = Image.new("RGB", (source.width * 2 + 24, source.height), "white")
    side.paste(source, (0, 0))
    side.paste(rendered, (source.width + 24, 0))
    side.save(side_by_side_path)
    nonzero = sum(1 for pixel in diff.convert("L").getdata() if pixel > 24)
    total = source.width * source.height
    return round(nonzero / total if total else 1.0, 4)


def compare_page(page: dict[str, Any], render_root: Path, inkscape: Path) -> dict[str, Any]:
    page_root = Path(page["output_root"])
    manifest = read_json(page_root / "manifest.json")
    source_path = page_root / manifest["render"]["page_png"]
    source = Image.open(source_path).convert("RGB")
    svg_rel = manifest["inkscape"].get("inkscape_fidelity_svg") or manifest["inkscape"]["inkscape_layered_svg"]
    svg_path = page_root / svg_rel
    page_dir = render_root / f"page_{int(page['page']):03d}"
    rendered_png = page_dir / "inkscape_layered_render.png"
    side_by_side = page_dir / "inkscape_vs_pdf_source_side_by_side.png"
    diff_png = page_dir / "inkscape_vs_pdf_source_pixel_difference.png"
    try:
        render_svg(inkscape, svg_path, rendered_png, source.width, source.height)
        difference_ratio = compare_images(source_path, rendered_png, side_by_side, diff_png)
        status = "VISUAL_REVIEW_REQUIRED"
        error = None
    except Exception as exc:
        difference_ratio = 1.0
        status = "RENDER_FAILED"
        error = str(exc)
    result = {
        "page": page["page"],
        "page_id": manifest["page_id"],
        "status": status,
        "renderer": "inkscape",
        "inkscape": str(inkscape),
        "source_render": str(source_path),
        "inkscape_svg": str(svg_path),
        "rendered_png": str(rendered_png) if rendered_png.exists() else None,
        "side_by_side": str(side_by_side) if side_by_side.exists() else None,
        "pixel_difference": str(diff_png) if diff_png.exists() else None,
        "difference_ratio": difference_ratio,
        "editable_text_count": manifest["inkscape"].get("editable_text_count", 0),
        "error": error,
    }
    write_json(page_dir / "inkscape_visual_result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Render generated Inkscape SVG files and compare them to source PDF renders.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--inkscape")
    parser.add_argument("--pages", nargs="*", type=int, help="1-based source PDF page numbers to render; defaults to all pages in manifest")
    args = parser.parse_args()

    config = read_json(Path(args.config).resolve())
    output_root = Path(config["output_root"])
    pages = load_pages(output_root)
    if args.pages:
        requested = set(args.pages)
        pages = [page for page in pages if int(page["page"]) in requested]
    inkscape = find_inkscape(args.inkscape)
    render_root = output_root / "inkscape_rendered_visual_comparisons"
    render_root.mkdir(parents=True, exist_ok=True)
    results = [compare_page(page, render_root, inkscape) for page in pages]
    report = {
        "status": "VISUAL_REVIEW_REQUIRED" if all(item["status"] != "RENDER_FAILED" for item in results) else "RENDER_FAILED",
        "renderer": "inkscape",
        "inkscape": str(inkscape),
        "output_root": str(output_root),
        "visual_root": str(render_root),
        "pages": results,
    }
    write_json(render_root / "inkscape_visual_comparisons_report.json", report)
    lines = [
        "# Inkscape Rendered Visual Comparisons",
        "",
        f"Status: {report['status']}",
        "",
        f"Renderer: `{inkscape}`",
        "",
        "These comparisons render the generated layered Inkscape SVG and compare it to the original PDF page render.",
        "",
    ]
    for result in results:
        lines.extend([
            f"## Page {result['page']}",
            "",
            f"- Inkscape SVG: `{result['inkscape_svg']}`",
            f"- Side by side: `{result['side_by_side']}`",
            f"- Pixel difference: `{result['pixel_difference']}`",
            f"- Difference ratio: `{result['difference_ratio']}`",
            f"- Editable SVG text elements: `{result['editable_text_count']}`",
            f"- Status: `{result['status']}`",
            "",
        ])
        if result["error"]:
            lines.extend([f"- Error: `{result['error']}`", ""])
    write_text(render_root / "inkscape_visual_comparisons_report.md", "\n".join(lines))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["status"] == "RENDER_FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
