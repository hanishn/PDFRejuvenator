from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_intake import (  # noqa: E402
    CorpusRegistryEntry,
    IngestionManifest,
    IntakeState,
    PrivacyClass,
    ProcessingIntent,
    RightsClass,
    build_inventory_manifest,
    manifest_to_json,
    validate_manifest,
    validate_registry_entry,
)


def synthetic_entry(
    *,
    book_id: str = "synthetic-book-001",
    sha256: str = "a" * 64,
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC_SAMPLE,
    intake_state: IntakeState = IntakeState.REGISTERED,
    processing_intent: ProcessingIntent = ProcessingIntent.INVENTORY_ONLY,
    blocked_reason: str | None = None,
) -> CorpusRegistryEntry:
    return CorpusRegistryEntry(
        corpus_id="synthetic-corpus",
        book_id=book_id,
        display_name="Synthetic Fixture Book",
        source_path="samples/synthetic_fixture.pdf",
        sha256=sha256,
        file_size_bytes=12345,
        page_count=3,
        privacy_class=privacy_class,
        rights_class=RightsClass.ORIGINAL,
        intake_state=intake_state,
        processing_intent=processing_intent,
        created_at="2026-07-11T00:00:00Z",
        updated_at="2026-07-11T00:00:00Z",
        blocked_reason=blocked_reason,
    )


def check(name: str, passed: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, passed, detail


def run_checks() -> list[tuple[str, bool, str]]:
    valid_entry = synthetic_entry()
    valid_manifest = IngestionManifest(
        manifest_version="0.4.0-intake-v1",
        batch_id="synthetic-batch",
        generated_at="2026-07-11T00:00:00Z",
        entries=[valid_entry],
    )
    blocked_entry = synthetic_entry(
        book_id="synthetic-book-002",
        sha256="b" * 64,
        intake_state=IntakeState.BLOCKED,
        blocked_reason="rights review required",
    )
    invalid_private_ocr = synthetic_entry(
        privacy_class=PrivacyClass.PRIVATE_SOURCE,
        processing_intent=ProcessingIntent.OCR_APPROVED_PRIVATE,
    )
    duplicate_manifest = IngestionManifest(
        manifest_version="0.4.0-intake-v1",
        batch_id="synthetic-batch-duplicate",
        generated_at="2026-07-11T00:00:00Z",
        entries=[
            synthetic_entry(book_id="synthetic-book-a", sha256="c" * 64),
            synthetic_entry(book_id="synthetic-book-b", sha256="c" * 64),
        ],
    )
    rendered_json = manifest_to_json(valid_manifest)
    sample_root = ROOT / "samples"
    sample_manifest = build_inventory_manifest(
        sample_root,
        corpus_id="public-sample-corpus",
        batch_id="public-sample-batch",
        privacy_class=PrivacyClass.PUBLIC_SAMPLE,
        rights_class=RightsClass.ORIGINAL,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        manifest_path = Path(temp_dir) / "inventory_manifest.json"
        manifest_path.write_text(manifest_to_json(sample_manifest), encoding="utf-8")
        manifest_written = manifest_path.exists() and manifest_path.stat().st_size > 0
    return [
        check("valid registry entry", not validate_registry_entry(valid_entry)),
        check("valid manifest", not validate_manifest(valid_manifest)),
        check("blocked entry with reason", not validate_registry_entry(blocked_entry)),
        check(
            "private OCR approval gate",
            any(issue.path == "processing_intent" for issue in validate_registry_entry(invalid_private_ocr)),
        ),
        check(
            "duplicate hash detection",
            any(issue.path.endswith(".sha256") for issue in validate_manifest(duplicate_manifest)),
        ),
        check("manifest JSON serialization", '"manifest_version": "0.4.0-intake-v1"' in rendered_json),
        check("sample inventory entries", len(sample_manifest.entries) >= 1),
        check("sample inventory page counts", all(entry.page_count and entry.page_count > 0 for entry in sample_manifest.entries)),
        check("sample inventory manifest validation", not validate_manifest(sample_manifest)),
        check("sample inventory manifest write", manifest_written),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"CORPUS INTAKE SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
