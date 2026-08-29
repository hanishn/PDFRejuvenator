from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class HttpErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"forced failure"}')

    def log_message(self, _format: str, *args: object) -> None:
        return


class TimeoutHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        threading.Event().wait(3.0)

    def log_message(self, _format: str, *args: object) -> None:
        return


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _run_failure_case(
    *,
    python_exe: Path,
    vector_index: Path,
    output_dir: Path,
    case_name: str,
    ollama_url: str,
    answer_timeout_seconds: str,
    subprocess_timeout_seconds: float,
) -> dict[str, Any]:
    answer_path = output_dir / f"{case_name}_answer_query.json"
    if answer_path.exists():
        answer_path.unlink()
    command = [
        str(python_exe),
        "-m",
        "pdfrejuvenator",
        "answer-query",
        str(vector_index),
        "What does the smoke test evidence say?",
        "--provider",
        "deterministic-test",
        "--limit",
        "1",
        "--answer-provider",
        "ollama",
        "--answer-model",
        "mock-model",
        "--answer-timeout-seconds",
        answer_timeout_seconds,
        "--ollama-url",
        ollama_url,
        "--output",
        str(answer_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=subprocess_timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "case": case_name,
            "passed": False,
            "detail": f"subprocess timeout after {subprocess_timeout_seconds} seconds: {exc}",
            "answer_exists": answer_path.exists(),
        }
    stdout_path = output_dir / f"{case_name}_stdout.txt"
    stderr_path = output_dir / f"{case_name}_stderr.txt"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    passed = (
        result.returncode == 1
        and "ollama answer request failed for model mock-model" in result.stderr
        and not answer_path.exists()
    )
    return {
        "case": case_name,
        "passed": passed,
        "returncode": result.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "answer_exists": answer_path.exists(),
        "stderr": result.stderr.strip(),
    }


def _run_hidden_evidence_generation_case(
    *,
    python_exe: Path,
    vector_index: Path,
    output_dir: Path,
) -> dict[str, Any]:
    case_name = "hidden_evidence_generation"
    answer_path = output_dir / f"{case_name}_answer_query.json"
    evidence_path = output_dir / f"{case_name}_answer_query_evidence.jsonl"
    for path in (answer_path, evidence_path):
        if path.exists():
            path.unlink()
    command = [
        str(python_exe),
        "-m",
        "pdfrejuvenator",
        "answer-query",
        str(vector_index),
        "What does the smoke test evidence say?",
        "--provider",
        "deterministic-test",
        "--limit",
        "1",
        "--answer-provider",
        "ollama",
        "--answer-model",
        "mock-model",
        "--hide-evidence-text",
        "--output",
        str(answer_path),
        "--evidence-output",
        str(evidence_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20.0, check=False)
    stdout_path = output_dir / f"{case_name}_stdout.txt"
    stderr_path = output_dir / f"{case_name}_stderr.txt"
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    passed = (
        result.returncode == 1
        and "generated answers require evidence text" in result.stderr
        and not answer_path.exists()
        and not evidence_path.exists()
    )
    return {
        "case": case_name,
        "passed": passed,
        "returncode": result.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "answer_exists": answer_path.exists(),
        "evidence_exists": evidence_path.exists(),
        "stderr": result.stderr.strip(),
    }


def run_checks(python_exe: Path, vector_index: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    http_server, http_url = _serve(HttpErrorHandler)
    try:
        checks.append(
            _run_failure_case(
                python_exe=python_exe,
                vector_index=vector_index,
                output_dir=output_dir,
                case_name="http_error",
                ollama_url=http_url,
                answer_timeout_seconds="1",
                subprocess_timeout_seconds=20.0,
            )
        )
    finally:
        http_server.shutdown()
        http_server.server_close()

    timeout_server, timeout_url = _serve(TimeoutHandler)
    try:
        checks.append(
            _run_failure_case(
                python_exe=python_exe,
                vector_index=vector_index,
                output_dir=output_dir,
                case_name="timeout",
                ollama_url=timeout_url,
                answer_timeout_seconds="0.2",
                subprocess_timeout_seconds=20.0,
            )
        )
    finally:
        timeout_server.shutdown()
        timeout_server.server_close()

    checks.append(
        _run_hidden_evidence_generation_case(
            python_exe=python_exe,
            vector_index=vector_index,
            output_dir=output_dir,
        )
    )

    failures = [check for check in checks if not check["passed"]]
    return {"checks": checks, "check_count": len(checks), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert answer-query fails closed for local answer-provider failures.")
    parser.add_argument("--python-exe", type=Path, default=Path(sys.executable))
    parser.add_argument("--vector-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    summary = run_checks(args.python_exe.resolve(), args.vector_index.resolve(), args.output_dir.resolve())
    report_path = args.report or args.output_dir / "answer_provider_failure_assertions.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ANSWER PROVIDER FAILURE ASSERTIONS: checks={summary['check_count']} failures={len(summary['failures'])}")
    for failure in summary["failures"]:
        print(f"FAIL: {failure['case']} - {failure}")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
