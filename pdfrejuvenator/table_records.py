from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfrejuvenator.private_workspace import path_is_within


TABLE_RECORD_SCHEMA_VERSION = "0.5.0-table-records-v1"


@dataclass(frozen=True)
class TableRecord:
    schema_version: str
    corpus_id: str
    book_id: str
    source_sha256: str
    page_number: int
    table_id: str
    caption: str
    cells: list[list[str]]
    confidence: float
    extraction_method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "book_id": self.book_id,
            "source_sha256": self.source_sha256,
            "page_number": self.page_number,
            "table_id": self.table_id,
            "caption": self.caption,
            "cells": [list(row) for row in self.cells],
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
        }


def normalize_cells(cells: list[list[object]]) -> list[list[str]]:
    width = max((len(row) for row in cells), default=0)
    normalized: list[list[str]] = []
    for row in cells:
        normalized.append([str(cell) for cell in row] + [""] * (width - len(row)))
    return normalized


def build_table_record(
    *,
    corpus_id: str,
    book_id: str,
    source_sha256: str,
    page_number: int,
    table_id: str,
    caption: str,
    cells: list[list[object]],
    confidence: float,
    extraction_method: str = "synthetic_table_fixture",
) -> TableRecord:
    return TableRecord(
        schema_version=TABLE_RECORD_SCHEMA_VERSION,
        corpus_id=corpus_id,
        book_id=book_id,
        source_sha256=source_sha256,
        page_number=page_number,
        table_id=table_id,
        caption=caption,
        cells=normalize_cells(cells),
        confidence=confidence,
        extraction_method=extraction_method,
    )


def write_table_records(records: list[TableRecord], output: Path, *, private_workspace_root: Path | None = None) -> int:
    resolved_output = output.resolve()
    if private_workspace_root and not path_is_within(resolved_output, private_workspace_root):
        raise ValueError("table records output must be inside the private workspace")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TABLE_RECORD_SCHEMA_VERSION,
        "records": [record.to_dict() for record in records],
    }
    resolved_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(records)


def validate_table_record_payload(path: Path) -> list[str]:
    issues: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != TABLE_RECORD_SCHEMA_VERSION:
        issues.append("unsupported schema_version")
    records = data.get("records")
    if not isinstance(records, list):
        return [*issues, "records must be a list"]
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if record.get("schema_version") != TABLE_RECORD_SCHEMA_VERSION:
            issues.append(f"{prefix}.schema_version unsupported")
        if not record.get("corpus_id"):
            issues.append(f"{prefix}.corpus_id required")
        if not record.get("book_id"):
            issues.append(f"{prefix}.book_id required")
        if len(str(record.get("source_sha256", ""))) != 64:
            issues.append(f"{prefix}.source_sha256 invalid")
        if not isinstance(record.get("page_number"), int) or record["page_number"] < 1:
            issues.append(f"{prefix}.page_number invalid")
        if not record.get("table_id"):
            issues.append(f"{prefix}.table_id required")
        cells = record.get("cells")
        if not isinstance(cells, list) or not cells:
            issues.append(f"{prefix}.cells required")
        elif not all(isinstance(row, list) for row in cells):
            issues.append(f"{prefix}.cells rows must be lists")
        else:
            widths = {len(row) for row in cells}
            if len(widths) != 1:
                issues.append(f"{prefix}.cells rows must have a consistent width")
            if not all(isinstance(cell, str) for row in cells for cell in row):
                issues.append(f"{prefix}.cells values must be strings")
        confidence = record.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            issues.append(f"{prefix}.confidence invalid")
    return issues
