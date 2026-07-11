from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_search import (  # noqa: E402
    SEARCH_SCHEMA_VERSION,
    IMAGE_RECORD_SCHEMA_VERSION,
    TABLE_RECORD_SCHEMA_VERSION,
    TEXT_RECORD_SCHEMA_VERSION,
    build_index_from_image_records,
    build_index_from_manifest,
    build_index_from_table_records,
    build_index_from_text_records,
    image_entries_to_records,
    manifest_entries_to_records,
    table_entries_to_records,
    text_entries_to_records,
)


def synthetic_manifest() -> dict[str, object]:
    return {
        "manifest_version": "0.4.0-intake-v1",
        "batch_id": "synthetic-search-batch",
        "generated_at": "2026-07-11T00:00:00Z",
        "entries": [
            {
                "book_id": "synthetic-search-book",
                "display_name": "Synthetic Search Fixture",
                "source_path": "synthetic_fixture.pdf",
                "sha256": "d" * 64,
                "file_size_bytes": 123,
                "page_count": 2,
                "privacy_class": "public_sample",
                "rights_class": "original",
                "intake_state": "registered",
                "processing_intent": "inventory_only",
            }
        ],
    }


def synthetic_text_payload() -> dict[str, object]:
    return {
        "schema_version": TEXT_RECORD_SCHEMA_VERSION,
        "batch_id": "synthetic-text-batch",
        "records": [
            {
                "record_id": "synthetic-text-batch::synthetic-book::p001::text",
                "book_id": "synthetic-book",
                "page": 1,
                "section": "sample section",
                "text": "Synthetic public-safe search fixture with arcology beacon terminology.",
                "confidence": 1.0,
                "source": "synthetic_fixture",
            }
        ],
    }


def synthetic_table_payload() -> dict[str, object]:
    return {
        "schema_version": TABLE_RECORD_SCHEMA_VERSION,
        "batch_id": "synthetic-table-batch",
        "records": [
            {
                "book_id": "synthetic-book",
                "page": 2,
                "table_id": "table-alpha",
                "caption": "Synthetic Resource Table",
                "cells": [["Resource", "Value"], ["Beacon", "42"]],
                "source": "synthetic_fixture",
            }
        ],
    }


def synthetic_image_payload() -> dict[str, object]:
    return {
        "schema_version": IMAGE_RECORD_SCHEMA_VERSION,
        "batch_id": "synthetic-image-batch",
        "records": [
            {
                "book_id": "synthetic-book",
                "page": 3,
                "image_id": "image-alpha",
                "label": "Synthetic Beacon Diagram",
                "classification": "diagram",
                "alt_text": "Public-safe synthetic image metadata fixture.",
                "width_px": 640,
                "height_px": 480,
                "source": "synthetic_fixture",
            }
        ],
    }


def run_checks() -> list[tuple[str, bool, str]]:
    manifest = synthetic_manifest()
    records = manifest_entries_to_records(manifest)
    text_payload = synthetic_text_payload()
    text_records = text_entries_to_records(text_payload)
    table_payload = synthetic_table_payload()
    table_records = table_entries_to_records(table_payload)
    image_payload = synthetic_image_payload()
    image_records = image_entries_to_records(image_payload)
    with tempfile.TemporaryDirectory() as temp_dir:
        manifest_path = Path(temp_dir) / "manifest.json"
        index_path = Path(temp_dir) / "index.jsonl"
        text_path = Path(temp_dir) / "text_records.json"
        text_index_path = Path(temp_dir) / "text_index.jsonl"
        table_path = Path(temp_dir) / "table_records.json"
        table_index_path = Path(temp_dir) / "table_index.jsonl"
        image_path = Path(temp_dir) / "image_records.json"
        image_index_path = Path(temp_dir) / "image_index.jsonl"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        count = build_index_from_manifest(manifest_path, index_path)
        text_path.write_text(json.dumps(text_payload), encoding="utf-8")
        text_count = build_index_from_text_records(text_path, text_index_path)
        table_path.write_text(json.dumps(table_payload), encoding="utf-8")
        table_count = build_index_from_table_records(table_path, table_index_path)
        image_path.write_text(json.dumps(image_payload), encoding="utf-8")
        image_count = build_index_from_image_records(image_path, image_index_path)
        lines = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
        text_lines = [json.loads(line) for line in text_index_path.read_text(encoding="utf-8").splitlines()]
        table_lines = [json.loads(line) for line in table_index_path.read_text(encoding="utf-8").splitlines()]
        image_lines = [json.loads(line) for line in image_index_path.read_text(encoding="utf-8").splitlines()]
    return [
        ("manifest record count", len(records) == 1, ""),
        ("index build count", count == 1, ""),
        ("index file lines", len(lines) == 1, ""),
        ("schema version", lines[0].get("schema_version") == SEARCH_SCHEMA_VERSION, ""),
        ("searchable text", "Synthetic Search Fixture" in lines[0].get("text", ""), ""),
        ("metadata page count", lines[0].get("metadata", {}).get("page_count") == 2, ""),
        ("text record count", len(text_records) == 1, ""),
        ("text index build count", text_count == 1, ""),
        ("text index file lines", len(text_lines) == 1, ""),
        ("text searchable content", "arcology beacon" in text_lines[0].get("text", ""), ""),
        ("table record count", len(table_records) == 1, ""),
        ("table index build count", table_count == 1, ""),
        ("table searchable content", "Beacon" in table_lines[0].get("text", ""), ""),
        ("table dimensions", table_lines[0].get("metadata", {}).get("column_count") == 2, ""),
        ("image record count", len(image_records) == 1, ""),
        ("image index build count", image_count == 1, ""),
        ("image searchable content", "Beacon Diagram" in image_lines[0].get("text", ""), ""),
        ("image metadata dimensions", image_lines[0].get("metadata", {}).get("width_px") == 640, ""),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"CORPUS SEARCH SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
