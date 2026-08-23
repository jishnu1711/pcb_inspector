# `llm_planner/`

## Role in the pipeline

This is the **AI layer**. It is the only layer in the system that calls a language model. It sits in two places in the pipeline:

**Before execution** — takes the unordered test list and returns it ordered by priority, with a rationale attached to each test.

**After execution** — takes the list of failed tests and returns a human-readable fault narrative explaining what likely went wrong physically on the board.

```
test_generator/list[TestCase]  ──→  planner.py  ──→  ordered TestPattern  ──→  executor/

executor/list[TestResult]  ──→  fault_interpreter.py  ──→  FaultReport.fault_summary
```

**Critical constraint:** This layer never touches electrical truth. It cannot change thresholds, modify coordinates, add or remove test cases, or make pass/fail decisions. It only reorders and annotates.

---

## Files

### `llm_client.py`

**What it does:**
A single adapter that abstracts away which LLM backend is being used. The rest of the system calls `llm_client.complete(prompt)` and gets back a string — it does not need to know whether the response came from Ollama, the Anthropic API, or OpenAI.

**Supported backends:**
| Backend | When to use |
|---|---|
| `ollama` | Local demo, no internet needed, no API key |
| `anthropic` | Online demo, best output quality |
| `openai` | Alternative online option |

**Configuration** (from `config.yaml`):
```yaml
llm:
  provider: ollama
  model: phi3
  base_url: http://localhost:11434
  timeout_sec: 30
  fallback_on_error: true
```

**Fallback behaviour:**
If the LLM call fails for any reason (model not running, API key missing, timeout, malformed JSON response), the client returns `None`. Every caller checks for `None` and falls back to deterministic behaviour. The LLM being unavailable never crashes the pipeline.

---

### `prompts.py`

**What it does:**
Stores all prompt templates in one place, versioned. No prompt strings are scattered through other files.

**Why centralised:**
Prompts are code. They need to be reviewed, tested, and iterated. Keeping them in one file makes it easy to see exactly what the system is telling the LLM, and to update prompts without touching business logic.

**Prompts defined:**

`COMPONENT_CLASSIFICATION_PROMPT` — used by `model/component_classifier.py`
Sends component ref, value, lib symbol, and pin names. Asks for component type, applicable tests, test parameters, pin roles, and confidence.

`TEST_ORDERING_PROMPT` — used by `planner.py`
Sends the list of test cases (without coordinates — only net names, component refs, test types). Asks for an ordered list of test IDs with a one-line rationale per test.

`FAULT_INTERPRETATION_PROMPT` — used by `fault_interpreter.py`
Sends the list of failed test cases with their measured values. Asks for a likely physical cause per failure and an overall board summary.

**Output format contract:**
Every prompt explicitly instructs the model to return only valid JSON with no preamble, no markdown fences, no explanation outside the JSON structure. The callers validate the response against a schema before using it.

---

### `planner.py`

**What it does:**
Takes the unordered `list[TestCase]` from the test generator and returns the same list reordered by priority, with `rationale` strings attached to each test case.

**What it sends to the LLM:**
A compact summary of each test: test ID, test type, net names, component reference. Coordinates are deliberately excluded — the LLM does not need them and they add noise.

**Ordering principles it instructs the LLM to apply:**
1. Power rail isolation tests (GND vs VCC, etc.) always first — most destructive if wrong
2. Continuity on power nets before signal nets
3. Group tests by component to minimise probe travel distance
4. Diode tests after continuity on the same component

**Fallback ordering (used when LLM unavailable):**
```
priority 1: isolation tests on power nets
priority 2: isolation tests on other nets  
priority 3: continuity tests
priority 4: diode tests
within each group: sorted by component reference
```

**Output validation:**
The returned JSON is validated — every ID in `ordered_ids` must exist in the original test list. If the LLM hallucinates a new ID or drops an existing one, the fallback ordering is used instead.

---

### `fault_interpreter.py`

**What it does:**
After hardware execution, takes the list of failed `TestResult` objects and asks the LLM to explain what likely went wrong physically.

**What it sends to the LLM:**
For each failed test: test type, net names, component reference, measured value, expected threshold. The prompt includes basic board context (component count, board ID).

**Example input to LLM:**
```
Test tc_007 FAILED: isolation between GND and VCC
  Expected: resistance ≥ 1,000,000 Ω
  Measured: 47 Ω
  Location: near component U2
```

**Example output from LLM:**
```
"Likely solder bridge between GND and VCC pins of U2. 
At 47Ω, this is a near-direct short, consistent with excess solder 
bridging adjacent pads during reflow."
```

**What it does NOT do:**
- It does not change any pass/fail status — those are already set by the report generator
- It does not suggest repair actions (out of scope for v1)
- It does not claim certainty — prompts instruct it to use "likely", "possible", "consistent with"

---

## What this layer guarantees

- If the LLM is unavailable, the pipeline still runs to completion with deterministic fallbacks
- The LLM never sees raw coordinates — only net names and component references
- LLM output is always schema-validated before use
- No electrical truth (thresholds, pass/fail) is ever delegated to the LLM
