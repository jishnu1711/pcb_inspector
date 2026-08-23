# `test_generator/`

## Role in the pipeline

This layer takes the electrical model and produces a flat list of `TestCase` objects — one per physical test the hardware needs to execute. It is entirely deterministic. No AI, no guessing. Every test case it generates follows directly from the electrical model with explicit, auditable rules.

```
model/ElectricalModel  ──→  generator.py  ──→  list[TestCase]  ──→  llm_planner/
```

The output of this layer is an unordered list — ordering and prioritisation is handled downstream by the AI planner. This layer only decides *what* to test, not *in what order*.

---

## Files

### `generator.py`

**What it does:**
The orchestrator. Calls the three sub-generators in sequence and merges their outputs into a single `list[TestCase]`.

**Flow:**
```python
tests = []
tests += continuity_gen.generate(model)
tests += isolation_gen.generate(model)
tests += diode_gen.generate(model)
return tests
```

Assigns a unique `id` to each test case (`tc_001`, `tc_002`, ...) before returning.

---

### `continuity_gen.py`

**What it does:**
For every net that has 2 or more probe points, generates test cases that verify the net is actually connected end-to-end.

**The logic:**

A net is a logical claim: "all these pads should be electrically connected." Continuity tests verify that claim physically.

**Spanning tree approach:**
Rather than testing every pair of points on a net (which is O(N²)), the generator connects probe points in a chain:

```
Net with points A, B, C, D:
  generates: A↔B, B↔C, C↔D   (3 tests, not 6)
```

If any single link in the chain fails, it implies an open between those two points. This covers the net with the minimum number of tests.

**Expected result per test:**
```python
expected = { "resistance_max_ohm": 10.0 }
```
Default threshold is 10 Ω. Configurable in `config.yaml`. Industry standard for flying-probe continuity is typically 5–25 Ω depending on board complexity.

**What gets skipped:**
- Nets with only 1 probe point — cannot test both ends, logged as untestable
- Nets named `""` or unconnected pseudo-nets

---

### `isolation_gen.py`

**What it does:**
Generates tests that verify two pads on *different* nets are *not* connected — catching solder bridges, contamination, and shorts.

**Why not test every net pair:**
A board with 100 nets has 4,950 possible net pairs. Testing all of them is impractical. Instead, the generator focuses on the highest-risk pairs:

**Strategy 1 — Adjacent pad isolation:**
For each component, checks all pairs of neighbouring pins (pads within 2× the pad pitch of each other). Adjacent pads are the most common source of solder bridges because they are physically close and share the same solder paste stencil opening.

**Strategy 2 — Power rail isolation:**
Always tests GND against every power net found on the board (VCC, VBAT, V3V3, V5V, etc.). A short between power and ground is the most destructive possible fault and must always be checked first.

**Strategy 3 — Connector pin isolation:**
Pins on connectors (`J*`, `P*`, `CN*` references) are high risk because they are often hand-assembled and are the most common point of assembly error. Adjacent connector pins always get isolation tests.

**Expected result per test:**
```python
expected = { "resistance_min_ohm": 1_000_000 }
```
Default threshold is 1 MΩ. If measured resistance is below this, the test fails — the two nets have an unintended connection.

---

### `diode_gen.py`

**What it does:**
For every component classified as a diode or LED, generates two test cases: one forward-bias test and one reverse-bias test.

**Preconditions (all must be true to generate a diode test):**
1. Component type from AI classifier is `"diode"` or `"led"`
2. AI classifier has provided `pin_roles` identifying which pin is anode and which is cathode
3. Both the anode pin and cathode pin have probe points in the electrical model

If any precondition fails, the component gets a continuity-only test instead, and the gap is flagged in the report.

**Forward test — probe A on anode, probe B on cathode:**
```python
test_type = "diode_forward"
expected = {
    "vf_min_v": 0.6,   # from AI classification or BOM override
    "vf_max_v": 0.75
}
```
Pass means: the diode conducts in the forward direction with a voltage drop in the expected range.
Fail means: open circuit (no conduction), short circuit (0V drop), or reversed installation.

**Reverse test — probe A on cathode, probe B on anode:**
```python
test_type = "diode_reverse"
expected = {
    "resistance_min_ohm": 100_000
}
```
Pass means: the diode blocks current in the reverse direction.
Fail means: diode is shorted, or installed backwards (which would have shown up as a forward-test failure too).

**Threshold source priority:**
1. BOM annotation (user-supplied, most trusted)
2. AI classifier `test_parameters` (from LLM knowledge of the part number)
3. Generic defaults (0.3–0.9 V for diodes, 1.8–3.5 V for LEDs)

---

## What this layer guarantees

- Every generated test has a valid pair of `ProbePoint`s with real coordinates
- Every expected threshold has a value — there are no tests with undefined pass criteria
- No test is generated for a net pair that is intentionally connected
- The output is a plain list — no ordering assumptions, no hardware-specific fields
- All test logic is auditable: given the same `ElectricalModel`, the same tests are always generated
