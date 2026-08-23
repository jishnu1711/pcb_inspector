# `parser/`

## Role in the pipeline

This is the **entry point** of the entire system. Nothing downstream can run until this layer has executed. The parser's only job is to read KiCad files and return raw structured data — it does not interpret, classify, or make decisions about what anything means electrically.

```
.kicad_pcb  ──→  kicad_pcb_parser.py  ──┐
                                         ├──→  model/electrical_model.py
.kicad_sch  ──→  kicad_sch_parser.py  ──┘
```

---

## Files

### `kicad_pcb_parser.py`

**What it does:**
Parses the `.kicad_pcb` file — the physical board layout — using the `kiutils` library.

**What it extracts:**
- Every pad on every footprint: position (x, y in mm), copper layer, net name, pad type (SMD / through-hole), component reference, pin number
- Every via: position, net name, copper layers it spans
- Net name → net ID mapping for the whole board

**What it does NOT do:**
- It does not know what a component is or what it does
- It does not decide which pads are testable
- It does not understand pin roles (anode, cathode, input, output)

**Key output type:** `RawPCBData`
```
RawPCBData
  .nets   → dict[net_name → net_id]
  .pads   → list[RawPad]
  .vias   → list[RawVia]
```

**How to test it standalone:**
```bash
python -m parser.kicad_pcb_parser path/to/board.kicad_pcb
```

**Key implementation detail:**
KiCad stores pad positions relative to their parent footprint origin. The parser rotates and translates each pad position using the footprint's absolute position and rotation angle to produce correct absolute board coordinates.

---

### `kicad_sch_parser.py`

**What it does:**
Parses the `.kicad_sch` file — the logical schematic — using `kiutils`.

**What it extracts:**
- Every real component instance: reference (e.g. `D3`), value (e.g. `1N4148`), footprint string, library symbol ID (e.g. `Device:D`)
- Every pin on every component: pin number, pin name (e.g. `A`, `K`, `GND`), electrical type (e.g. `passive`, `power_in`, `output`)

**What it does NOT do:**
- It does not know where components are physically on the board (no x/y coordinates)
- It does not decide what tests to run
- It does not classify components — that is `model/component_classifier.py`'s job

**Key output type:** `RawSchData`
```
RawSchData
  .components → dict[ref → RawComponent]

RawComponent
  .ref         → "D3"
  .value        → "1N4148"
  .lib_symbol   → "Device:D"
  .pins         → list[RawPin]

RawPin
  .pin_number   → "1"
  .pin_name     → "A"
  .pin_type     → "passive"
```

**How to test it standalone:**
```bash
python -m parser.kicad_sch_parser path/to/board.kicad_sch
```

**Key implementation detail:**
In kiutils, a `SchematicSymbol` (an instance placed on the schematic) stores pins as a plain `dict[pin_number → uuid]` — just a reference, no names or types. The actual pin names and electrical types live in `sch.libSymbols` (the embedded library definitions). The parser builds a lookup table from `libSymbols` first, then cross-references each instance's pin numbers against it to produce complete `RawPin` objects. Both `libId` (`"Device:D"`) and `entryName` (`"D"`) are indexed so the lookup is robust.

---

### `bom_parser.py`

**What it does:**
Parses an optional CSV bill-of-materials file that the user can provide to supply component parameters that cannot be inferred automatically.

**Why it exists:**
The schematic tells you a component is a diode. The LLM can guess its forward voltage from the part number. But if the user wants to override with exact datasheet values (e.g. for a rare or custom part), the BOM is the authoritative source. BOM values always win over LLM inference.

**Expected CSV columns:**
```
Reference, Value, Vf_min, Vf_max, Notes
D1, 1N4148, 0.6, 0.75,
D2, BAT54S, 0.2, 0.4, Schottky
```

**Status:** Optional input. If not provided, the system falls back to LLM inference → hardcoded table → generic defaults, in that order.

---

## What this layer guarantees

- All data returned is a direct reading of the file — no guessing
- If a net name is in the output, it exists in the file
- If a coordinate is in the output, it is the correct physical location on the board
- Power symbols (`#PWR`, `#FLG`, `power:`) are filtered out — they are net labels, not real components
