# parser/kicad_pcb_parser.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import tempfile
from typing import Optional

from kiutils.board import Board
from kiutils.items.brditems import Arc, Segment, Via


@dataclass
class RawPad:
    component_ref: str
    pad_number: str
    net_name: str
    x: float
    y: float
    layer: str
    pad_type: str          # "smd" | "thru_hole" | "np_thru_hole" | "connect"
    drill: bool            # True if through-hole


@dataclass
class RawVia:
    net_name: str
    x: float
    y: float
    layers: list[str]      # e.g. ["F.Cu", "B.Cu"]


@dataclass
class RawTrace:
    net_name: Optional[str]
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: str


@dataclass
class RawTraceArc:
    net_name: Optional[str]
    start: tuple[float, float]
    mid: tuple[float, float]
    end: tuple[float, float]
    width: float
    layer: str


@dataclass
class RawPCBData:
    file_path: str
    nets: dict[str, int]           # net_name → net_id
    pads: list[RawPad]
    vias: list[RawVia]
    traces: list[RawTrace] = field(default_factory=list)
    trace_arcs: list[RawTraceArc] = field(default_factory=list)


def parse_pcb(pcb_path: str | Path) -> RawPCBData:
    """
    Parse a .kicad_pcb file and return all nets, pads, and vias.
    No inference — pure structural extraction.
    """
    pcb_path = Path(pcb_path)
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    board = _load_board_with_kiutils(pcb_path)

    # --- Collect net name → id mapping ---
    nets: dict[str, int] = {}
    for net in board.nets:
        nets[net.name] = net.number
    net_id_to_name = {net_id: name for name, net_id in nets.items()}

    # --- Collect pads from all footprints ---
    pads: list[RawPad] = []
    for footprint in board.footprints:
        ref = _footprint_reference(footprint)  # component reference e.g. "R1", "U2"

        for pad in footprint.pads:
            # Skip unconnected pads
            if not pad.net or not pad.net.name:
                continue

            net_name = pad.net.name

            # Determine primary copper layer
            # pad.layers is a list; primary layer is first F.Cu or B.Cu
            copper_layer = _primary_copper_layer(pad.layers)
            if copper_layer is None:
                continue

            # Absolute position (kiutils gives position relative to footprint)
            abs_x, abs_y = _absolute_position(footprint, pad)

            pad_type = pad.type if pad.type else "smd"
            is_drill = pad_type in ("thru_hole", "np_thru_hole")

            pads.append(RawPad(
                component_ref=ref,
                pad_number=str(pad.number),
                net_name=net_name,
                x=round(abs_x, 4),
                y=round(abs_y, 4),
                layer=copper_layer,
                pad_type=pad_type,
                drill=is_drill,
            ))

    # --- Collect copper trace items ---
    vias: list[RawVia] = []
    traces: list[RawTrace] = []
    trace_arcs: list[RawTraceArc] = []
    for item in board.traceItems:
        net_name = _net_name_from_id(getattr(item, "net", 0), net_id_to_name)

        if isinstance(item, Segment):
            if not net_name:
                continue
            traces.append(RawTrace(
                net_name=net_name,
                x1=round(float(item.start.X), 4),
                y1=round(float(item.start.Y), 4),
                x2=round(float(item.end.X), 4),
                y2=round(float(item.end.Y), 4),
                width=float(item.width),
                layer=item.layer,
            ))
        elif isinstance(item, Arc):
            if not net_name:
                continue
            trace_arcs.append(RawTraceArc(
                net_name=net_name,
                start=(round(float(item.start.X), 4), round(float(item.start.Y), 4)),
                mid=(round(float(item.mid.X), 4), round(float(item.mid.Y), 4)),
                end=(round(float(item.end.X), 4), round(float(item.end.Y), 4)),
                width=float(item.width),
                layer=item.layer,
            ))
        elif isinstance(item, Via):
            if not net_name:
                continue
            vias.append(RawVia(
                net_name=net_name,
                x=round(float(item.position.X), 4),
                y=round(float(item.position.Y), 4),
                layers=list(item.layers) if item.layers else ["F.Cu", "B.Cu"],
            ))

    return RawPCBData(
        file_path=str(pcb_path),
        nets=nets,
        pads=pads,
        vias=vias,
        traces=traces,
        trace_arcs=trace_arcs,
    )


# --- Helpers ---

_NAME_ONLY_NET_RE = re.compile(r'\(net\s+"((?:\\.|[^"\\])*)"\)')
_NUMBERED_NET_RE = re.compile(r'\(net\s+(\d+)\s+"((?:\\.|[^"\\])*)"\)')


def _load_board_with_kiutils(pcb_path: Path):
    """Load a board, normalizing KiCad 10 name-only net refs if needed."""
    try:
        return Board.from_file(str(pcb_path))
    except IndexError:
        text = pcb_path.read_text(encoding="utf-8")
        normalized = _normalize_name_only_net_refs(text)
        if normalized == text:
            raise

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".kicad_pcb",
            delete=True,
        ) as tmp:
            tmp.write(normalized)
            tmp.flush()
            return Board.from_file(tmp.name)


def _normalize_name_only_net_refs(text: str) -> str:
    """
    Convert KiCad 10-style `(net "NAME")` references into the older
    `(net ID "NAME")` shape expected by kiutils 1.4.x.
    """
    existing_by_name: dict[str, int] = {}
    max_id = 0
    for match in _NUMBERED_NET_RE.finditer(text):
        net_id = int(match.group(1))
        net_name = match.group(2)
        existing_by_name.setdefault(net_name, net_id)
        max_id = max(max_id, net_id)

    name_to_id = dict(existing_by_name)
    missing_header_names: list[str] = []

    for match in _NAME_ONLY_NET_RE.finditer(text):
        net_name = match.group(1)
        if net_name not in name_to_id:
            max_id += 1
            name_to_id[net_name] = max_id
            missing_header_names.append(net_name)

    if not missing_header_names:
        return text

    def replace_name_only(match: re.Match[str]) -> str:
        net_name = match.group(1)
        return f'(net {name_to_id[net_name]} "{net_name}")'

    normalized = _NAME_ONLY_NET_RE.sub(replace_name_only, text)
    header = "".join(
        f'\t(net {name_to_id[name]} "{name}")\n'
        for name in missing_header_names
    )
    return normalized.replace("(kicad_pcb\n", f"(kicad_pcb\n{header}", 1)

def _primary_copper_layer(layers) -> Optional[str]:
    """Return the most accessible copper layer from a pad's layer list."""
    if layers is None:
        return None
    preference = ["F.Cu", "B.Cu"]
    for preferred in preference:
        if preferred in layers:
            return preferred
    # Accept any copper layer
    for layer in layers:
        if layer.endswith(".Cu") or "Cu" in layer:
            return layer
    return None


def _net_name_from_id(net_id, net_id_to_name: dict[int, str]) -> Optional[str]:
    """Resolve a trace/via net number to a net name."""
    if not net_id:
        return None
    try:
        return net_id_to_name.get(int(net_id))
    except (TypeError, ValueError):
        return None


def _footprint_reference(footprint) -> str:
    """Return the component reference from a footprint across KiCad formats."""
    properties = getattr(footprint, "properties", None)
    if isinstance(properties, dict):
        ref = properties.get("Reference")
        if ref:
            return str(ref)
    return str(getattr(footprint, "entryName", ""))


def _absolute_position(footprint, pad) -> tuple[float, float]:
    """
    Compute absolute pad position from footprint position + pad offset.
    kiutils stores footprint position and pad position separately.
    """
    import math

    if footprint.position is None:
        raise ValueError(f"Footprint {getattr(footprint, 'entryName', '<unknown>')} has no position")
    if pad.position is None:
        raise ValueError(
            f"Pad {getattr(pad, 'number', '<unknown>')} on "
            f"{getattr(footprint, 'entryName', '<unknown>')} has no position"
        )

    fp_x = float(footprint.position.X)
    fp_y = float(footprint.position.Y)
    fp_angle = float(footprint.position.angle or 0.0)

    pad_x = float(pad.position.X)
    pad_y = float(pad.position.Y)

    # KiCad footprint angles rotate local pad coordinates clockwise in board space.
    angle_rad = math.radians(-fp_angle)
    rot_x = pad_x * math.cos(angle_rad) - pad_y * math.sin(angle_rad)
    rot_y = pad_x * math.sin(angle_rad) + pad_y * math.cos(angle_rad)

    return fp_x + rot_x, fp_y + rot_y


# --- CLI quick-test ---
if __name__ == "__main__":
    import sys, json

    if len(sys.argv) < 2:
        print("Usage: python -m parser.kicad_pcb_parser <path/to/board.kicad_pcb>")
        sys.exit(1)

    data = parse_pcb(sys.argv[1])

    print(f"\n=== PCB: {data.file_path} ===")
    print(f"Nets   : {len(data.nets)}")
    print(f"Pads   : {len(data.pads)}")
    print(f"Vias   : {len(data.vias)}")

    print("\n--- First 5 pads ---")
    for p in data.pads[:5]:
        print(f"  {p.component_ref} pad {p.pad_number:>4}  net={p.net_name:<20} "
              f"({p.x:>8.3f}, {p.y:>8.3f})  layer={p.layer}  type={p.pad_type}")

    print("\n--- First 5 vias ---")
    for v in data.vias[:5]:
        print(f"  net={v.net_name:<20} ({v.x:>8.3f}, {v.y:>8.3f})  layers={v.layers}")

class KiCadPCBParser:
    def __init__(self, path: str):
        self.path = path
    def parse(self) -> RawPCBData:
        return parse_pcb(self.path)
