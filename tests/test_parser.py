from __future__ import annotations

import math

import pytest

pytest.importorskip("kiutils")

from inspector.parser import kicad_pcb_parser as pcb_parser


class Point:
    def __init__(self, x: float, y: float, angle: float | None = None):
        self.X = x
        self.Y = y
        self.angle = angle


class FakeNet:
    def __init__(self, number: int, name: str):
        self.number = number
        self.name = name


class FakePad:
    def __init__(self):
        self.number = "1"
        self.net = FakeNet(1, "+5V")
        self.layers = ["F.Cu"]
        self.type = "smd"
        self.position = Point(2.0, 0.0)


class FakeFootprint:
    def __init__(self):
        self.entryName = "U1"
        self.position = Point(100.0, 50.0, 90.0)
        self.pads = [FakePad()]


class FakeSegment:
    def __init__(self):
        self.net = 1
        self.start = Point(10.0, 10.0)
        self.end = Point(30.0, 10.0)
        self.width = 0.25
        self.layer = "F.Cu"


class FakeArc:
    def __init__(self):
        self.net = 1
        self.start = Point(30.0, 10.0)
        self.mid = Point(35.0, 15.0)
        self.end = Point(40.0, 10.0)
        self.width = 0.2
        self.layer = "B.Cu"


class FakeVia:
    def __init__(self):
        self.net = 2
        self.position = Point(20.0, 20.0)
        self.layers = ["F.Cu", "B.Cu"]


class FakeBoard:
    def __init__(self):
        self.nets = [FakeNet(1, "+5V"), FakeNet(2, "GND")]
        self.footprints = [FakeFootprint()]
        self.traceItems = [FakeSegment(), FakeArc(), FakeVia()]


def test_absolute_position_uses_negative_kicad_rotation():
    footprint = FakeFootprint()
    pad = footprint.pads[0]

    x, y = pcb_parser._absolute_position(footprint, pad)

    assert math.isclose(x, 100.0, abs_tol=1e-6)
    assert math.isclose(y, 48.0, abs_tol=1e-6)


def test_parse_pcb_collects_segments_arcs_and_vias_by_net_id(tmp_path, monkeypatch):
    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(pcb_parser, "Segment", FakeSegment)
    monkeypatch.setattr(pcb_parser, "Arc", FakeArc)
    monkeypatch.setattr(pcb_parser, "Via", FakeVia)
    monkeypatch.setattr(pcb_parser.Board, "from_file", staticmethod(lambda _: FakeBoard()))

    data = pcb_parser.parse_pcb(pcb_path)

    assert data.nets == {"+5V": 1, "GND": 2}
    assert len(data.pads) == 1
    assert data.pads[0].x == 100.0
    assert data.pads[0].y == 48.0

    assert len(data.traces) == 1
    assert data.traces[0].net_name == "+5V"
    assert data.traces[0].x1 == 10.0
    assert data.traces[0].x2 == 30.0
    assert data.traces[0].width == 0.25

    assert len(data.trace_arcs) == 1
    assert data.trace_arcs[0].net_name == "+5V"
    assert data.trace_arcs[0].mid == (35.0, 15.0)
    assert data.trace_arcs[0].layer == "B.Cu"

    assert len(data.vias) == 1
    assert data.vias[0].net_name == "GND"
    assert data.vias[0].x == 20.0
