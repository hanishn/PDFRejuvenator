import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scrub_public_export.py"
SPEC = importlib.util.spec_from_file_location("public_scrubber", SCRIPT)
scrubber = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scrubber
SPEC.loader.exec_module(scrubber)


def test_reject_binary_and_document_assets(tmp_path):
    for name in ("private.docx", "private.png", "private.zip", "private.pdf"):
        (tmp_path / name).write_bytes(b"synthetic")
    findings = scrubber.scan_root(tmp_path, [])
    assert {str(f.path) for f in findings} == {
        "private.docx", "private.png", "private.zip", "private.pdf"}
    assert all(f.category == "unapproved binary asset" for f in findings)


def test_extensionless_text_and_external_denylist(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("SYNTHETIC_RESTRICTED_MARKER\n")
    patterns = scrubber.load_extra_patterns(terms)
    terms.unlink()
    (tmp_path / "LICENSE").write_text("SYNTHETIC_RESTRICTED_MARKER")
    findings = scrubber.scan_root(tmp_path, patterns)
    assert len(findings) == 1
    assert findings[0].category == "external denylist"


def test_binary_disguised_as_source_is_rejected(tmp_path):
    (tmp_path / "disguised.txt").write_bytes(bytes([255, 254]))
    findings = scrubber.scan_root(tmp_path, [])
    assert len(findings) == 1
    assert findings[0].category == "non-text payload"


def test_scrubber_itself_is_not_exempt_from_private_denylist(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("SYNTHETIC_RESTRICTED_MARKER")
    patterns = scrubber.load_extra_patterns(terms)
    terms.unlink()
    (tmp_path / scrubber.SELF_NAME).write_text("SYNTHETIC_RESTRICTED_MARKER")
    findings = scrubber.scan_root(tmp_path, patterns)
    assert len(findings) == 1
    assert findings[0].category == "external denylist"
