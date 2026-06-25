from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_records(index_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def score_record(record: dict[str, Any], terms: list[str]) -> int:
    metadata = record.get("metadata", {})
    searchable_metadata = []
    if isinstance(metadata, dict):
        for key in ("classification", "review_role", "layout_class"):
            if metadata.get(key):
                searchable_metadata.append(str(metadata[key]))
    haystack = " ".join(
        [
            str(record.get("text", "")),
            str(record.get("record_type", "")),
            " ".join(searchable_metadata),
        ]
    ).lower()
    score = 0
    for term in terms:
        score += haystack.count(term)
    if record.get("record_type") == "page" and score:
        score += 1
    return score


def snippet(text: str, terms: list[str], limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    lowered = compact.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, min(positions) - 45) if positions else 0
    end = min(len(compact), start + limit)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def default_index_path(output_dir: Path) -> Path:
    return output_dir / "_search" / "search_index.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Search a local PDFRejuvenator index.")
    parser.add_argument("query", help="Search text.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Consolidated PDFRejuvenator output directory.")
    parser.add_argument("--index", type=Path, default=None, help="Explicit search_index.jsonl path.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    index_path = (args.index or default_index_path(args.output_dir.resolve())).resolve() if args.output_dir else args.index
    if index_path is None:
        raise SystemExit("provide --output-dir or --index")
    if not index_path.exists():
        raise SystemExit(f"missing search index: {index_path}")

    terms = [term.lower() for term in args.query.split() if term.strip()]
    if not terms:
        raise SystemExit("empty query")

    hits = []
    for record in load_records(index_path):
        score = score_record(record, terms)
        if score:
            hits.append((score, record))
    hits.sort(key=lambda item: (-item[0], item[1].get("page", 0), item[1].get("record_type", "")))

    for score, record in hits[: args.limit]:
        print(
            f"page={record.get('page')} type={record.get('record_type')} score={score} "
            f"artifact={record.get('artifact_path', '')}"
        )
        print(f"  {snippet(str(record.get('text', '')), terms)}")
    print(f"RESULTS={min(len(hits), args.limit)} TOTAL_MATCHES={len(hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
