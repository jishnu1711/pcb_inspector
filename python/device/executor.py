from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict
import hashlib
import json

from inspector.model.types import TestCase, TestResult


class Executor(ABC):
    @abstractmethod
    def execute(self, test_case: TestCase) -> TestResult:
        """Execute one logical test without raising hardware errors."""

    def execute_all(self, test_cases: list[TestCase]) -> list[TestResult]:
        return [self.execute(test_case) for test_case in test_cases]


class DryRunExecutor(Executor):
    """Records logical operations and produces stable in-range mock values."""

    def __init__(self, faults: dict[str, dict] | None = None):
        self._faults = faults or {}
        self.trace: list[dict] = []

    def execute(self, test_case: TestCase) -> TestResult:
        fault = self._fault_for(test_case)
        if fault:
            status = str(fault.get("status", "fail"))
            value = fault.get("value")
            unit = self._unit_for(test_case)
        else:
            value, unit = self._measurement_for(test_case)
            status = "pass"

        operation = {
            "test_case_id": test_case.id,
            "test_type": test_case.test_type,
            "probe_a": asdict(test_case.probe_a),
            "probe_b": asdict(test_case.probe_b),
            "expected": test_case.expected,
            "status": status,
            "measured_value": value,
            "unit": unit,
            "fault_injected": bool(fault),
        }
        self.trace.append(operation)
        return TestResult(
            test_case_id=test_case.id,
            status=status,
            measured_value=value,
            unit=unit,
            timestamp="1970-01-01T00:00:00+00:00",
            raw_response=json.dumps({"dry_run": True, **operation}, sort_keys=True),
        )

    def _fault_for(self, test_case: TestCase) -> dict | None:
        return (
            self._faults.get(test_case.net_a)
            or self._faults.get(test_case.net_b or "")
            or self._faults.get(test_case.component_ref or "")
        )

    @staticmethod
    def _unit_for(test_case: TestCase) -> str:
        return "V" if test_case.test_type == "diode_forward" else "ohm"

    @staticmethod
    def _fraction(test_case: TestCase) -> float:
        digest = hashlib.sha256(test_case.id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / (2**64 - 1)

    def _measurement_for(self, test_case: TestCase) -> tuple[float, str]:
        fraction = self._fraction(test_case)
        expected = test_case.expected
        if test_case.test_type == "continuity":
            return round(0.5 + fraction * 2.5, 2), "ohm"
        if test_case.test_type in ("isolation", "diode_reverse"):
            minimum = float(expected.get("resistance_min_ohm", 1_000_000))
            return round(minimum * (2 + fraction * 8), 2), "ohm"
        if test_case.test_type == "diode_forward":
            low = float(expected.get("vf_min_v", 0.3))
            high = float(expected.get("vf_max_v", 0.9))
            return round(low + (high - low) * fraction, 3), "V"
        return 0.0, "unknown"
