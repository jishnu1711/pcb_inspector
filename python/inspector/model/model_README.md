# `model/`

## Role in the pipeline

This layer is the **brain of the system**. It takes raw data from the parsers and the AI classification, joins everything together, and produces a clean, unified electrical model that the rest of the system works from.

```
parser/kicad_pcb_parser  ──┐
                            ├──→  electrical_model.py  ──→  probe_selector.py  ──→  test_generator/
parser/kicad_sch_parser  ──┤
                            │
model/component_classifier ─┘  (calls LLM internally)
```

Nothing in `test_generator/`, `llm_planner/`, `executor/`, or `report/` touches the raw parser output directly — they all consume the model objects defined here.

---

## Files

### `types.py`

**What it does:**
Defines all the core dataclasses used throughout the project. Every other module imports from here.

**Why it's its own file:**
Prevents circular imports. `electrical_model.py`, `probe_selector.py`, `test_generator/`, `executor/`, and `report/` all need these types. Centralising them means no module needs to import from another module just to get a type definition.

**Key types defined:**

| Type | What it represents |
|---|---|
| `ProbePoint` | A single physical location on the board that a probe can touch — has real x/y coordinates, layer, net, and accessibility tier |
| `Net` | A logical electrical connection — a named set of `ProbePoint`s that should all be electrically connected |
| `Pin` | One pin of one component — connects a component to a net, carries pin name and role |
| `Component` | A real component on the board — has a type, value, and list of pins |
| `TestCase` | One test to execute — two probe points, a test type, and expected thresholds |
| `TestPattern` | The full ordered list of `TestCase`s — this is what gets written to JSON and sent to hardware |
| `TestResult` | The measured outcome of one executed `TestCase` |
| `FaultReport` | The complete post-execution report — all results, pass/fail counts, and fault narrative |

---

### `electrical_model.py`

**What it does:**
Joins PCB data + schematic data + AI component classification into a single coherent model.

**The join it performs:**
```
PCB pad:  ref="D3", pin="1", net="NET_LED_ANODE", x=42.15, y=28.30
SCH pin:  ref="D3", pin="1", name="A", type="passive"
AI class: ref="D3", component_type="diode", pin_roles={"1":"anode","2":"cathode"}

Result →  Pin(ref="D3", pin="1", name="A", role="anode", net="NET_LED_ANODE", x=42.15, y=28.30)
```

Without this join:
- The PCB file knows *where* pin 1 of D3 is but not that it is an anode
- The schematic knows pin 1 is named "A" but not where it is
- The AI knows D3 is a diode but not its coordinates

**What it builds:**
- `Net` objects: for each net name, collects all pads/vias that belong to it
- `Component` objects: one per component reference, with type from AI classification
- `Pin` objects: one per pad, with coordinates from PCB and role from AI + schematic

**Output:** `ElectricalModel` — the single object passed to `probe_selector.py`

---

### `component_classifier.py`

**What it does:**
This is where AI enters the pipeline for the first time. For each component extracted from the schematic, it sends a prompt to the LLM and gets back a structured classification.

**Why AI here instead of hardcoding:**
The schematic gives you a component name like `LM317`, `PMEG3010`, or `TS3A5018`. You cannot know what that component does, how to test it, or what its parameters are without external knowledge. A hardcoded lookup table covers maybe 20 common parts and breaks immediately on anything else. The LLM has seen thousands of datasheets and can classify almost any real component correctly.

**What it asks the LLM:**
For each component, it sends: `ref`, `value`, `lib_symbol`, and pin list (numbers + names).

**What it gets back (structured JSON):**
```json
{
  "component_type": "diode",
  "applicable_tests": ["continuity", "diode_forward", "diode_reverse"],
  "test_parameters": { "vf_min_v": 0.6, "vf_max_v": 0.75 },
  "pin_roles": { "1": "anode", "2": "cathode" },
  "confidence": "high",
  "reasoning": "1N4148 is a standard small-signal switching diode"
}
```

**Confidence gating:**
- `high` → use all applicable tests including parametric ones
- `medium` → use all tests but widen thresholds by 20%
- `low` → continuity only; skip parametric tests; flag component in report for manual review

**What it does NOT do:**
- It does not decide where on the board to probe (that is `probe_selector.py`)
- It does not generate test cases (that is `test_generator/`)
- It does not touch coordinates or net names

---

### `probe_selector.py`

**What it does:**
For each net in the electrical model, selects the best physical probe points — the actual (x, y) coordinates the hardware will move to.

**Why selection is needed:**
A net can have dozens of pads. You do not want to probe every one — that wastes time. You want the most accessible, most reliable probe locations. You also need at least two points per net for a continuity test.

**Accessibility tiers (in priority order):**

| Tier | Pad type | Why preferred |
|---|---|---|
| 1 | Dedicated test pad (`TP*` reference) | Designed to be probed — large, exposed, reliable |
| 2 | Via | Through-board, accessible from either side |
| 3 | Through-hole pad | Large drill hole, easy to contact reliably |
| 4 | SMD pad | Small, fragile, last resort |

**Rules applied:**
- Minimum probe separation enforced (configurable, default 0.5 mm) — prevents the two probes from touching each other
- For each net, selects the top 2 probe points by tier
- For large nets, builds a spanning tree (N points → N-1 test pairs) to cover connectivity without O(N²) test explosion

**Output:** Adds a ranked `ProbePoint` list to each `Net` in the electrical model.

---

## What this layer guarantees

- Every object has a single source of truth — coordinates only come from the PCB file, component knowledge only comes from the AI/schematic
- The join is explicit — if a pad exists in the PCB but not the schematic (e.g. a mechanical pad), it is still included but with no component context
- AI classification failures are handled gracefully — unknown components fall back to continuity-only testing, never silently dropped
