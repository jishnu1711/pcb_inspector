"""
test_generator/generator.py
----------------------------
Orchestrator: calls continuity_gen, isolation_gen, and diode_gen,
then assembles a TestPattern ready for the LLM planner.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from inspector.model.types import Net, Component, TestPattern
from inspector.test_generator.continuity_gen import generate_continuity_tests
from inspector.test_generator.isolation_gen import generate_isolation_tests
from inspector.test_generator.diode_gen import generate_diode_tests

logger = logging.getLogger(__name__)


def generate_test_pattern(
    nets: dict[str, Net],
    components: dict[str, Component],
    kicad_pcb_file: str,
    kicad_sch_file: str,
    config_path: str = "config.yaml",
) -> TestPattern:
    """
    Run all test generators and return an unordered TestPattern.
    Priority values are defaults — LLM planner will re-sort them.

    Parameters
    ----------
    nets           : from probe_selector.select_probes
    components     : from electrical_model.build_electrical_model
    kicad_pcb_file : original PCB file path (for traceability)
    kicad_sch_file : original schematic file path
    config_path    : path to config.yaml

    Returns
    -------
    TestPattern with all generated TestCases.
    """
    logger.info("=== Test generation started ===")

    continuity_cases = generate_continuity_tests(nets, config_path=config_path)
    isolation_cases  = generate_isolation_tests(nets, components, config_path=config_path)
    diode_cases      = generate_diode_tests(nets, components, config_path=config_path)

    all_cases = continuity_cases + isolation_cases + diode_cases

    logger.info(
        "Total test cases: %d  (continuity=%d  isolation=%d  diode=%d)",
        len(all_cases), len(continuity_cases), len(isolation_cases), len(diode_cases),
    )

    pattern = TestPattern(
        board_id=str(uuid.uuid4()),
        generated_at=datetime.now(timezone.utc).isoformat(),
        kicad_pcb_file=kicad_pcb_file,
        kicad_sch_file=kicad_sch_file,
        test_cases=all_cases,
    )

    return pattern
