"""Pytest plugin to write structured test results to tests/test_output.json."""

import os
import tempfile

# Set test-time defaults before any app code is imported
os.environ.setdefault("CORS_ORIGINS", "https://bins.lovesguinness.com")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("RUN_REFRESH_JOB", "0")
os.environ.setdefault(
    "DATA_DIR", tempfile.mkdtemp(prefix="bins-test-data-")
)

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "test_output.json"

_results: list[dict] = []


def pytest_runtest_logreport(report):
    if report.when != "call":
        return

    node_id = report.nodeid

    # Extract council and label from parametrized id
    # test_integration.py uses "council|label", test_ci.py uses "council" alone
    council = ""
    label = ""
    if "[" in node_id:
        param_str = node_id.split("[", 1)[1].rstrip("]")
        if "|" in param_str:
            council, label = param_str.split("|", 1)
        else:
            council = param_str

    entry = {
        "node_id": node_id,
        "council": council,
        "label": label,
        "status": report.outcome,  # "passed", "failed", "skipped"
        "duration": round(report.duration, 2),
    }

    if report.failed:
        msg = str(report.longrepr)
        entry["full_message"] = msg

        # Extract structured fields from the failure message
        for line in msg.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith(("UPRN/address_id:", "UPRN:")):
                entry["uprn"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("Query params:"):
                entry["query_params_raw"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("Status code:"):
                entry["status_code"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("Error detail:"):
                entry["error_detail"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith(("Exception:", "Error message:")):
                entry["exception"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("Error type:"):
                entry["error_type"] = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("Response keys:"):
                entry["response_keys"] = line_stripped.split(":", 1)[1].strip()

        # Categorisation key for grouping
        if "error_detail" in entry:
            entry["failure_category"] = entry["error_detail"]
        elif "exception" in entry:
            entry["failure_category"] = entry["exception"]
        elif "status_code" in entry:
            entry["failure_category"] = f"HTTP {entry['status_code']}"
        else:
            # Fallback: last non-empty line
            entry["failure_category"] = msg.splitlines()[-1].strip()[:200]

        # Extract error_summary from the first diagnostic line
        for line in msg.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith(
                ("Expected ", "Response ", "Request ", "FAILED:")
            ):
                entry["error_summary"] = line_stripped[:200]
                break

    _results.append(entry)


def pytest_sessionfinish(session, exitstatus):
    results = _results
    passed = [r for r in results if r["status"] == "passed"]
    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped"]

    summary = {
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
    }

    # Group failures by category for easy scanning
    failure_categories: dict[str, list[dict]] = {}
    for r in failed:
        key = r.get("failure_category", "unknown")
        failure_categories.setdefault(key, []).append(
            {
                "council": r["council"],
                "label": r["label"],
                "uprn": r.get("uprn", ""),
                "status_code": r.get("status_code", ""),
                "error_summary": r.get("error_summary", ""),
                "duration": r["duration"],
            }
        )

    summary["failure_categories"] = {
        k: {"count": len(v), "councils": v}
        for k, v in sorted(failure_categories.items(), key=lambda x: -len(x[1]))
    }

    # Per-council results for quick lookup
    summary["results"] = results

    OUTPUT_PATH.write_text(json.dumps(summary, indent=2) + "\n")
