from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class PrivacyClass(StrEnum):
    PUBLIC_SAMPLE = "public_sample"
    PRIVATE_SOURCE = "private_source"
    RESTRICTED_SOURCE = "restricted_source"


class RightsClass(StrEnum):
    ORIGINAL = "original"
    LICENSED_PRIVATE = "licensed_private"
    UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"


class IntakeState(StrEnum):
    REGISTERED = "registered"
    BLOCKED = "blocked"
    READY_FOR_PROBE = "ready_for_probe"
    READY_FOR_OCR = "ready_for_ocr"
    PROCESSED = "processed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class ProcessingIntent(StrEnum):
    INVENTORY_ONLY = "inventory_only"
    STRUCTURE_PROBE = "structure_probe"
    OCR_PENDING_APPROVAL = "ocr_pending_approval"
    OCR_APPROVED_PRIVATE = "ocr_approved_private"


PUBLIC_SAFE_PRIVACY_CLASSES = {PrivacyClass.PUBLIC_SAMPLE}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class CorpusRegistryEntry:
    corpus_id: str
    book_id: str
    display_name: str
    source_path: str
    sha256: str
    file_size_bytes: int
    page_count: int | None
    privacy_class: PrivacyClass
    rights_class: RightsClass
    intake_state: IntakeState
    processing_intent: ProcessingIntent
    created_at: str
    updated_at: str
    evidence_paths: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "book_id": self.book_id,
            "display_name": self.display_name,
            "source_path": self.source_path,
            "sha256": self.sha256,
            "file_size_bytes": self.file_size_bytes,
            "page_count": self.page_count,
            "privacy_class": self.privacy_class.value,
            "rights_class": self.rights_class.value,
            "intake_state": self.intake_state.value,
            "processing_intent": self.processing_intent.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "evidence_paths": list(self.evidence_paths),
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class IngestionManifest:
    manifest_version: str
    batch_id: str
    generated_at: str
    entries: list[CorpusRegistryEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "batch_id": self.batch_id,
            "generated_at": self.generated_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_book_id(path: Path) -> str:
    stem = path.stem.lower()
    safe = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return safe or "source-document"


def pdf_page_count(path: Path) -> int | None:
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(path) as document:
        return document.page_count


def build_registry_entry(
    path: Path,
    *,
    corpus_id: str,
    privacy_class: PrivacyClass,
    rights_class: RightsClass,
    intake_state: IntakeState = IntakeState.REGISTERED,
    processing_intent: ProcessingIntent = ProcessingIntent.INVENTORY_ONLY,
    display_name: str | None = None,
    source_root: Path | None = None,
) -> CorpusRegistryEntry:
    resolved = path.resolve()
    root = source_root.resolve() if source_root else resolved.parent
    try:
        source_path = resolved.relative_to(root).as_posix()
    except ValueError:
        source_path = resolved.name
    now = utc_now_iso()
    return CorpusRegistryEntry(
        corpus_id=corpus_id,
        book_id=safe_book_id(resolved),
        display_name=display_name or safe_book_id(resolved),
        source_path=source_path,
        sha256=file_sha256(resolved),
        file_size_bytes=resolved.stat().st_size,
        page_count=pdf_page_count(resolved),
        privacy_class=privacy_class,
        rights_class=rights_class,
        intake_state=intake_state,
        processing_intent=processing_intent,
        created_at=now,
        updated_at=now,
    )


def discover_source_pdfs(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*.pdf") if path.is_file())


def build_inventory_manifest(
    source_root: Path,
    *,
    corpus_id: str,
    batch_id: str,
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE_SOURCE,
    rights_class: RightsClass = RightsClass.UNKNOWN_REVIEW_REQUIRED,
) -> IngestionManifest:
    entries = [
        build_registry_entry(
            path,
            corpus_id=corpus_id,
            privacy_class=privacy_class,
            rights_class=rights_class,
            source_root=source_root,
        )
        for path in discover_source_pdfs(source_root)
    ]
    return IngestionManifest(
        manifest_version="0.4.0-intake-v1",
        batch_id=batch_id,
        generated_at=utc_now_iso(),
        entries=entries,
    )


def validate_registry_entry(entry: CorpusRegistryEntry) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not entry.corpus_id:
        issues.append(ValidationIssue("corpus_id", "corpus_id is required"))
    if not entry.book_id:
        issues.append(ValidationIssue("book_id", "book_id is required"))
    if not entry.display_name:
        issues.append(ValidationIssue("display_name", "display_name is required"))
    if len(entry.sha256) != 64 or any(char not in "0123456789abcdef" for char in entry.sha256.lower()):
        issues.append(ValidationIssue("sha256", "sha256 must be a 64-character hex digest"))
    if entry.file_size_bytes < 0:
        issues.append(ValidationIssue("file_size_bytes", "file_size_bytes must be non-negative"))
    if entry.page_count is not None and entry.page_count < 1:
        issues.append(ValidationIssue("page_count", "page_count must be null or greater than zero"))
    if entry.privacy_class not in PUBLIC_SAFE_PRIVACY_CLASSES and entry.processing_intent == ProcessingIntent.OCR_APPROVED_PRIVATE:
        issues.append(ValidationIssue("processing_intent", "private OCR requires a separate recorded approval gate"))
    if entry.intake_state == IntakeState.BLOCKED and not entry.blocked_reason:
        issues.append(ValidationIssue("blocked_reason", "blocked entries require blocked_reason"))
    if entry.intake_state != IntakeState.BLOCKED and entry.blocked_reason:
        issues.append(ValidationIssue("blocked_reason", "blocked_reason is only valid for blocked entries"))
    return issues


def validate_manifest(manifest: IngestionManifest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if manifest.manifest_version != "0.4.0-intake-v1":
        issues.append(ValidationIssue("manifest_version", "unsupported manifest_version"))
    if not manifest.batch_id:
        issues.append(ValidationIssue("batch_id", "batch_id is required"))
    seen_hashes: dict[str, str] = {}
    for index, entry in enumerate(manifest.entries):
        prefix = f"entries[{index}]"
        for issue in validate_registry_entry(entry):
            issues.append(ValidationIssue(f"{prefix}.{issue.path}", issue.message))
        existing = seen_hashes.get(entry.sha256)
        if existing and existing != entry.book_id:
            issues.append(ValidationIssue(f"{prefix}.sha256", f"duplicate source hash also used by {existing}"))
        seen_hashes[entry.sha256] = entry.book_id
    return issues


def manifest_to_json(manifest: IngestionManifest) -> str:
    return json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
