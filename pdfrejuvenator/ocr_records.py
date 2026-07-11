from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfrejuvenator.private_workspace import path_is_within


OCR_RECORD_SCHEMA_VERSION = "0.5.0-ocr-records-v1"


@dataclass(frozen=True)
class OcrPageRecord:
    schema_version: str
    corpus_id: str
    book_id: str
    source_sha256: str
    page_number: int
    extraction_method: str
    text: str
    text_sha256: str
    char_count: int
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "book_id": self.book_id,
            "source_sha256": self.source_sha256,
            "page_number": self.page_number,
            "extraction_method": self.extraction_method,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "char_count": self.char_count,
            "confidence": self.confidence,
        }


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_pdf_ocr_records(
    source_pdf: Path,
    *,
    corpus_id: str,
    book_id: str,
    source_sha256: str,
    extraction_method: str = "pymupdf_text",
) -> list[OcrPageRecord]:
    import fitz

    records: list[OcrPageRecord] = []
    with fitz.open(source_pdf) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text")
            stripped = text.strip()
            records.append(
                OcrPageRecord(
                    schema_version=OCR_RECORD_SCHEMA_VERSION,
                    corpus_id=corpus_id,
                    book_id=book_id,
                    source_sha256=source_sha256,
                    page_number=page_index,
                    extraction_method=extraction_method,
                    text=text,
                    text_sha256=text_sha256(text),
                    char_count=len(text),
                    confidence=1.0 if stripped else 0.0,
                )
            )
    return records


def write_ocr_records(records: list[OcrPageRecord], output: Path, *, private_workspace_root: Path) -> int:
    resolved_output = output.resolve()
    if not path_is_within(resolved_output, private_workspace_root):
        raise ValueError("OCR records output must be inside the private workspace")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": OCR_RECORD_SCHEMA_VERSION,
        "records": [record.to_dict() for record in records],
    }
    resolved_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(records)


def load_manifest_entries(manifest_path: Path) -> list[dict[str, Any]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")
    return entries


def build_ocr_records_from_manifest(
    manifest_path: Path,
    *,
    source_root: Path,
    private_workspace_root: Path,
    output: Path,
) -> int:
    all_records: list[OcrPageRecord] = []
    for entry in load_manifest_entries(manifest_path):
        source_path = source_root / str(entry["source_path"])
        all_records.extend(
            extract_pdf_ocr_records(
                source_path,
                corpus_id=str(entry["corpus_id"]),
                book_id=str(entry["book_id"]),
                source_sha256=str(entry["sha256"]),
            )
        )
    return write_ocr_records(all_records, output, private_workspace_root=private_workspace_root)


def validate_ocr_record_payload(path: Path) -> list[str]:
    issues: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != OCR_RECORD_SCHEMA_VERSION:
        issues.append("unsupported schema_version")
    records = data.get("records")
    if not isinstance(records, list):
        return [*issues, "records must be a list"]
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if record.get("schema_version") != OCR_RECORD_SCHEMA_VERSION:
            issues.append(f"{prefix}.schema_version unsupported")
        if not record.get("corpus_id"):
            issues.append(f"{prefix}.corpus_id required")
        if not record.get("book_id"):
            issues.append(f"{prefix}.book_id required")
        if len(str(record.get("source_sha256", ""))) != 64:
            issues.append(f"{prefix}.source_sha256 invalid")
        if not isinstance(record.get("page_number"), int) or record["page_number"] < 1:
            issues.append(f"{prefix}.page_number invalid")
        text = record.get("text")
        if not isinstance(text, str):
            issues.append(f"{prefix}.text required")
        expected_hash = text_sha256(text) if isinstance(text, str) else None
        if record.get("text_sha256") != expected_hash:
            issues.append(f"{prefix}.text_sha256 mismatch")
        if record.get("char_count") != (len(text) if isinstance(text, str) else None):
            issues.append(f"{prefix}.char_count mismatch")
        confidence = record.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            issues.append(f"{prefix}.confidence invalid")
    return issues
