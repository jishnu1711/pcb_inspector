"""
test_generator/continuity_gen.py
---------------------------------
Generates continuity (same-net, low-resistance) test cases.

Strategy: spanning-tree chain — A↔B, B↔C, C↔D (N-1 tests per net).
ProbePoints are already sorted best-first by probe_selector.

Skips nets with fewer than 2 probe points (logged as untestable).
"""

from __future__ import annotations

import logging
from typing import Optional

import yaml

from inspector.model.types import Net, TestCase, ProbePoint

logger = logging.getLogger(__name__)

_counter = 0

def _next_id() -> str:
    global _counter
    _counter += 1
    return f"cont_{_counter:04d}"


def generate_continuity_tests(
    nets: dict[str, Net],
    config_path: str = "config.yaml",
    resistance_max_ohm: Optional[float] = None,
) -> list[TestCase]:
    """
    Parameters
    ----------
    nets                 : from probe_selector (probe_points already sorted+pruned)
    config_path          : path to config.yaml
    resistance_max_ohm   : override; if None, read from config

    Returns list of TestCase with test_type="continuity".
    """
    global _counter
    _counter = 0

    if resistance_max_ohm is None:
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            resistance_max_ohm = float(
                cfg.get("thresholds", {}).get("continuity_max_ohm", 10.0)
            )
        except Exception as exc:
            logger.warning("Could not read config — using 10 Ω threshold: %s", exc)
            resistance_max_ohm = 10.0

    test_cases: list[TestCase] = []
    skipped_single: list[str] = []

    for net_name, net in nets.items():
        pts = net.probe_points
        if len(pts) < 2:
            skipped_single.append(net_name)
            continue

        # Chain: pts[0]↔pts[1], pts[1]↔pts[2], …
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            tc = TestCase(
                id=_next_id(),
                test_type="continuity",
                probe_a=a,
                probe_b=b,
                expected={"resistance_max_ohm": resistance_max_ohm},
                net_a=net_name,
                net_b=None,
                component_ref=None,
                priority=50,        # default; LLM planner will re-order
                rationale=f"Continuity along net {net_name}: {a.id} → {b.id}",
            )
            test_cases.append(tc)

    if skipped_single:
        logger.info(
            "Continuity: skipped %d nets with <2 probe points: %s",
            len(skipped_single), skipped_single,
        )

    logger.info("Continuity: generated %d test cases", len(test_cases))
    return test_cases
