from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfrejuvenator.corpus_intake import utc_now_iso


WORKSPACE_CONFIG_NAME = "pdfrejuvenator_private_workspace.json"
WORKSPACE_LAYOUT_VERSION = "0.5.0-private-workspace-v1"
PRIVATE_WORKSPACE_DIRS = (
    "source_private",
    "manifests",
    "derived/ocr",
    "derived/tables",
    "derived/images",
    "indexes",
    "evidence",
)


@dataclass(frozen=True)
class PrivateWorkspaceIssue:
    path: str
    message: str


@dataclass(frozen=True)
class PrivateWorkspaceConfig:
    layout_version: str
    workspace_root: str
    corpus_id: str
    created_at: str
    public_export_allowed: bool
    release_scope: str
    paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_version": self.layout_version,
            "workspace_root": self.workspace_root,
            "corpus_id": self.corpus_id,
            "created_at": self.created_at,
            "public_export_allowed": self.public_export_allowed,
            "release_scope": self.release_scope,
            "paths": dict(self.paths),
        }


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def private_workspace_config_path(workspace_root: Path) -> Path:
    return workspace_root / WORKSPACE_CONFIG_NAME


def build_private_workspace_config(workspace_root: Path, *, corpus_id: str) -> PrivateWorkspaceConfig:
    resolved = workspace_root.resolve()
    return PrivateWorkspaceConfig(
        layout_version=WORKSPACE_LAYOUT_VERSION,
        workspace_root=str(resolved),
        corpus_id=corpus_id,
        created_at=utc_now_iso(),
        public_export_allowed=False,
        release_scope="private_local_only",
        paths={name.replace("/", "_"): name for name in PRIVATE_WORKSPACE_DIRS},
    )


def write_private_workspace_config(config: PrivateWorkspaceConfig, output: Path) -> None:
    output.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_private_workspace_config(workspace_root: Path) -> PrivateWorkspaceConfig:
    data = json.loads(private_workspace_config_path(workspace_root).read_text(encoding="utf-8"))
    return PrivateWorkspaceConfig(
        layout_version=data["layout_version"],
        workspace_root=data["workspace_root"],
        corpus_id=data["corpus_id"],
        created_at=data["created_at"],
        public_export_allowed=bool(data["public_export_allowed"]),
        release_scope=data["release_scope"],
        paths=dict(data["paths"]),
    )


def init_private_workspace(workspace_root: Path, *, corpus_id: str = "private-corpus") -> PrivateWorkspaceConfig:
    root = workspace_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative in PRIVATE_WORKSPACE_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n!pdfrejuvenator_private_workspace.json\n", encoding="utf-8")
    config = build_private_workspace_config(root, corpus_id=corpus_id)
    write_private_workspace_config(config, private_workspace_config_path(root))
    return config


def validate_private_workspace(
    workspace_root: Path,
    *,
    public_repo_root: Path | None = None,
) -> list[PrivateWorkspaceIssue]:
    issues: list[PrivateWorkspaceIssue] = []
    root = workspace_root.resolve()
    if not root.exists() or not root.is_dir():
        return [PrivateWorkspaceIssue(str(root), "workspace root must exist and be a directory")]

    config_path = private_workspace_config_path(root)
    if not config_path.exists():
        issues.append(PrivateWorkspaceIssue(_safe_relative(config_path, root), "workspace config is missing"))
        config: PrivateWorkspaceConfig | None = None
    else:
        try:
            config = load_private_workspace_config(root)
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            issues.append(PrivateWorkspaceIssue(_safe_relative(config_path, root), f"workspace config is invalid: {exc}"))
            config = None

    if public_repo_root and path_is_within(root, public_repo_root):
        issues.append(PrivateWorkspaceIssue(str(root), "private workspace must not be inside the public repository"))

    for relative in PRIVATE_WORKSPACE_DIRS:
        required = root / relative
        if not required.exists() or not required.is_dir():
            issues.append(PrivateWorkspaceIssue(relative, "required private workspace directory is missing"))

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        issues.append(PrivateWorkspaceIssue(".gitignore", "private workspace .gitignore is missing"))
    else:
        ignore_text = gitignore.read_text(encoding="utf-8")
        if "*" not in ignore_text:
            issues.append(PrivateWorkspaceIssue(".gitignore", "private workspace .gitignore must ignore private artifacts by default"))

    if config:
        if config.layout_version != WORKSPACE_LAYOUT_VERSION:
            issues.append(PrivateWorkspaceIssue(WORKSPACE_CONFIG_NAME, "unsupported private workspace layout_version"))
        if Path(config.workspace_root).resolve() != root:
            issues.append(PrivateWorkspaceIssue(WORKSPACE_CONFIG_NAME, "workspace_root does not match the validated directory"))
        if config.public_export_allowed:
            issues.append(PrivateWorkspaceIssue(WORKSPACE_CONFIG_NAME, "private workspace must not be public-export allowed"))
        if config.release_scope != "private_local_only":
            issues.append(PrivateWorkspaceIssue(WORKSPACE_CONFIG_NAME, "release_scope must be private_local_only"))
        if not config.corpus_id:
            issues.append(PrivateWorkspaceIssue(WORKSPACE_CONFIG_NAME, "corpus_id is required"))

    return issues


def classify_workspace_path(path: Path, *, private_workspace_root: Path, public_repo_root: Path) -> str:
    if path_is_within(path, private_workspace_root):
        return "private_workspace"
    if path_is_within(path, public_repo_root):
        return "public_repo"
    return "external"
