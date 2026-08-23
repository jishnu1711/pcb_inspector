"""
report/formatters/json_formatter.py
-------------------------------------
Serialises FaultReport + TestPattern to a JSON string.
TestCase probe coordinates are included for machine consumption.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from inspector.model.types import FaultReport, TestPattern


def _asdict(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _asdict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_asdict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    return obj


def format_json(report: FaultReport, pattern: TestPattern) -> str:
    """Return a pretty-printed JSON string."""
    payload = {
        "board_id": report.board_id,
        "executed_at": report.executed_at,
        "summary": {
            "total_tests": report.total_tests,
            "passed": report.passed,
            "failed": report.failed,
            "errors": report.errors,
        },
        "fault_summary": report.fault_summary,
        "test_cases": _asdict(pattern.test_cases),
        "results": _asdict(report.results),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
