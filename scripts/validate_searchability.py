from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


INTERNAL_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\(?:Projects|Users)\\|/mnt/[a-z]/|DocumentExpertProcessLibrary\\outputs\\pdf_runs)"
)
USER_FACING_FILES = [
    "dashboard.html",
    "manifest.csv",
    "README.md",
    "validation_report.csv",
    "validation_report.json",
]
REQUIRED_RECORD_FIELDS = {
    "schema_version",
    "record_id",
    "book_id",
    "source_pdf_sha256",
    "page",
    "page_id",
    "record_type",
    "text",
    "artifact_path",
    "metadata",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise SystemExit(f"invalid JSONL record at {path}:{line_number}: expected object")
            records.append(record)
    return records


def record_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        record_type = str(record.get("record_type", ""))
        counts[record_type] = counts.get(record_type, 0) + 1
    return counts


def score_record(record: dict[str, Any], terms: list[str]) -> int:
    metadata = record.get("metadata", {})
    searchable_metadata: list[str] = []
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
    return sum(haystack.count(term) for term in terms)


def query_hits(records: list[dict[str, Any]], query: str, *, record_type: str | None = None) -> list[dict[str, Any]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    hits = []
    for record in records:
        if record_type is not None and record.get("record_type") != record_type:
            continue
        score = score_record(record, terms)
        if score:
            hits.append(
                {
                    "score": score,
                    "page": record.get("page"),
                    "record_type": record.get("record_type"),
                    "record_id": record.get("record_id"),
                }
            )
    hits.sort(key=lambda item: (-int(item["score"]), int(item.get("page") or 0), str(item.get("record_type") or "")))
    return hits


def parse_min_record_type(values: list[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--min-record-type must use record_type=count: {value}")
        record_type, count_text = value.split("=", 1)
        parsed[record_type] = int(count_text)
    return parsed


def parse_query_record_type(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"--query-record-type must use record_type=query: {value}")
    record_type, query = value.split("=", 1)
    record_type = record_type.strip()
    query = query.strip()
    if not record_type or not query:
        raise SystemExit(f"--query-record-type must use record_type=query: {value}")
    return record_type, query


def find_path_leaks(output_dir: Path) -> list[dict[str, Any]]:
    leaks: list[dict[str, Any]] = []
    for relative in USER_FACING_FILES:
        path = output_dir / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if INTERNAL_PATH_RE.search(line):
                leaks.append({"file": str(path), "line": line_number})
    return leaks


def validate(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    errors: list[str] = []
    output_dir = args.output_dir.resolve()
    search_dir = output_dir / "_search"
    index_path = search_dir / "search_index.jsonl"
    manifest_path = search_dir / "search_manifest.json"

    if not index_path.exists():
        errors.append(f"missing search index: {index_path}")
        records: list[dict[str, Any]] = []
    else:
        records = load_jsonl(index_path)

    manifest: dict[str, Any] = {}
    if not manifest_path.exists():
        errors.append(f"missing search manifest: {manifest_path}")
    else:
        payload = read_json(manifest_path)
        if not isinstance(payload, dict):
            errors.append(f"search manifest is not an object: {manifest_path}")
        else:
            manifest = payload

    counts = record_counts(records)
    if manifest:
        if manifest.get("status") != "PASS":
            errors.append(f"search manifest status is not PASS: {manifest.get('status')}")
        if int(manifest.get("record_count", -1)) != len(records):
            errors.append(f"search manifest record_count mismatch: manifest={manifest.get('record_count')} index={len(records)}")
        manifest_counts = manifest.get("record_counts", {})
        if isinstance(manifest_counts, dict):
            for record_type, count in counts.items():
                if int(manifest_counts.get(record_type, -1)) != count:
                    errors.append(f"search manifest count mismatch for {record_type}: manifest={manifest_counts.get(record_type)} index={count}")

    for index, record in enumerate(records, start=1):
        missing = REQUIRED_RECORD_FIELDS - set(record)
        if missing:
            errors.append(f"record {index} missing fields: {', '.join(sorted(missing))}")
        if record.get("schema_version") != "pdfrejuvenator.search.v0.3":
            errors.append(f"record {index} has unexpected schema_version: {record.get('schema_version')}")
        if not isinstance(record.get("metadata"), dict):
            errors.append(f"record {index} metadata is not an object")

    for record_type in args.require_record_type:
        if counts.get(record_type, 0) < 1:
            errors.append(f"required record type absent: {record_type}")

    for record_type, minimum in parse_min_record_type(args.min_record_type).items():
        if counts.get(record_type, 0) < minimum:
            errors.append(f"record type {record_type} count {counts.get(record_type, 0)} is below required minimum {minimum}")

    if args.require_nonempty_page_text:
        empty_pages = [
            record.get("page")
            for record in records
            if record.get("record_type") == "page" and not str(record.get("text", "")).strip()
        ]
        if empty_pages:
            errors.append(f"page records with empty text: {', '.join(str(page) for page in empty_pages)}")

    if args.require_nonempty_table_text:
        empty_tables = [
            record.get("record_id")
            for record in records
            if record.get("record_type") == "table" and not str(record.get("text", "")).strip()
        ]
        if empty_tables:
            errors.append(f"table records with empty text: {', '.join(str(record_id) for record_id in empty_tables)}")

    query_results: dict[str, list[dict[str, Any]]] = {}
    for query in args.query:
        hits = query_hits(records, query)
        query_results[query] = hits[:10]
        if not hits:
            errors.append(f"query produced no hits: {query}")

    typed_query_results: dict[str, list[dict[str, Any]]] = {}
    for value in args.query_record_type:
        record_type, query = parse_query_record_type(value)
        result_key = f"{record_type}={query}"
        hits = query_hits(records, query, record_type=record_type)
        typed_query_results[result_key] = hits[:10]
        if not hits:
            errors.append(f"query produced no {record_type} hits: {query}")

    leaks = find_path_leaks(output_dir) if args.check_user_facing_paths else []
    if leaks:
        errors.append(f"user-facing internal path leaks: {len(leaks)}")

    report = {
        "status": "PASS" if not errors else "FAIL",
        "output_dir": str(output_dir),
        "search_index": str(index_path),
        "search_manifest": str(manifest_path),
        "record_count": len(records),
        "record_counts": counts,
        "queries": query_results,
        "typed_queries": typed_query_results,
        "path_leaks": leaks,
        "errors": errors,
    }
    return (0 if not errors else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PDFRejuvenator local searchability artifacts.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Consolidated output directory containing _search.")
    parser.add_argument("--require-record-type", action="append", default=[], help="Record type that must be present at least once.")
    parser.add_argument("--min-record-type", action="append", default=[], help="Minimum record count, formatted as record_type=count.")
    parser.add_argument("--require-nonempty-page-text", action="store_true", help="Fail if any page record has empty text.")
    parser.add_argument("--require-nonempty-table-text", action="store_true", help="Fail if any table record has empty text.")
    parser.add_argument("--query", action="append", default=[], help="Query that must produce at least one hit.")
    parser.add_argument("--query-record-type", action="append", default=[], help="Typed query that must hit a specific record type, formatted as record_type=query.")
    parser.add_argument("--check-user-facing-paths", action="store_true", help="Scan root user-facing output files for internal absolute path leaks.")
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON report path.")
    args = parser.parse_args()

    code, report = validate(args)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"SEARCHABILITY_STATUS={report['status']}")
    print(f"SEARCH_RECORDS={report['record_count']}")
    print("SEARCH_RECORD_COUNTS=" + json.dumps(report["record_counts"], sort_keys=True))
    if report["errors"]:
        print("SEARCHABILITY_ERRORS=" + json.dumps(report["errors"], ensure_ascii=False))
    if args.report:
        print(f"SEARCHABILITY_REPORT={args.report}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
