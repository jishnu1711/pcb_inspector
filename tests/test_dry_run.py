from __future__ import annotations

import json
from pathlib import Path

from device.app import run_local_job
from device.config import JobInput
from device.executor import DryRunExecutor
from inspector.model.types import ProbePoint, TestCase as ElectricalTestCase


FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = Path(__file__).parents[1] / "python" / "inspector" / "config.yaml"


def _job(tmp_path: Path, faults: dict | None = None) -> JobInput:
    return JobInput.from_dict(
        {
            "pcb_path": str(FIXTURES / "led.kicad_pcb"),
            "schematic_path": str(FIXTURES / "led.kicad_sch"),
            "output_dir": str(tmp_path / "output"),
            "config_path": str(CONFIG),
            "dry_run": {"faults": faults or {}},
        }
    )


def test_fixture_board_runs_from_plan_to_report(tmp_path):
    result = run_local_job(str(_write_job_manifest(tmp_path, _job(tmp_path))))

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert Path(result["plan"]).is_file()
    assert Path(result["trace"]).is_file()
    assert manifest["input_hashes"]["pcb"]
    assert len(manifest["logical_plan"]["test_cases"]) == report["summary"]["total_tests"]
    assert report["summary"]["errors"] == 0


def test_repeated_fixture_runs_keep_the_same_logical_tests(tmp_path):
    first = run_local_job(str(_write_job_manifest(tmp_path / "one", _job(tmp_path / "one"))))
    second = run_local_job(str(_write_job_manifest(tmp_path / "two", _job(tmp_path / "two"))))

    def logical_cases(result: dict) -> list[dict]:
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        return [
            {key: case[key] for key in ("id", "test_type", "net_a", "net_b", "component_ref", "expected")}
            for case in manifest["logical_plan"]["test_cases"]
        ]

    assert logical_cases(first) == logical_cases(second)


def test_fault_injection_and_llm_fallback_are_reported(tmp_path):
    baseline = run_local_job(str(_write_job_manifest(tmp_path / "baseline", _job(tmp_path / "baseline"))))
    baseline_manifest = json.loads(Path(baseline["manifest"]).read_text(encoding="utf-8"))
    fault_key = baseline_manifest["logical_plan"]["test_cases"][0]["net_a"]
    result = run_local_job(
        str(_write_job_manifest(tmp_path, _job(tmp_path, faults={fault_key: {"status": "fail", "value": 0}})))
    )
    report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert report["summary"]["failed"] > 0
    assert "failed" in report["fault_summary"]


def test_dry_run_value_is_deterministic():
    probe = ProbePoint("TP1_p1", "GND", 1, 1, "F.Cu", "test_pad", "TP1", "1", 1)
    test_case = ElectricalTestCase("cont_0001", "continuity", probe, probe, {"resistance_max_ohm": 10}, "GND", None, None, 1, None)
    first = DryRunExecutor().execute(test_case)
    second = DryRunExecutor().execute(test_case)
    assert first.measured_value == second.measured_value
    assert first.timestamp == "1970-01-01T00:00:00+00:00"


def _write_job_manifest(tmp_path: Path, job: JobInput) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job.to_dict()), encoding="utf-8")
    return path
