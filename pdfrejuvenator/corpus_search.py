from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SEARCH_SCHEMA_VERSION = "pdfrejuvenator.corpus_search.v0.4"
TEXT_RECORD_SCHEMA_VERSION = "pdfrejuvenator.text_record.v0.4"
TABLE_RECORD_SCHEMA_VERSION = "pdfrejuvenator.table_record.v0.4"
IMAGE_RECORD_SCHEMA_VERSION = "pdfrejuvenator.image_record.v0.4"


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_entries_to_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    batch_id = str(manifest.get("batch_id", ""))
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        book_id = str(entry.get("book_id", ""))
        text_parts = [
            entry.get("display_name", ""),
            entry.get("book_id", ""),
            entry.get("privacy_class", ""),
            entry.get("rights_class", ""),
            entry.get("intake_state", ""),
            entry.get("processing_intent", ""),
        ]
        records.append(
            {
                "schema_version": SEARCH_SCHEMA_VERSION,
                "record_id": "::".join(part for part in [batch_id, book_id, "inventory"] if part),
                "batch_id": batch_id,
                "book_id": book_id,
                "record_type": "inventory_entry",
                "text": " ".join(str(part) for part in text_parts if part),
                "page": 0,
                "artifact_path": "",
                "metadata": {
                    "source_path": entry.get("source_path", ""),
                    "sha256": entry.get("sha256", ""),
                    "file_size_bytes": entry.get("file_size_bytes"),
                    "page_count": entry.get("page_count"),
                    "privacy_class": entry.get("privacy_class", ""),
                    "rights_class": entry.get("rights_class", ""),
                    "intake_state": entry.get("intake_state", ""),
                    "processing_intent": entry.get("processing_intent", ""),
                },
            }
        )
    return records


def text_entries_to_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    batch_id = str(payload.get("batch_id", ""))
    records: list[dict[str, Any]] = []
    for entry in payload.get("records", []):
        if not isinstance(entry, dict):
            continue
        book_id = str(entry.get("book_id", ""))
        page = int(entry.get("page", 0) or 0)
        record_id = str(entry.get("record_id") or "::".join([batch_id, book_id, f"p{page:03d}", "text"]))
        records.append(
            {
                "schema_version": SEARCH_SCHEMA_VERSION,
                "source_schema_version": TEXT_RECORD_SCHEMA_VERSION,
                "record_id": record_id,
                "batch_id": batch_id,
                "book_id": book_id,
                "record_type": "synthetic_text",
                "text": str(entry.get("text", "")),
                "page": page,
                "artifact_path": str(entry.get("artifact_path", "")),
                "metadata": {
                    "section": entry.get("section", ""),
                    "confidence": entry.get("confidence"),
                    "source": entry.get("source", "synthetic_fixture"),
                },
            }
        )
    return records


def table_entries_to_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    batch_id = str(payload.get("batch_id", ""))
    records: list[dict[str, Any]] = []
    for entry in payload.get("records", []):
        if not isinstance(entry, dict):
            continue
        book_id = str(entry.get("book_id", ""))
        page = int(entry.get("page", 0) or 0)
        table_id = str(entry.get("table_id", "table"))
        cells = entry.get("cells", [])
        cell_text = " ".join(str(cell) for row in cells if isinstance(row, list) for cell in row)
        text = " ".join(str(part) for part in [entry.get("caption", ""), table_id, cell_text] if part)
        records.append(
            {
                "schema_version": SEARCH_SCHEMA_VERSION,
                "source_schema_version": TABLE_RECORD_SCHEMA_VERSION,
                "record_id": str(entry.get("record_id") or "::".join([batch_id, book_id, f"p{page:03d}", table_id])),
                "batch_id": batch_id,
                "book_id": book_id,
                "record_type": "synthetic_table",
                "text": text,
                "page": page,
                "artifact_path": str(entry.get("artifact_path", "")),
                "metadata": {
                    "table_id": table_id,
                    "caption": entry.get("caption", ""),
                    "row_count": len(cells) if isinstance(cells, list) else 0,
                    "column_count": max((len(row) for row in cells if isinstance(row, list)), default=0),
                    "source": entry.get("source", "synthetic_fixture"),
                },
            }
        )
    return records


def image_entries_to_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    batch_id = str(payload.get("batch_id", ""))
    records: list[dict[str, Any]] = []
    for entry in payload.get("records", []):
        if not isinstance(entry, dict):
            continue
        book_id = str(entry.get("book_id", ""))
        page = int(entry.get("page", 0) or 0)
        image_id = str(entry.get("image_id", "image"))
        text = " ".join(
            str(part)
            for part in [
                entry.get("label", ""),
                entry.get("classification", ""),
                entry.get("alt_text", ""),
                image_id,
            ]
            if part
        )
        records.append(
            {
                "schema_version": SEARCH_SCHEMA_VERSION,
                "source_schema_version": IMAGE_RECORD_SCHEMA_VERSION,
                "record_id": str(entry.get("record_id") or "::".join([batch_id, book_id, f"p{page:03d}", image_id])),
                "batch_id": batch_id,
                "book_id": book_id,
                "record_type": "synthetic_image",
                "text": text,
                "page": page,
                "artifact_path": str(entry.get("artifact_path", "")),
                "metadata": {
                    "image_id": image_id,
                    "label": entry.get("label", ""),
                    "classification": entry.get("classification", ""),
                    "width_px": entry.get("width_px"),
                    "height_px": entry.get("height_px"),
                    "source": entry.get("source", "synthetic_fixture"),
                },
            }
        )
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_index_from_manifest(manifest_path: Path, output_path: Path) -> int:
    manifest = load_manifest(manifest_path)
    records = manifest_entries_to_records(manifest)
    write_jsonl(output_path, records)
    return len(records)


def build_index_from_text_records(text_records_path: Path, output_path: Path) -> int:
    payload = json.loads(text_records_path.read_text(encoding="utf-8"))
    records = text_entries_to_records(payload)
    write_jsonl(output_path, records)
    return len(records)


def build_index_from_table_records(table_records_path: Path, output_path: Path) -> int:
    payload = json.loads(table_records_path.read_text(encoding="utf-8"))
    records = table_entries_to_records(payload)
    write_jsonl(output_path, records)
    return len(records)


def build_index_from_image_records(image_records_path: Path, output_path: Path) -> int:
    payload = json.loads(image_records_path.read_text(encoding="utf-8"))
    records = image_entries_to_records(payload)
    write_jsonl(output_path, records)
    return len(records)
