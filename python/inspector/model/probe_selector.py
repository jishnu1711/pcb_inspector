"""
model/probe_selector.py
------------------------
For each net, ranks ProbePoints by accessibility tier and prunes any that are
too close together (minimum separation from config.yaml).

Accessibility tiers (lower = better):
  1 → test pad  (ref starts with TP)
  2 → via
  3 → thru_hole
  4 → smd

After selection:
  - Each Net.probe_points list is sorted best-first.
  - Probes that are within min_separation_mm of a better-tier probe are dropped.
  - Nets with 0 remaining probe points are logged as untestable.

Returns an updated dict[net_name → Net] (mutates in-place and also returns it).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import yaml

from inspector.model.types import Net, ProbePoint

logger = logging.getLogger(__name__)


def _distance(a: ProbePoint, b: ProbePoint) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def select_probes(
    nets: dict[str, Net],
    config_path: str = "config.yaml",
    min_separation_mm: Optional[float] = None,
) -> dict[str, Net]:
    """
    Sort and prune each net's probe_points list in-place.

    Parameters
    ----------
    nets              : dict from electrical_model.build_electrical_model
    config_path       : path to config.yaml
    min_separation_mm : override; if None, read from config.yaml

    Returns the same dict (mutated).
    """
    # --- load config ---
    if min_separation_mm is None:
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            min_separation_mm = float(
                cfg.get("thresholds", {}).get("min_probe_separation_mm", 0.5)
            )
        except Exception as exc:
            logger.warning("Could not read config — using 0.5 mm separation: %s", exc)
            min_separation_mm = 0.5

    logger.info("Probe selector: min separation = %.2f mm", min_separation_mm)

    untestable: list[str] = []

    for net_name, net in nets.items():
        if not net.probe_points:
            untestable.append(net_name)
            continue

        # 1. Sort by (tier, pad_type stability) — stable sort keeps original order
        #    for equal tiers (e.g. multiple smd pads on same net).
        net.probe_points.sort(key=lambda p: (p.accessibility_tier, p.id))

        # 2. Greedy distance filter: keep a point only if it is at least
        #    min_separation_mm from every already-kept point.
        kept: list[ProbePoint] = []
        for candidate in net.probe_points:
            too_close = any(
                _distance(candidate, k) < min_separation_mm for k in kept
            )
            if not too_close:
                kept.append(candidate)

        net.probe_points = kept

        if len(kept) == 0:
            untestable.append(net_name)
        elif len(kept) == 1:
            logger.debug("Net %-25s  1 probe point (continuity untestable)", net_name)
        else:
            logger.debug(
                "Net %-25s  %d probe points  best-tier=%d",
                net_name, len(kept), kept[0].accessibility_tier,
            )

    if untestable:
        logger.warning(
            "%d nets have no usable probe points and will be skipped: %s",
            len(untestable), untestable,
        )

    return nets
