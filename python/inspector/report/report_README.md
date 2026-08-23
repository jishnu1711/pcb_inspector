# `report/`

## Role in the pipeline

This is the **last layer**. It takes the `TestPattern` (what was expected) and the `list[TestResult]` (what was measured) and produces a `FaultReport` — a complete, human and machine-readable account of what passed, what failed, and what likely went wrong.

```
TestPattern + list[TestResult]  ──→  report_generator.py  ──→  FaultReport
                                                                     │
                                          ┌──────────────────────────┤
                                          ▼                          ▼
                                   fault_report.json        summary.md (optional)
```

The report generator also calls `llm_planner/fault_interpreter.py` for any failed tests — this is the second place in the pipeline where AI is used, to convert raw measurement failures into human-readable fault explanations.

---

## Files

### `report_generator.py`

**What it does:**
- Pairs each `TestResult` with its corresponding `TestCase` by ID
- Evaluates pass/fail for each result by comparing measured value against expected threshold
- Groups failures by component and by net
- Computes summary statistics (total, passed, failed, error counts)
- Calls `fault_interpreter.py` on the failed subset to get AI-generated fault descriptions
- Returns a complete `FaultReport` object

**Pass/fail logic (deterministic — no AI):**

| Test type | Pass condition |
|---|---|
| `continuity` | `measured_resistance ≤ expected.resistance_max_ohm` |
| `isolation` | `measured_resistance ≥ expected.resistance_min_ohm` |
| `diode_forward` | `expected.vf_min_v ≤ measured_voltage ≤ expected.vf_max_v` |
| `diode_reverse` | `measured_resistance ≥ expected.resistance_min_ohm` |

Results with `status="error"` (hardware fault, timeout) are counted separately and never evaluated as pass or fail — a hardware error is not an electrical failure.

**Failure grouping:**
Failures are grouped by component reference first, then by net. This makes it easy to see if one component has multiple failures (likely a single bad part or assembly error) versus scattered failures across nets (likely a systemic issue like contamination).

---

### `formatters/json_formatter.py`

**What it does:**
Serialises the `FaultReport` to a JSON file matching the schema defined in `schemas/fault_report.schema.json`.

This is the **primary machine-readable output** — the file that a test management system, CI pipeline, or database would consume.

**Output structure:**
```json
{
  "board_id": "P_supply_v1",
  "executed_at": "2024-01-15T14:23:01Z",
  "total_tests": 47,
  "passed": 44,
  "failed": 2,
  "errors": 1,
  "results": [ ... ],
  "fault_summary": "Two likely solder bridges near U2 ..."
}
```

---

### `formatters/markdown_formatter.py`

**What it does:**
Produces a human-readable `.md` summary of the test run.

This is the **primary human-readable output** — useful for attaching to a GitHub issue, printing, or displaying in a demo.

**What it includes:**
- Board ID, timestamp, pass/fail counts
- A table of all failed tests with measured vs expected values
- AI-generated fault descriptions per failure
- A section listing untestable components (those the system could not probe)

---

## What this layer guarantees

- Pass/fail decisions are purely deterministic — the AI only provides narrative, never changes a result
- Every `TestCase` in the pattern has a corresponding `TestResult` in the report — nothing is silently missing
- If `fault_interpreter.py` (AI) is unavailable, the report is still complete — just without the narrative section
- The JSON output always validates against `schemas/fault_report.schema.json`
