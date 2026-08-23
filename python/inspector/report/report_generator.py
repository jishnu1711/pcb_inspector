"""
report/report_generator.py
---------------------------
Assembles a FaultReport from a TestPattern and a list of TestResults,
then delegates formatting to json_formatter or markdown_formatter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from inspector.model.types import TestPattern, TestResult, FaultReport
from inspector.report.formatters.json_formatter import format_json
from inspector.report.formatters.markdown_formatter import format_markdown

logger = logging.getLogger(__name__)


def build_report(
    pattern: TestPattern,
    results: list[TestResult],
) -> FaultReport:
    """
    Aggregate results into a FaultReport (fault_summary left as None —
    fault_interpreter fills it in separately).
    """
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    errors  = sum(1 for r in results if r.status == "error")

    report = FaultReport(
        board_id=pattern.board_id,
        executed_at=datetime.now(timezone.utc).isoformat(),
        total_tests=len(results),
        passed=passed,
        failed=failed,
        errors=errors,
        results=results,
        fault_summary=None,
    )

    logger.info(
        "Report: total=%d  pass=%d  fail=%d  error=%d",
        report.total_tests, passed, failed, errors,
    )
    return report


def write_report(
    report: FaultReport,
    pattern: TestPattern,
    output_path: str,
    fmt: str = "json",
) -> None:
    """
    Write report to disk.

    Parameters
    ----------
    output_path : file path (extension is appended if missing)
    fmt         : "json" | "markdown"
    """
    if fmt == "json":
        if not output_path.endswith(".json"):
            output_path += ".json"
        content = format_json(report, pattern)
    elif fmt in ("markdown", "md"):
        if not output_path.endswith((".md", ".markdown")):
            output_path += ".md"
        content = format_markdown(report, pattern)
    else:
        raise ValueError(f"Unknown report format: {fmt!r}")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    logger.info("Report written to %s (%s format)", output_path, fmt)
