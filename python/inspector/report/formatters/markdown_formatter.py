"""
report/formatters/markdown_formatter.py
----------------------------------------
Produces a human-readable Markdown inspection report.
"""

from __future__ import annotations

from inspector.model.types import FaultReport, TestPattern, TestResult


_STATUS_EMOJI = {"pass": "✅", "fail": "❌", "error": "⚠️"}


def format_markdown(report: FaultReport, pattern: TestPattern) -> str:
    id_to_tc = {tc.id: tc for tc in pattern.test_cases}
    lines: list[str] = []

    # Header
    lines += [
        f"# PCB Inspection Report",
        f"",
        f"**Board ID:** `{report.board_id}`  ",
        f"**Executed:** {report.executed_at}  ",
        f"**PCB file:** `{pattern.kicad_pcb_file}`  ",
        f"**Schematic:** `{pattern.kicad_sch_file}`  ",
        f"",
    ]

    # Summary table
    pct = (report.passed / report.total_tests * 100) if report.total_tests else 0
    lines += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total tests | {report.total_tests} |",
        f"| Passed | {report.passed} ({pct:.1f}%) |",
        f"| Failed | {report.failed} |",
        f"| Errors | {report.errors} |",
        "",
    ]

    # Fault narrative
    if report.fault_summary:
        lines += [
            "## Fault Analysis",
            "",
            report.fault_summary,
            "",
        ]

    # Failures detail
    failures = [r for r in report.results if r.status in ("fail", "error")]
    if failures:
        lines += [
            "## Failures",
            "",
            "| Test ID | Type | Net A | Net B | Component | Expected | Measured | Status |",
            "|---------|------|-------|-------|-----------|----------|----------|--------|",
        ]
        for r in failures:
            tc = id_to_tc.get(r.test_case_id)
            if tc:
                exp_str = ", ".join(f"{k}={v}" for k, v in tc.expected.items())
                meas = f"{r.measured_value} {r.unit}" if r.measured_value is not None else "—"
                lines.append(
                    f"| `{r.test_case_id}` | {tc.test_type} | {tc.net_a} "
                    f"| {tc.net_b or '—'} | {tc.component_ref or '—'} "
                    f"| {exp_str} | {meas} | {_STATUS_EMOJI[r.status]} {r.status} |"
                )
        lines.append("")

    # Full results table (collapsed for long runs)
    lines += [
        "## All Results",
        "",
        "<details><summary>Click to expand</summary>",
        "",
        "| Test ID | Type | Status | Measured |",
        "|---------|------|--------|----------|",
    ]
    for r in report.results:
        tc = id_to_tc.get(r.test_case_id)
        ttype = tc.test_type if tc else "?"
        meas = f"{r.measured_value} {r.unit}" if r.measured_value is not None else "—"
        lines.append(
            f"| `{r.test_case_id}` | {ttype} | {_STATUS_EMOJI.get(r.status, '')} {r.status} | {meas} |"
        )
    lines += ["", "</details>", ""]

    return "\n".join(lines)
