"""
model/types.py
--------------
All shared dataclasses for the PCB Probe Inspector pipeline.
No logic here — pure data definitions only.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Probe / Net layer
# ---------------------------------------------------------------------------

@dataclass
class ProbePoint:
    id: str                          # unique: "{ref}_p{pad_number}" or "via_{x}_{y}"
    net_name: str
    x: float                         # absolute mm on board
    y: float
    layer: str                       # "F.Cu" | "B.Cu" | "*.Cu"
    pad_type: str                    # "test_pad" | "via" | "thru_hole" | "smd"
    component_ref: Optional[str]     # None for vias
    pin_number: Optional[str]        # None for vias
    accessibility_tier: int          # 1=best (TP*), 2=via, 3=thru_hole, 4=smd


@dataclass
class Net:
    name: str
    probe_points: list[ProbePoint] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    trace_arcs: list[TraceArc] = field(default_factory=list)


@dataclass
class Trace:
    net_name: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: str


@dataclass
class TraceArc:
    net_name: str
    start: tuple[float, float]
    mid: tuple[float, float]
    end: tuple[float, float]
    width: float
    layer: str


# ---------------------------------------------------------------------------
# Component / Pin layer
# ---------------------------------------------------------------------------

@dataclass
class Pin:
    component_ref: str
    pin_number: str
    pin_name: str                    # "A", "K", "GND", "VI", "VO", etc.
    net_name: str
    x: float
    y: float
    pin_function: Optional[str]      # "anode" | "cathode" | "input" | "output" | etc.
                                     # filled in by component_classifier


@dataclass
class Component:
    ref: str
    value: str
    component_type: str              # "diode" | "led" | "resistor" | "capacitor"
                                     # "ic" | "connector" | "switch" | "unknown"
    pins: list[Pin]
    footprint: str
    applicable_tests: list[str]      # ["continuity", "diode_forward", ...]
    test_parameters: dict            # {"vf_min_v": 0.6, "vf_max_v": 0.75, ...}
    ai_confidence: str               # "high" | "medium" | "low"
    ai_reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Test layer
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: str                          # e.g. "cont_0001", "iso_0042", "diode_D3_fwd"
    test_type: str                   # "continuity" | "isolation"
                                     # "diode_forward" | "diode_reverse"
    probe_a: ProbePoint
    probe_b: ProbePoint
    expected: dict                   # {"resistance_max_ohm": 10.0} etc.
    net_a: str
    net_b: Optional[str]             # None for continuity (same net)
    component_ref: Optional[str]     # set for diode tests
    priority: int                    # lower = run first (set by LLM planner)
    rationale: Optional[str]         # human-readable why this test exists


@dataclass
class TestPattern:
    board_id: str
    generated_at: str                # ISO-8601
    kicad_pcb_file: str
    kicad_sch_file: str
    test_cases: list[TestCase]


# ---------------------------------------------------------------------------
# Result / Report layer
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    test_case_id: str
    status: str                      # "pass" | "fail" | "error"
    measured_value: Optional[float]
    unit: Optional[str]              # "ohm" | "V" | None
    timestamp: str                   # ISO-8601
    raw_response: Optional[str]      # raw JSON string from hardware / mock


@dataclass
class FaultReport:
    board_id: str
    executed_at: str                 # ISO-8601
    total_tests: int
    passed: int
    failed: int
    errors: int
    results: list[TestResult]
    fault_summary: Optional[str]     # LLM-generated narrative, or None
