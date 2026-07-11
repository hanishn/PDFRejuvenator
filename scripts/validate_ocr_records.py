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
from pdfrejuvenator.ocr_records import (  # noqa: E402
    OCR_RECORD_SCHEMA_VERSION,
    build_ocr_records_from_manifest,
    validate_ocr_record_payload,
)
from pdfrejuvenator.private_workspace import init_private_workspace  # noqa: E402


def check(name: str, passed: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, passed, detail


def run_checks() -> list[tuple[str, bool, str]]:
    sample_root = ROOT / "samples"
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        private_workspace = temp_root / "private_workspace"
        init_private_workspace(private_workspace, corpus_id="synthetic-private-corpus")

        manifest = build_inventory_manifest(
            sample_root,
            corpus_id="public-sample-corpus",
            batch_id="ocr-records-batch",
            privacy_class=PrivacyClass.PUBLIC_SAMPLE,
            rights_class=RightsClass.ORIGINAL,
        )
        manifest_path = private_workspace / "manifests" / "sample_manifest.json"
        manifest_path.write_text(manifest_to_json(manifest), encoding="utf-8")
        output = private_workspace / "derived" / "ocr" / "sample_ocr_records.json"
        record_count = build_ocr_records_from_manifest(
            manifest_path,
            source_root=sample_root,
            private_workspace_root=private_workspace,
            output=output,
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        records = payload["records"]
        validation_issues = validate_ocr_record_payload(output)
        output_exists = output.exists()
        outside_rejected = False
        try:
            build_ocr_records_from_manifest(
                manifest_path,
                source_root=sample_root,
                private_workspace_root=private_workspace,
                output=temp_root / "outside_ocr_records.json",
            )
        except ValueError:
            outside_rejected = True

    return [
        check("ocr records written", output_exists),
        check("ocr records schema version", payload.get("schema_version") == OCR_RECORD_SCHEMA_VERSION),
        check("ocr records count", record_count == len(records) and record_count >= 1),
        check("ocr records payload validation", not validation_issues, "; ".join(validation_issues)),
        check("ocr record text hash", all(len(record["text_sha256"]) == 64 for record in records)),
        check("ocr record source hash", all(len(record["source_sha256"]) == 64 for record in records)),
        check("ocr record page numbers", all(isinstance(record["page_number"], int) and record["page_number"] >= 1 for record in records)),
        check("ocr record confidence bounds", all(0 <= float(record["confidence"]) <= 1 for record in records)),
        check("ocr private output enforcement", outside_rejected),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"OCR RECORDS SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
