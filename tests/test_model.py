from __future__ import annotations

import pytest

pytest.importorskip("kiutils")

from inspector.model.electrical_model import build_electrical_model
from inspector.parser.kicad_pcb_parser import RawPCBData, RawTrace, RawTraceArc, RawVia
from inspector.parser.kicad_sch_parser import RawSchData


def test_electrical_model_attaches_trace_geometry_to_nets():
    pcb = RawPCBData(
        file_path="board.kicad_pcb",
        nets={"+5V": 1, "GND": 2},
        pads=[],
        vias=[RawVia(net_name="GND", x=5.0, y=6.0, layers=["F.Cu", "B.Cu"])],
        traces=[
            RawTrace(
                net_name="+5V",
                x1=10.0,
                y1=10.0,
                x2=30.0,
                y2=10.0,
                width=0.25,
                layer="F.Cu",
            )
        ],
        trace_arcs=[
            RawTraceArc(
                net_name="+5V",
                start=(30.0, 10.0),
                mid=(35.0, 15.0),
                end=(40.0, 10.0),
                width=0.2,
                layer="B.Cu",
            )
        ],
    )
    sch = RawSchData(file_path="board.kicad_sch", components={})

    nets, components = build_electrical_model(pcb, sch, classifications={})

    assert components == {}
    assert len(nets["+5V"].traces) == 1
    assert nets["+5V"].traces[0].x1 == 10.0
    assert nets["+5V"].traces[0].layer == "F.Cu"
    assert len(nets["+5V"].trace_arcs) == 1
    assert nets["+5V"].trace_arcs[0].mid == (35.0, 15.0)

    assert len(nets["GND"].probe_points) == 1
    assert nets["GND"].probe_points[0].pad_type == "via"
