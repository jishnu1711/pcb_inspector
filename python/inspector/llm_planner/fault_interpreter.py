"""
llm_planner/fault_interpreter.py
----------------------------------
After test execution, sends failed/errored results to the LLM and gets back
a plain-English fault narrative.

Falls back to a deterministic summary if the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging

from inspector.model.types import FaultReport, TestResult, TestPattern
from inspector.llm_planner.llm_client import LLMClient
from inspector.llm_planner.prompts import (
    FAULT_INTERPRETER_SYSTEM,
    FAULT_INTERPRETER_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


def _deterministic_summary(report: FaultReport, pattern: TestPattern) -> str:
    """Simple fallback summary without LLM."""
    if report.failed == 0 and report.errors == 0:
        return "All tests passed. No faults detected."

    lines = [
        f"{report.failed} test(s) failed, {report.errors} error(s) encountered "
        f"out of {report.total_tests} total."
    ]

    # Group by test_type
    id_to_tc = {tc.id: tc for tc in pattern.test_cases}
    by_type: dict[str, list[TestResult]] = {}
    for r in report.results:
        if r.status in ("fail", "error"):
            tc = id_to_tc.get(r.test_case_id)
            ttype = tc.test_type if tc else "unknown"
            by_type.setdefault(ttype, []).append(r)

    for ttype, results in by_type.items():
        lines.append(f"  {ttype}: {len(results)} failure(s)")

    lines.append("Review the detailed results for probe coordinates and measured values.")
    return " ".join(lines)


def interpret_faults(
    report: FaultReport,
    pattern: TestPattern,
    llm_client: LLMClient,
) -> FaultReport:
    """
    Populate report.fault_summary using LLM (or deterministic fallback).
    Mutates and returns the same FaultReport.
    """
    if report.failed == 0 and report.errors == 0:
        report.fault_summary = "All tests passed. No faults detected."
        return report

    # Build id → TestCase lookup for context
    id_to_tc = {tc.id: tc for tc in pattern.test_cases}

    failed_results = []
    for r in report.results:
        if r.status in ("fail", "error"):
            tc = id_to_tc.get(r.test_case_id)
            entry = {
                "test_case_id": r.test_case_id,
                "status": r.status,
                "measured_value": r.measured_value,
                "unit": r.unit,
                "timestamp": r.timestamp,
            }
            if tc:
                entry.update({
                    "test_type": tc.test_type,
                    "net_a": tc.net_a,
                    "net_b": tc.net_b,
                    "component_ref": tc.component_ref,
                    "expected": tc.expected,
                    "rationale": tc.rationale,
                })
            failed_results.append(entry)

    user_prompt = FAULT_INTERPRETER_USER_TEMPLATE.format(
        board_id=report.board_id,
        passed=report.passed,
        failed=report.failed,
        errors=report.errors,
        failed_results_json=json.dumps(failed_results, indent=2),
    )

    raw = llm_client.complete(FAULT_INTERPRETER_SYSTEM, user_prompt)

    if raw and raw.strip():
        report.fault_summary = raw.strip()
        logger.info("Fault interpreter: LLM summary generated (%d chars)", len(raw))
    else:
        report.fault_summary = _deterministic_summary(report, pattern)
        logger.info("Fault interpreter: using deterministic fallback summary")

    return report
