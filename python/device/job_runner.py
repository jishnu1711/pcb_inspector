from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from inspector.llm_planner.llm_client import LLMClient
from inspector.llm_planner.fault_interpreter import interpret_faults
from inspector.llm_planner.planner import plan_test_order
from inspector.model.component_classifier import ComponentClassifier
from inspector.model.electrical_model import build_electrical_model
from inspector.model.probe_selector import select_probes
from inspector.parser.kicad_pcb_parser import KiCadPCBParser
from inspector.parser.kicad_sch_parser import KiCadSchParser
from inspector.report.report_generator import build_report, write_report
from inspector.test_generator.generator import generate_test_pattern

from .config import JobInput
from .executor import DryRunExecutor
from .storage import sha256_file, write_json

APP_VERSION = "0.1.0"


class JobRunner:
    def run(self, job: JobInput) -> dict:
        job.output_dir.mkdir(parents=True, exist_ok=True)
        pcb_data = KiCadPCBParser(str(job.pcb_path)).parse()
        schematic_data = KiCadSchParser(str(job.schematic_path)).parse()
        llm_client = LLMClient.from_config(str(job.config_path))
        classifications = ComponentClassifier(llm_client).classify_all(schematic_data.components)
        nets, components = build_electrical_model(pcb_data, schematic_data, classifications)
        nets = select_probes(nets, config_path=str(job.config_path))
        pattern = generate_test_pattern(
            nets, components, str(job.pcb_path), str(job.schematic_path), config_path=str(job.config_path)
        )
        pattern = plan_test_order(pattern, llm_client)

        executor = DryRunExecutor(job.dry_run.faults)
        results = executor.execute_all(pattern.test_cases)
        report = build_report(pattern, results)
        report = interpret_faults(report, pattern, llm_client)

        plan_path = write_json(job.output_dir / "plan.json", pattern)
        trace_path = write_json(job.output_dir / "dry-run-trace.json", executor.trace)
        report_path = job.output_dir / "report.json"
        write_report(report, pattern, str(report_path), fmt="json")
        manifest = {
            "app_version": APP_VERSION,
            "input": job.to_dict(),
            "input_hashes": {
                "pcb": sha256_file(job.pcb_path),
                "schematic": sha256_file(job.schematic_path),
                "config": sha256_file(job.config_path),
            },
            "logical_plan": asdict(pattern),
            "dry_run_trace": executor.trace,
            "report_paths": {
                "plan": str(plan_path),
                "trace": str(trace_path),
                "report": str(report_path),
            },
        }
        manifest_path = write_json(job.output_dir / "manifest.json", manifest)
        return {"manifest": str(manifest_path), **manifest["report_paths"]}
