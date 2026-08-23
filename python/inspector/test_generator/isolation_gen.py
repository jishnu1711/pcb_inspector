"""
test_generator/isolation_gen.py
--------------------------------
Generates isolation (cross-net, high-resistance) test cases.

Three categories:
  1. Adjacent-pin pairs — for each component, pairs of pins within 2× pad pitch
  2. Power-rail pairs — GND vs every power net (VCC/VDD/VBAT/V3V3/V5V/PWR)
  3. Connector adjacent-pin pairs — J*/P*/CN* references, all adjacent pad pairs

All pairs are cross-net (probe_a and probe_b are on DIFFERENT nets).
"""

from __future__ import annotations

import itertools
import logging
import math
import re
from typing import Optional

import yaml

from inspector.model.types import Net, Component, TestCase, ProbePoint

logger = logging.getLogger(__name__)

_counter = 0

def _next_id() -> str:
    global _counter
    _counter += 1
    return f"iso_{_counter:04d}"


# Nets whose name suggests a power rail
_POWER_PATTERN = re.compile(
    r"(VCC|VDD|VBAT|V3V3|V5V|PWR|3V3|5V|VBUS|VIN|VOUT)", re.IGNORECASE
)
_GND_PATTERN = re.compile(r"(GND|GROUND|VSS|AGND|DGND)", re.IGNORECASE)

# Connector reference prefixes
_CONNECTOR_PREFIX = re.compile(r"^(J|P|CN|X|CON)\d", re.IGNORECASE)


def _distance(a: ProbePoint, b: ProbePoint) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def _best_probe(net: Net) -> Optional[ProbePoint]:
    """Return the best (tier 1 or lowest tier) probe point for a net."""
    if not net.probe_points:
        return None
    return net.probe_points[0]   # already sorted best-first by probe_selector


def _make_iso_tc(
    a: ProbePoint,
    b: ProbePoint,
    resistance_min_ohm: float,
    rationale: str,
    component_ref: Optional[str] = None,
) -> TestCase:
    return TestCase(
        id=_next_id(),
        test_type="isolation",
        probe_a=a,
        probe_b=b,
        expected={"resistance_min_ohm": resistance_min_ohm},
        net_a=a.net_name,
        net_b=b.net_name,
        component_ref=component_ref,
        priority=60,
        rationale=rationale,
    )


def generate_isolation_tests(
    nets: dict[str, Net],
    components: dict[str, Component],
    config_path: str = "config.yaml",
    resistance_min_ohm: Optional[float] = None,
    pad_pitch_factor: float = 2.0,
) -> list[TestCase]:
    """
    Parameters
    ----------
    nets                : from probe_selector
    components          : from electrical_model
    config_path         : path to config.yaml
    resistance_min_ohm  : override; if None, read from config
    pad_pitch_factor    : multiplier on component's own pad spacing for adjacency

    Returns list of TestCase with test_type="isolation".
    """
    global _counter
    _counter = 0

    if resistance_min_ohm is None:
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            resistance_min_ohm = float(
                cfg.get("thresholds", {}).get("isolation_min_ohm", 1_000_000)
            )
        except Exception as exc:
            logger.warning("Could not read config — using 1 MΩ threshold: %s", exc)
            resistance_min_ohm = 1_000_000

    # Build net_name → best ProbePoint lookup
    net_best: dict[str, ProbePoint] = {}
    for net_name, net in nets.items():
        bp = _best_probe(net)
        if bp is not None:
            net_best[net_name] = bp

    test_cases: list[TestCase] = []
    seen_pairs: set[frozenset] = set()   # avoid duplicate cross-net pairs

    def _add_if_new(a: ProbePoint, b: ProbePoint, rationale: str,
                    component_ref: Optional[str] = None) -> None:
        if a.net_name == b.net_name:
            return   # same net — not an isolation test
        pair_key = frozenset([a.id, b.id])
        if pair_key in seen_pairs:
            return
        seen_pairs.add(pair_key)
        test_cases.append(_make_iso_tc(a, b, resistance_min_ohm, rationale, component_ref))

    # ------------------------------------------------------------------ #
    # 1. Adjacent pin pairs on each component                             #
    # ------------------------------------------------------------------ #
    for ref, comp in components.items():
        pins_with_probes = [
            pin for pin in comp.pins
            if pin.net_name in net_best
        ]
        if len(pins_with_probes) < 2:
            continue

        # Compute the component's characteristic pitch (median spacing of all pin pairs)
        spacings = [
            _distance(
                ProbePoint("", "", pins_with_probes[i].x, pins_with_probes[i].y,
                           "", "", None, None, 4),
                ProbePoint("", "", pins_with_probes[j].x, pins_with_probes[j].y,
                           "", "", None, None, 4),
            )
            for i, j in itertools.combinations(range(len(pins_with_probes)), 2)
        ]
        if not spacings:
            continue
        spacings.sort()
        pitch = spacings[0]   # smallest spacing = pad pitch
        threshold_dist = pad_pitch_factor * pitch if pitch > 0 else float("inf")

        for i, j in itertools.combinations(range(len(pins_with_probes)), 2):
            pi, pj = pins_with_probes[i], pins_with_probes[j]
            if pi.net_name == pj.net_name:
                continue
            d = _distance(
                ProbePoint("", "", pi.x, pi.y, "", "", None, None, 4),
                ProbePoint("", "", pj.x, pj.y, "", "", None, None, 4),
            )
            if d <= threshold_dist:
                a = net_best[pi.net_name]
                b = net_best[pj.net_name]
                _add_if_new(
                    a, b,
                    f"Adjacent pins {ref}/{pi.pin_number}({pi.net_name}) ↔ "
                    f"{ref}/{pj.pin_number}({pj.net_name})",
                    component_ref=ref,
                )

    # ------------------------------------------------------------------ #
    # 2. Power rail pairs: GND vs every power net                         #
    # ------------------------------------------------------------------ #
    gnd_nets = [n for n in net_best if _GND_PATTERN.search(n)]
    power_nets = [n for n in net_best if _POWER_PATTERN.search(n)]

    for gnd_name in gnd_nets:
        for pwr_name in power_nets:
            if gnd_name == pwr_name:
                continue
            _add_if_new(
                net_best[gnd_name],
                net_best[pwr_name],
                f"Power rail isolation: {gnd_name} ↔ {pwr_name}",
            )

    # ------------------------------------------------------------------ #
    # 3. Connector adjacent pin pairs                                      #
    # ------------------------------------------------------------------ #
    for ref, comp in components.items():
        if not _CONNECTOR_PREFIX.match(ref):
            continue
        pins_sorted = sorted(
            [p for p in comp.pins if p.net_name in net_best],
            key=lambda p: int(p.pin_number) if p.pin_number.isdigit() else 0,
        )
        for i in range(len(pins_sorted) - 1):
            pi, pj = pins_sorted[i], pins_sorted[i + 1]
            if pi.net_name == pj.net_name:
                continue
            _add_if_new(
                net_best[pi.net_name],
                net_best[pj.net_name],
                f"Connector {ref} adjacent pins "
                f"{pi.pin_number}({pi.net_name}) ↔ {pj.pin_number}({pj.net_name})",
                component_ref=ref,
            )

    logger.info("Isolation: generated %d test cases", len(test_cases))
    return test_cases
