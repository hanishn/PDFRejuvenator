from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.private_workspace import (  # noqa: E402
    PRIVATE_WORKSPACE_DIRS,
    WORKSPACE_CONFIG_NAME,
    classify_workspace_path,
    init_private_workspace,
    validate_private_workspace,
)


def check(name: str, passed: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, passed, detail


def run_checks() -> list[tuple[str, bool, str]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        private_root = temp_root / "private_workspace"
        public_root = temp_root / "public_repo"
        public_root.mkdir()

        config = init_private_workspace(private_root, corpus_id="synthetic-private-corpus")
        issues = validate_private_workspace(private_root, public_repo_root=public_root)
        config_created = (private_root / WORKSPACE_CONFIG_NAME).exists()
        required_dirs_created = all((private_root / relative).exists() for relative in PRIVATE_WORKSPACE_DIRS)
        missing_dir = private_root / "derived" / "ocr"
        missing_dir.rmdir()
        missing_dir_issues = validate_private_workspace(private_root, public_repo_root=public_root)
        inside_public = public_root / "bad_private_workspace"
        init_private_workspace(inside_public, corpus_id="bad-layout")
        inside_public_issues = validate_private_workspace(inside_public, public_repo_root=public_root)
        private_classification = classify_workspace_path(private_root / "indexes" / "index.jsonl", private_workspace_root=private_root, public_repo_root=public_root)
        public_classification = classify_workspace_path(public_root / "README.md", private_workspace_root=private_root, public_repo_root=public_root)
        external_classification = classify_workspace_path(temp_root / "elsewhere" / "file.txt", private_workspace_root=private_root, public_repo_root=public_root)

    return [
        check("private workspace config created", config_created),
        check("private workspace config release scope", config.release_scope == "private_local_only"),
        check("private workspace public export disabled", not config.public_export_allowed),
        check("private workspace required dirs", required_dirs_created),
        check("private workspace validation", not issues),
        check(
            "private workspace missing dir detection",
            any(issue.path == "derived/ocr" for issue in missing_dir_issues),
        ),
        check(
            "private workspace public repo separation",
            any("public repository" in issue.message for issue in inside_public_issues),
        ),
        check("private path classification", private_classification == "private_workspace"),
        check("public path classification", public_classification == "public_repo"),
        check("external path classification", external_classification == "external"),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"PRIVATE WORKSPACE SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
