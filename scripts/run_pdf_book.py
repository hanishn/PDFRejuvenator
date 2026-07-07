from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doc_pipeline import read_json, run_pipeline, sha256_file, write_json  # noqa: E402


def parse_pages(value: str) -> list[int]:
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def default_book_config(source_pdf: Path, output_root: Path, book_id: str) -> dict[str, Any]:
    return {
        "book_id": book_id,
        "source_pdf": str(source_pdf.resolve()),
        "output_root": str(output_root.resolve()),
        "render": {
            "dpi": 150,
            "tiff_compression": "tiff_lzw",
            "transparent_threshold": 248,
        },
        "regions": {
            "layout_strategy": "line",
            "max_text_regions": 300,
            "merge_vertical_gap_points": 0,
            "min_text_chars": 2,
        },
        "tables": {
            "enabled": True,
            "row_tolerance_points": 4.0,
        },
        "ocr": {
            "allow_fallback": True,
            "fallback_engine": "pymupdf_text_blocks",
            "preferred_engine": "pymupdf_text_blocks",
        },
        "rebuild": {
            "hidden_editable_overlay": True,
            "include_page_render_as_docx_background": True,
            "include_page_render_in_outputs": False,
            "include_region_images_in_docx": False,
        },
    }


def clean(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def page_config(book_config: dict[str, Any], page_number: int, config_dir: Path, pages_root: Path) -> Path:
    page_id = f"{book_config['book_id']}_page_{page_number:03d}"
    config = {
        "job_id": page_id,
        "source_pdf": book_config["source_pdf"],
        "source_pdf_expected_sha256": book_config.get("source_pdf_expected_sha256"),
        "selected_page_1based": page_number,
        "page_selection_rule": "book batch explicit page order",
        "output_root": str(pages_root / f"page_{page_number:03d}"),
        "render": book_config["render"],
        "regions": book_config["regions"],
        "tables": book_config.get("tables", {"enabled": True}),
        "ocr": book_config["ocr"],
        "rebuild": book_config["rebuild"],
    }
    config_path = config_dir / f"page_{page_number:03d}.json"
    write_json(config_path, config)
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic PDF remastering process for a page range or whole PDF.")
    parser.add_argument("--config", help="Book JSON config.")
    parser.add_argument("--source-pdf", help="Source PDF path. Used when --config is omitted or to override config.")
    parser.add_argument("--output-root", help="Output root. Used when --config is omitted or to override config.")
    parser.add_argument("--book-id", default="pdfrejuvenator_book", help="Stable book id for generated page ids.")
    parser.add_argument("--page-start", type=int, default=None)
    parser.add_argument("--page-end", type=int, default=None)
    parser.add_argument("--pages", default=None, help="Comma-separated exact pages/ranges to process.")
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--ocr-engine", choices=["pymupdf_text_blocks", "rapidocr"], default=None)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if args.config:
        config_path = Path(args.config).resolve()
        config = read_json(config_path)
    else:
        if not args.source_pdf:
            raise SystemExit("--source-pdf is required when --config is omitted")
        source_pdf = Path(args.source_pdf).resolve()
        output_root = Path(args.output_root).resolve() if args.output_root else ROOT / "outputs" / args.book_id
        config = default_book_config(source_pdf, output_root, args.book_id)

    if args.source_pdf:
        config["source_pdf"] = str(Path(args.source_pdf).resolve())
    if args.output_root:
        config["output_root"] = str(Path(args.output_root).resolve())
    if args.dpi is not None:
        config["render"]["dpi"] = args.dpi
    if args.ocr_engine is not None:
        config["ocr"]["preferred_engine"] = args.ocr_engine

    source_pdf = Path(config["source_pdf"])
    doc = fitz.open(source_pdf)
    if args.pages:
        page_numbers = parse_pages(args.pages)
    else:
        page_start = int(args.page_start or config.get("page_start_1based") or 1)
        page_end = args.page_end if args.page_end is not None else config.get("page_end_1based")
        if page_end is None:
            page_end = len(doc)
        page_end = int(page_end)
        page_numbers = list(range(page_start, page_end + 1))
    if not page_numbers or min(page_numbers) < 1 or max(page_numbers) > len(doc):
        requested = args.pages or f"{page_numbers[0] if page_numbers else '?'}..{page_numbers[-1] if page_numbers else '?'}"
        raise SystemExit(f"invalid page selection {requested} for {len(doc)} pages")
    doc.close()

    output_root = Path(config["output_root"])
    if args.clean:
        clean(output_root)
    else:
        output_root.mkdir(parents=True, exist_ok=True)
    config_dir = output_root / "_page_configs"
    pages_root = output_root / "pages"
    config_dir.mkdir(parents=True, exist_ok=True)
    pages_root.mkdir(parents=True, exist_ok=True)

    page_manifests = []
    for page_number in page_numbers:
        cfg = page_config(config, page_number, config_dir, pages_root)
        manifest = run_pipeline(cfg, clean=True)
        page_manifests.append({
            "page_number_1based": page_number,
            "page": page_number,
            "page_id": manifest["page_id"],
            "output_root": str(Path(read_json(cfg)["output_root"])),
            "manifest": str(Path(read_json(cfg)["output_root"]) / "manifest.json"),
            "textboxes": len(manifest["textbox_regions"]),
            "normal_editable_text_regions": len([
                item for item in manifest["textbox_regions"]
                if item.get("classification") == "normal_editable_text"
            ]),
            "table_csv_files": len(manifest.get("tables", [])),
            "embedded_images": len(manifest["embedded_images"]),
            "ocr_engine": manifest["ocr"]["engine"],
            "ocr_fallback": manifest["ocr"]["fallback"],
        })
        print(f"page {page_number}/{page_numbers[-1]}: {manifest['page_id']} textboxes={len(manifest['textbox_regions'])} images={len(manifest['embedded_images'])}")

    book_manifest = {
        "book_id": config["book_id"],
        "source_pdf": str(source_pdf),
        "source_pdf_sha256": sha256_file(source_pdf),
        "page_start_1based": page_numbers[0],
        "page_end_1based": page_numbers[-1],
        "pages_requested": page_numbers,
        "page_count_processed": len(page_manifests),
        "output_root": str(output_root),
        "render": config["render"],
        "regions": config["regions"],
        "tables": config.get("tables", {"enabled": True}),
        "ocr": config["ocr"],
        "rebuild": config["rebuild"],
        "pages": page_manifests,
    }
    write_json(output_root / "book_manifest.json", book_manifest)
    print(f"book manifest: {output_root / 'book_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
