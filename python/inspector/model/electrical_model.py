"""
model/electrical_model.py
--------------------------
Joins RawPCBData + RawSchData + component classifications into:
  - dict[net_name → Net]
  - dict[ref → Component]

The join key is (component_ref, pin_number).

PCB gives us:   pad positions, net names, pad types
Schematic gives us: pin names, pin types, lib_symbol
Classifier gives us: component_type, applicable_tests, test_parameters, pin_roles

Pin.pin_function is filled from classifier's pin_roles dict.
"""

from __future__ import annotations

import logging

from inspector.parser.kicad_pcb_parser import RawPCBData, RawPad
from inspector.parser.kicad_sch_parser import RawSchData
from inspector.model.types import Component, Net, Pin, ProbePoint, Trace, TraceArc

logger = logging.getLogger(__name__)


def _pad_type_label(raw_pad_type: str, component_ref: str) -> str:
    """Map raw pad_type → ProbePoint.pad_type label, honouring test-pad convention."""
    if component_ref and component_ref.upper().startswith("TP"):
        return "test_pad"
    if raw_pad_type == "thru_hole":
        return "thru_hole"
    if raw_pad_type == "smd":
        return "smd"
    return "smd"   # np_thru_hole and anything else treated as smd for probing


def _accessibility_tier(pad_type_label: str) -> int:
    return {
        "test_pad":  1,
        "via":       2,
        "thru_hole": 3,
        "smd":       4,
    }.get(pad_type_label, 4)


def build_electrical_model(
    pcb: RawPCBData,
    sch: RawSchData,
    classifications: dict[str, dict],   # ref → classifier output dict
) -> tuple[dict[str, Net], dict[str, Component]]:
    """
    Returns:
        nets:       dict[net_name → Net]   (nets hold ProbePoints)
        components: dict[ref → Component]  (components hold Pins)
    """

    # ------------------------------------------------------------------ #
    # 1.  Build a (ref, pad_number) → RawPad lookup from PCB             #
    # ------------------------------------------------------------------ #
    pad_lookup: dict[tuple[str, str], RawPad] = {}
    for pad in pcb.pads:
        key = (pad.component_ref, pad.pad_number)
        if key in pad_lookup:
            logger.debug("Duplicate pad key %s — keeping first", key)
        else:
            pad_lookup[key] = pad

    # ------------------------------------------------------------------ #
    # 2.  Build Nets and ProbePoints from PCB pads                        #
    # ------------------------------------------------------------------ #
    nets: dict[str, Net] = {}

    for net_name in pcb.nets:
        nets[net_name] = Net(name=net_name)

    # Pads → ProbePoints
    for pad in pcb.pads:
        if not pad.net_name:
            continue   # unconnected pad

        net = nets.setdefault(pad.net_name, Net(name=pad.net_name))
        pad_type_label = _pad_type_label(pad.pad_type, pad.component_ref)
        tier = _accessibility_tier(pad_type_label)

        pp = ProbePoint(
            id=f"{pad.component_ref}_p{pad.pad_number}",
            net_name=pad.net_name,
            x=pad.x,
            y=pad.y,
            layer=pad.layer,
            pad_type=pad_type_label,
            component_ref=pad.component_ref,
            pin_number=pad.pad_number,
            accessibility_tier=tier,
        )
        net.probe_points.append(pp)

    # Vias → ProbePoints (tier 2)
    for via in pcb.vias:
        if not via.net_name:
            continue
        net = nets.setdefault(via.net_name, Net(name=via.net_name))
        via_id = f"via_{via.x:.3f}_{via.y:.3f}"
        pp = ProbePoint(
            id=via_id,
            net_name=via.net_name,
            x=via.x,
            y=via.y,
            layer=",".join(via.layers),
            pad_type="via",
            component_ref=None,
            pin_number=None,
            accessibility_tier=2,
        )
        net.probe_points.append(pp)

    # Traces/arcs are copper geometry, not probeable points. Keep them attached
    # to nets for reports/visualization without changing test generation yet.
    for raw_trace in getattr(pcb, "traces", []):
        if not raw_trace.net_name:
            continue
        net = nets.setdefault(raw_trace.net_name, Net(name=raw_trace.net_name))
        net.traces.append(Trace(
            net_name=raw_trace.net_name,
            x1=raw_trace.x1,
            y1=raw_trace.y1,
            x2=raw_trace.x2,
            y2=raw_trace.y2,
            width=raw_trace.width,
            layer=raw_trace.layer,
        ))

    for raw_arc in getattr(pcb, "trace_arcs", []):
        if not raw_arc.net_name:
            continue
        net = nets.setdefault(raw_arc.net_name, Net(name=raw_arc.net_name))
        net.trace_arcs.append(TraceArc(
            net_name=raw_arc.net_name,
            start=raw_arc.start,
            mid=raw_arc.mid,
            end=raw_arc.end,
            width=raw_arc.width,
            layer=raw_arc.layer,
        ))

    logger.info("Built %d nets from PCB data", len(nets))

    # ------------------------------------------------------------------ #
    # 3.  Build Components from Schematic + PCB pad positions             #
    # ------------------------------------------------------------------ #
    components: dict[str, Component] = {}

    for ref, sch_comp in sch.components.items():
        classification = classifications.get(ref, {
            "component_type": "unknown",
            "applicable_tests": ["continuity"],
            "test_parameters": {},
            "pin_roles": {},
            "confidence": "low",
            "reasoning": "No classification available",
        })

        pin_roles: dict[str, str] = classification.get("pin_roles", {})
        pins: list[Pin] = []

        for raw_pin in sch_comp.pins:
            pcb_pad = pad_lookup.get((ref, raw_pin.pin_number))

            if pcb_pad is None:
                # Pin exists in schematic but not placed on PCB (power symbols, etc.)
                logger.debug(
                    "Pin %s/%s has no matching PCB pad — skipping", ref, raw_pin.pin_number
                )
                continue

            pin = Pin(
                component_ref=ref,
                pin_number=raw_pin.pin_number,
                pin_name=raw_pin.pin_name,
                net_name=pcb_pad.net_name,
                x=pcb_pad.x,
                y=pcb_pad.y,
                pin_function=pin_roles.get(raw_pin.pin_number),
            )
            pins.append(pin)

        comp = Component(
            ref=ref,
            value=sch_comp.value,
            component_type=classification.get("component_type", "unknown"),
            pins=pins,
            footprint=sch_comp.footprint,
            applicable_tests=classification.get("applicable_tests", ["continuity"]),
            test_parameters=classification.get("test_parameters", {}),
            ai_confidence=classification.get("confidence", "low"),
            ai_reasoning=classification.get("reasoning"),
        )
        components[ref] = comp

    logger.info("Built %d components from schematic+PCB join", len(components))

    # Warn about PCB pads whose ref isn't in the schematic
    pcb_refs = {pad.component_ref for pad in pcb.pads if pad.component_ref}
    sch_refs = set(sch.components.keys())
    orphan_refs = pcb_refs - sch_refs
    if orphan_refs:
        logger.warning(
            "PCB refs not found in schematic (fiducials/keepouts?): %s",
            sorted(orphan_refs),
        )

    return nets, components
