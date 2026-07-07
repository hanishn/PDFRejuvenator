from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return re.sub(r"\s+", " ", text).strip()


def normalize_search_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = text.replace("●", " bullet ")
    text = re.sub(r"(?<=[A-Za-z])(?=\()", " ", text)
    text = re.sub(r"(?<=\))(?=[A-Za-z0-9])", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[0-9%])(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", text)
    text = re.sub(r"(?<=[.,:;!?])(?=[A-Za-z0-9])", " ", text)
    return clean_text(text)


def rel_artifact(path: str | None, page_root: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = page_root / candidate
    return str(candidate)


def make_record(
    *,
    book_manifest: dict[str, Any],
    page_manifest: dict[str, Any],
    record_type: str,
    text: str,
    artifact_path: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page_number = int(page_manifest.get("selected_page_1based") or page_manifest.get("page_number_1based") or 0)
    record_id_bits = [
        book_manifest.get("book_id", "book"),
        f"p{page_number:03d}",
        record_type,
        str((metadata or {}).get("record_id") or (metadata or {}).get("region_id") or (metadata or {}).get("image_id") or ""),
    ]
    return {
        "schema_version": "pdfrejuvenator.search.v0.3",
        "record_id": "::".join(bit for bit in record_id_bits if bit),
        "book_id": book_manifest.get("book_id", ""),
        "source_pdf": book_manifest.get("source_pdf", ""),
        "source_pdf_sha256": book_manifest.get("source_pdf_sha256", ""),
        "page": page_number,
        "page_id": page_manifest.get("page_id", ""),
        "record_type": record_type,
        "text": normalize_search_text(text),
        "artifact_path": artifact_path,
        "metadata": metadata or {},
    }


def text_from_table(table: Any) -> str:
    if isinstance(table, dict):
        parts: list[str] = []
        for key in ("caption", "title", "text", "csv", "file"):
            if table.get(key):
                parts.append(str(table[key]))
        rows = table.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list):
                    parts.append(" ".join(clean_text(cell) for cell in row))
                elif isinstance(row, dict):
                    parts.append(" ".join(clean_text(value) for value in row.values()))
        return clean_text(" ".join(parts))
    return clean_text(table)


def build_records(run_root: Path) -> list[dict[str, Any]]:
    pipeline_root = run_root / "pipeline"
    book_manifest_path = pipeline_root / "book_manifest.json"
    if not book_manifest_path.exists():
        raise SystemExit(f"missing book manifest: {book_manifest_path}")
    book_manifest = read_json(book_manifest_path)

    records: list[dict[str, Any]] = []
    for page_entry in sorted(book_manifest.get("pages", []), key=lambda item: int(item.get("page", 0))):
        page_manifest_path = Path(page_entry["manifest"])
        page_manifest = read_json(page_manifest_path)
        page_root = page_manifest_path.parent

        page_metadata = {
            "record_id": "page",
            "page_rect_points": page_manifest.get("page_rect_points", []),
            "ocr": page_manifest.get("ocr", {}),
            "render": page_manifest.get("render", {}),
            "textboxes": len(page_manifest.get("textbox_regions", [])),
            "tables": len(page_manifest.get("tables", [])),
            "embedded_images": len(page_manifest.get("embedded_images", [])),
        }
        ocr_records = load_ocr_records(page_manifest, page_root)
        page_text_parts = [clean_text(region.get("text")) for region in page_manifest.get("textbox_regions", [])]
        page_text_parts.extend(clean_text(record.get("text")) for record in ocr_records)
        page_text = " ".join(part for part in page_text_parts if part)
        records.append(
            make_record(
                book_manifest=book_manifest,
                page_manifest=page_manifest,
                record_type="page",
                text=page_text,
                metadata=page_metadata,
            )
        )

        for region in page_manifest.get("textbox_regions", []):
            text = clean_text(region.get("text"))
            if not text:
                continue
            metadata = {
                "record_id": region.get("region_id", ""),
                "region_id": region.get("region_id", ""),
                "bbox_points": region.get("bbox_points", []),
                "layout_class": region.get("layout_class", ""),
                "classification": region.get("classification", ""),
                "font_summary": [
                    {
                        "font": span.get("font", ""),
                        "size_pt": span.get("size_pt", ""),
                        "bold": span.get("bold", False),
                        "italic": span.get("italic", False),
                    }
                    for line in region.get("lines", [])
                    for span_group in line
                    for span in (span_group if isinstance(span_group, list) else [span_group])
                    if isinstance(span, dict)
                ],
            }
            records.append(
                make_record(
                    book_manifest=book_manifest,
                    page_manifest=page_manifest,
                    record_type="text_region",
                    text=text,
                    artifact_path=rel_artifact(region.get("file"), page_root),
                    metadata=metadata,
                )
            )

        for ocr_index, ocr_record in enumerate(ocr_records, start=1):
            text = clean_text(ocr_record.get("text"))
            if not text:
                continue
            metadata = {
                "record_id": ocr_record.get("region_id", f"ocr_{ocr_index:04d}"),
                "region_id": ocr_record.get("region_id", ""),
                "bbox_points": ocr_record.get("bbox_points", []),
                "engine": ocr_record.get("engine", ""),
                "confidence": ocr_record.get("confidence"),
                "fallback": ocr_record.get("fallback", False),
                "original_text": text,
            }
            records.append(
                make_record(
                    book_manifest=book_manifest,
                    page_manifest=page_manifest,
                    record_type="ocr_text",
                    text=text,
                    metadata=metadata,
                )
            )

        for table_index, table in enumerate(page_manifest.get("tables", []), start=1):
            table_text = text_from_table(table)
            metadata = table if isinstance(table, dict) else {"value": table}
            metadata = dict(metadata)
            metadata.setdefault("record_id", f"table_{table_index:03d}")
            records.append(
                make_record(
                    book_manifest=book_manifest,
                    page_manifest=page_manifest,
                    record_type="table",
                    text=table_text,
                    artifact_path=rel_artifact(metadata.get("file") or metadata.get("csv"), page_root),
                    metadata=metadata,
                )
            )

        for image in page_manifest.get("embedded_images", []):
            text = clean_text(
                " ".join(
                    [
                        image.get("classification", ""),
                        image.get("review_role", ""),
                        f"{image.get('width_px', '')}x{image.get('height_px', '')}",
                    ]
                )
            )
            metadata = {
                "record_id": image.get("image_id", ""),
                "image_id": image.get("image_id", ""),
                "classification": image.get("classification", ""),
                "review_role": image.get("review_role", ""),
                "bbox_points": image.get("bbox_points", []),
                "width_px": image.get("width_px", ""),
                "height_px": image.get("height_px", ""),
                "sha256": image.get("sha256", ""),
                "xref": image.get("xref", ""),
            }
            records.append(
                make_record(
                    book_manifest=book_manifest,
                    page_manifest=page_manifest,
                    record_type="image",
                    text=text,
                    artifact_path=rel_artifact(image.get("file"), page_root),
                    metadata=metadata,
                )
            )

    return records


def load_ocr_records(page_manifest: dict[str, Any], page_root: Path) -> list[dict[str, Any]]:
    ocr = page_manifest.get("ocr", {})
    if not isinstance(ocr, dict):
        return []
    ocr_json = ocr.get("ocr_json")
    if not ocr_json:
        return []
    path = Path(ocr_json)
    if not path.is_absolute():
        path = page_root / path
    if not path.exists():
        return []
    payload = read_json(path)
    records = payload.get("records", []) if isinstance(payload, dict) else []
    return [record for record in records if isinstance(record, dict)]


def write_index(output_dir: Path, records: list[dict[str, Any]], run_root: Path) -> None:
    search_dir = output_dir / "_search"
    search_dir.mkdir(parents=True, exist_ok=True)
    index_path = search_dir / "search_index.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")

    record_counts: dict[str, int] = {}
    for record in records:
        record_counts[record["record_type"]] = record_counts.get(record["record_type"], 0) + 1
    write_json(
        search_dir / "search_manifest.json",
        {
            "schema_version": "pdfrejuvenator.search.v0.3",
            "status": "PASS",
            "run_root": str(run_root),
            "index": str(index_path),
            "record_count": len(records),
            "record_counts": record_counts,
            "privacy": {
                "source_pdf_not_copied": True,
                "contains_extracted_text": True,
                "intended_scope": "local/private validation and future local digestion",
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local PDFRejuvenator search index.")
    parser.add_argument("--run-root", type=Path, required=True, help="Internal run root containing pipeline/book_manifest.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Consolidated output directory that receives _search.")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    output_dir = args.output_dir.resolve()
    records = build_records(run_root)
    write_index(output_dir, records, run_root)
    print(f"SEARCH_INDEX={output_dir / '_search' / 'search_index.jsonl'}")
    print(f"SEARCH_RECORDS={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
