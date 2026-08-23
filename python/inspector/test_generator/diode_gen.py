"""
test_generator/diode_gen.py
----------------------------
Generates diode forward and reverse test cases.

Only runs for components where component_type ∈ {"diode", "led"}.
Requires pin_function "anode" and "cathode" from AI classifier.

Threshold priority:
  1. BOM / test_parameters already in Component (from classifier)
  2. Generic defaults from config.yaml (diode_vf / led_vf ranges)

If anode or cathode probe point cannot be found, the component is skipped.
"""

from __future__ import annotations

import logging
from typing import Optional

import yaml

from inspector.model.types import Net, Component, TestCase, ProbePoint

logger = logging.getLogger(__name__)

_counter = 0

def _next_id() -> str:
    global _counter
    _counter += 1
    return f"diode_{_counter:04d}"


def _best_probe(net: Net) -> Optional[ProbePoint]:
    return net.probe_points[0] if net.probe_points else None


def generate_diode_tests(
    nets: dict[str, Net],
    components: dict[str, Component],
    config_path: str = "config.yaml",
) -> list[TestCase]:
    """
    Returns list of TestCase with test_type in
    {"diode_forward", "diode_reverse"}.
    """
    global _counter
    _counter = 0

    # Load config defaults
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        thr = cfg.get("thresholds", {})
        default_diode_vf_min = float(thr.get("diode_vf_min_v", 0.3))
        default_diode_vf_max = float(thr.get("diode_vf_max_v", 0.9))
        default_led_vf_min   = float(thr.get("led_vf_min_v", 1.8))
        default_led_vf_max   = float(thr.get("led_vf_max_v", 3.5))
        default_reverse_min  = float(thr.get("isolation_min_ohm", 100_000))
    except Exception as exc:
        logger.warning("Could not read config — using built-in diode defaults: %s", exc)
        default_diode_vf_min = 0.3
        default_diode_vf_max = 0.9
        default_led_vf_min   = 1.8
        default_led_vf_max   = 3.5
        default_reverse_min  = 100_000

    test_cases: list[TestCase] = []

    for ref, comp in components.items():
        if comp.component_type not in ("diode", "led"):
            continue

        # Find anode and cathode pins
        anode_pin = next(
            (p for p in comp.pins if p.pin_function == "anode"), None
        )
        cathode_pin = next(
            (p for p in comp.pins if p.pin_function == "cathode"), None
        )

        if anode_pin is None or cathode_pin is None:
            logger.warning(
                "%s is %s but anode/cathode pin_function not set — skipping diode tests",
                ref, comp.component_type,
            )
            continue

        anode_net   = nets.get(anode_pin.net_name)
        cathode_net = nets.get(cathode_pin.net_name)

        if anode_net is None or cathode_net is None:
            logger.warning("%s: anode or cathode net not found in nets dict", ref)
            continue

        anode_probe   = _best_probe(anode_net)
        cathode_probe = _best_probe(cathode_net)

        if anode_probe is None or cathode_probe is None:
            logger.warning("%s: no probe points on anode or cathode net", ref)
            continue

        # Determine Vf thresholds
        params = comp.test_parameters
        if "vf_min_v" in params and "vf_max_v" in params:
            vf_min = float(params["vf_min_v"])
            vf_max = float(params["vf_max_v"])
        elif comp.component_type == "led":
            vf_min = default_led_vf_min
            vf_max = default_led_vf_max
        else:
            vf_min = default_diode_vf_min
            vf_max = default_diode_vf_max

        # Forward test: anode(+) → cathode(-)
        if "diode_forward" in comp.applicable_tests:
            fwd = TestCase(
                id=_next_id(),
                test_type="diode_forward",
                probe_a=anode_probe,
                probe_b=cathode_probe,
                expected={"vf_min_v": vf_min, "vf_max_v": vf_max},
                net_a=anode_pin.net_name,
                net_b=cathode_pin.net_name,
                component_ref=ref,
                priority=30,   # diode checks are high priority
                rationale=(
                    f"{ref} ({comp.value}) forward Vf check: "
                    f"expect {vf_min}–{vf_max} V"
                ),
            )
            test_cases.append(fwd)

        # Reverse test: cathode(+) → anode(-), expect high resistance
        if "diode_reverse" in comp.applicable_tests:
            rev = TestCase(
                id=_next_id(),
                test_type="diode_reverse",
                probe_a=cathode_probe,
                probe_b=anode_probe,
                expected={"resistance_min_ohm": default_reverse_min},
                net_a=cathode_pin.net_name,
                net_b=anode_pin.net_name,
                component_ref=ref,
                priority=35,
                rationale=(
                    f"{ref} ({comp.value}) reverse blocking check: "
                    f"expect >{ default_reverse_min/1000:.0f} kΩ"
                ),
            )
            test_cases.append(rev)

    logger.info("Diode: generated %d test cases", len(test_cases))
    return test_cases
