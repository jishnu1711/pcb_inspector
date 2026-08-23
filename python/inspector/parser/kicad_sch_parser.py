# parser/kicad_sch_parser.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kiutils.schematic import Schematic
from kiutils.symbol import Symbol


@dataclass
class RawPin:
    pin_number: str
    pin_name: str
    pin_type: str       # "input" | "output" | "passive" | "power_in" etc.


@dataclass
class RawComponent:
    ref: str
    value: str
    footprint: str
    lib_symbol: str     # e.g. "Device:D" or "Device:LED"
    pins: list[RawPin]


@dataclass
class RawSchData:
    file_path: str
    components: dict[str, RawComponent]   # ref → RawComponent


def parse_sch(sch_path: str | Path) -> RawSchData:
    sch_path = Path(sch_path)
    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {sch_path}")

    sch = Schematic.from_file(str(sch_path))

    # --- Build pin lookup from library symbols embedded in the schematic ---
    # sch.libSymbols: List[Symbol]
    # Each Symbol has .name, .pins (List[SymbolPin]), .units (List[Symbol])
    # Pins can be on the parent symbol OR inside units — collect both
    lib_pin_lookup: dict[str, dict[str, RawPin]] = {}   # lib_name → {pin_number → RawPin}

    for lib_sym in sch.libSymbols:
        pin_map: dict[str, RawPin] = {}

        # Pins directly on the symbol
        for p in lib_sym.pins:
            pin_map[str(p.number)] = RawPin(
                pin_number=str(p.number),
                pin_name=p.name or "",
                pin_type=p.electricalType or "passive",
            )

        # Pins inside units (multi-unit symbols like op-amps)
        for unit in lib_sym.units:
            for p in unit.pins:
                pin_map[str(p.number)] = RawPin(
                    pin_number=str(p.number),
                    pin_name=p.name or "",
                    pin_type=p.electricalType or "passive",
                )

        lib_pin_lookup[lib_sym.libId] = pin_map
        lib_pin_lookup[lib_sym.entryName] = pin_map

    # --- Process schematic symbol instances ---
    components: dict[str, RawComponent] = {}

    for symbol in sch.schematicSymbols:
        if _is_power_symbol(symbol):
            continue

        ref = _get_property(symbol, "Reference")
        if not ref or ref.startswith("#"):
            continue

        value     = _get_property(symbol, "Value") or ""
        footprint = _get_property(symbol, "Footprint") or ""
        lib_id    = symbol.libId or ""

        # symbol.pins is Dict[pin_number_str → uuid_str]
        # Cross-reference with lib_pin_lookup to get names/types
        entry_name = symbol.entryName or ""
        pin_defs   = lib_pin_lookup.get(lib_id, {}) or lib_pin_lookup.get(entry_name, {})

        pins: list[RawPin] = []
        for pin_number in symbol.pins.keys():
            if pin_number in pin_defs:
                pins.append(pin_defs[pin_number])
            else:
                # Pin exists on instance but not found in lib — add with minimal info
                pins.append(RawPin(
                    pin_number=pin_number,
                    pin_name="",
                    pin_type="passive",
                ))

        components[ref] = RawComponent(
            ref=ref,
            value=value,
            footprint=footprint,
            lib_symbol=lib_id,
            pins=pins,
        )

    return RawSchData(
        file_path=str(sch_path),
        components=components,
    )


# --- Helpers ---

def _get_property(symbol, key: str) -> Optional[str]:
    if not symbol.properties:
        return None
    for prop in symbol.properties:
        if prop.key == key:
            return prop.value
    return None


def _is_power_symbol(symbol) -> bool:
    lib_id = symbol.libId or ""
    if lib_id.startswith("power:"):
        return True
    ref = _get_property(symbol, "Reference") or ""
    return ref.startswith("#PWR") or ref.startswith("#FLG")


# --- CLI quick-test ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m parser.kicad_sch_parser <path/to/board.kicad_sch>")
        sys.exit(1)

    data = parse_sch(sys.argv[1])

    print(f"\n=== Schematic: {data.file_path} ===")
    print(f"Components: {len(data.components)}")
    print("\n--- All components ---")
    for ref, comp in sorted(data.components.items()):
        print(f"  {ref:<8} value={comp.value:<20} lib={comp.lib_symbol}")
        for pin in comp.pins:
            print(f"           pin {pin.pin_number:>3}  name={pin.pin_name:<8}  type={pin.pin_type}")
class KiCadSchParser:
    def __init__(self, path: str):
        self.path = path
    def parse(self) -> RawSchData:
        return parse_sch(self.path)