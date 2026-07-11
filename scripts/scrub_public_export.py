from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF_NAME = Path(__file__).name

TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".pdf",
}

SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
}

GENERATED_PARTS = {
    ".ruff_cache",
    "__pycache__",
}

GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

FORBIDDEN_PATTERNS = [
    ("private path", re.compile(r"\b[A-Z]:\\(?:Users\\[^\\\s]+|Projects\\[^\\\s]+)", re.IGNORECASE)),
    ("api key wording", re.compile(r"api[_ -]?key|apikey|secret|password|passwd|bearer\s+[A-Za-z0-9._-]+|authorization:", re.IGNORECASE)),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("openai style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

PUBLIC_SOURCE_PDF_PATTERNS = [
    re.compile(r"^source/shadow_power_play_sample_[0-9a-f]+\.pdf$", re.IGNORECASE),
]


def load_extra_patterns(path: Path | None) -> list[tuple[str, re.Pattern[str]]]:
    if path is None:
        return []
    terms = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [
        ("external denylist", re.compile(re.escape(term), re.IGNORECASE))
        for term in terms
        if term and not term.startswith("#")
    ]


@dataclass(frozen=True)
class Finding:
    category: str
    path: Path
    line_number: int
    line: str


def should_scan(path: Path) -> bool:
    if path.name == SELF_NAME:
        return False
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    return path.suffix.lower() in TEXT_SUFFIXES


def scan_file(path: Path, root: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    rel = path.relative_to(root)
    for line_number, line in enumerate(lines, start=1):
        for category, pattern in patterns:
            if pattern.search(line):
                findings.append(Finding(category, rel, line_number, line.strip()))
    return findings


def scan_path(path: Path, root: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    rel = path.relative_to(root)
    rel_posix = rel.as_posix()
    findings: list[Finding] = []
    if rel.suffix.lower() == ".pdf" and "source" in rel.parts:
        allowed_public_source_pdf = any(pattern.search(rel_posix) for pattern in PUBLIC_SOURCE_PDF_PATTERNS)
        if not allowed_public_source_pdf:
            findings.append(Finding("private source pdf", rel, 0, "source PDFs must be public sample fixtures only"))
    for category, pattern in patterns:
        if pattern.search(rel_posix):
            findings.append(Finding(category, rel, 0, "matched path"))
    return findings


def scan_pdf(path: Path, root: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    try:
        import fitz
    except ImportError:
        return [Finding("pdf scan unavailable", path.relative_to(root), 0, "PyMuPDF is required to scan PDF text")]

    findings: list[Finding] = []
    rel = path.relative_to(root)
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for category, pattern in patterns:
                    if pattern.search(line):
                        findings.append(Finding(category, rel, page_index * 10000 + line_number, line.strip()))
    return findings


def scan_root(root: Path, patterns: list[tuple[str, re.Pattern[str]]]) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        path_findings = scan_path(path, root, patterns)
        findings.extend(path_findings)
        if any(finding.category == "private source pdf" for finding in path_findings):
            continue
        if any(part in GENERATED_PARTS for part in rel.parts) or rel.suffix.lower() in GENERATED_SUFFIXES:
            findings.append(Finding("generated file", rel, 0, "remove generated cache/artifact from public export"))
            continue
        if rel.suffix.lower() == ".pdf":
            findings.extend(scan_pdf(path, root, patterns))
        elif should_scan(rel):
            findings.extend(scan_file(path, root, patterns))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrub a PDFRejuvenator public export for secrets and local-only content.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Public export root to scan.")
    parser.add_argument("--denylist", type=Path, help="Optional private newline-delimited terms file to scan for.")
    args = parser.parse_args()

    root = args.root.resolve()
    patterns = [*FORBIDDEN_PATTERNS, *load_extra_patterns(args.denylist)]
    findings = scan_root(root, patterns)
    for finding in findings:
        print(f"{finding.category}: {finding.path}:{finding.line_number}: {finding.line}")
    print(f"SCRUB SUMMARY: files_root={root} findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
