from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfrejuvenator.corpus_search import (  # noqa: E402
    TABLE_RECORD_SEARCH_SCHEMA_VERSION,
    build_index_from_table_records,
)
from pdfrejuvenator.private_workspace import init_private_workspace  # noqa: E402
from pdfrejuvenator.table_records import (  # noqa: E402
    TABLE_RECORD_SCHEMA_VERSION,
    build_table_record,
    validate_table_record_payload,
    write_table_records,
)


def check(name: str, passed: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, passed, detail


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_checks() -> list[tuple[str, bool, str]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        private_workspace = temp_root / "private_workspace"
        init_private_workspace(private_workspace, corpus_id="synthetic-private-corpus")
        record = build_table_record(
            corpus_id="synthetic-corpus",
            book_id="synthetic-book",
            source_sha256="d" * 64,
            page_number=7,
            table_id="table-001",
            caption="Synthetic table fixture",
            cells=[["Name", "Value"], ["Alpha", 10], ["Beta"]],
            confidence=0.91,
        )
        output = private_workspace / "derived" / "tables" / "table_records.json"
        record_count = write_table_records([record], output, private_workspace_root=private_workspace)
        payload = json.loads(output.read_text(encoding="utf-8"))
        validation_issues = validate_table_record_payload(output)
        index_path = private_workspace / "indexes" / "table_index.jsonl"
        index_count = build_index_from_table_records(output, index_path)
        index_records = read_jsonl(index_path)
        outside_rejected = False
        try:
            write_table_records([record], temp_root / "outside_table_records.json", private_workspace_root=private_workspace)
        except ValueError:
            outside_rejected = True
        output_exists = output.exists()

    return [
        check("table records written", output_exists),
        check("table records schema version", payload.get("schema_version") == TABLE_RECORD_SCHEMA_VERSION),
        check("table records count", record_count == 1),
        check("table records validation", not validation_issues, "; ".join(validation_issues)),
        check("table row normalization", payload["records"][0]["cells"][-1] == ["Beta", ""]),
        check("table private output enforcement", outside_rejected),
        check("table search index written", index_count == len(index_records) == 1),
        check("table search source schema", index_records[0].get("source_schema_version") == TABLE_RECORD_SEARCH_SCHEMA_VERSION),
        check("table search record type", index_records[0].get("record_type") == "private_table"),
        check("table search metadata", index_records[0].get("metadata", {}).get("row_count") == 3),
    ]


def main() -> int:
    checks = run_checks()
    failures = [(name, detail) for name, passed, detail in checks if not passed]
    for name, passed, detail in checks:
        if not passed:
            suffix = f" - {detail}" if detail else ""
            print(f"FAIL: {name}{suffix}")
    print(f"TABLE RECORDS SUMMARY: checks={len(checks)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
