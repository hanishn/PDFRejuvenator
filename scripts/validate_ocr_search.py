from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_intake import (  # noqa: E402
    PrivacyClass,
    RightsClass,
    build_inventory_manifest,
    manifest_to_json,
)
from pdfrejuvenator.corpus_search import (  # noqa: E402
    OCR_RECORD_SEARCH_SCHEMA_VERSION,
    SEARCH_SCHEMA_VERSION,
    build_index_from_ocr_records,
)
from pdfrejuvenator.ocr_records import build_ocr_records_from_manifest  # noqa: E402
from pdfrejuvenator.private_workspace import init_private_workspace  # noqa: E402


def check(name: str, passed: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, passed, detail


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_checks() -> list[tuple[str, bool, str]]:
    sample_root = ROOT / "samples"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        private_workspace = temp_root / "private_workspace"
        init_private_workspace(private_workspace, corpus_id="synthetic-private-corpus")

        manifest = build_inventory_manifest(
            sample_root,
            corpus_id="public-sample-corpus",
            batch_id="ocr-search-batch",
            privacy_class=PrivacyClass.PUBLIC_SAMPLE,
            rights_class=RightsClass.ORIGINAL,
        )
        manifest_path = private_workspace / "manifests" / "sample_manifest.json"
        manifest_path.write_text(manifest_to_json(manifest), encoding="utf-8")
        ocr_records = private_workspace / "derived" / "ocr" / "sample_ocr_records.json"
        ocr_count = build_ocr_records_from_manifest(
            manifest_path,
            source_root=sample_root,
            private_workspace_root=private_workspace,
            output=ocr_records,
        )
        index_path = private_workspace / "indexes" / "sample_ocr_index.jsonl"
        index_count = build_index_from_ocr_records(ocr_records, index_path)
        index_records = read_jsonl(index_path)
        record_types = {record.get("record_type") for record in index_records}
        source_versions = {record.get("source_schema_version") for record in index_records}
        privacy_scopes = {record.get("metadata", {}).get("privacy_scope") for record in index_records if isinstance(record.get("metadata"), dict)}
        text_hashes = [record.get("metadata", {}).get("text_sha256") for record in index_records if isinstance(record.get("metadata"), dict)]
        output_exists = index_path.exists()

    return [
        check("ocr search index written", output_exists),
        check("ocr search count", index_count == ocr_count and index_count == len(index_records) and index_count >= 1),
        check("ocr search schema", all(record.get("schema_version") == SEARCH_SCHEMA_VERSION for record in index_records)),
        check("ocr search source schema", source_versions == {OCR_RECORD_SEARCH_SCHEMA_VERSION}),
        check("ocr search record type", record_types == {"private_ocr_page"}),
        check("ocr search privacy scope", privacy_scopes == {"private_local_only"}),
        check("ocr search text hash metadata", all(isinstance(value, str) and len(value) == 64 for value in text_hashes)),
        check("ocr search page numbers", all(isinstance(record.get("page"), int) and record["page"] >= 1 for record in index_records)),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"OCR SEARCH SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
