# Phase 1: Inspector Port And Local Dry Run

## Goal

Create the Arduino App Lab Python application skeleton and reuse the existing
inspection pipeline without changing its electrical semantics. Deliver a local
dry run from KiCad inputs to report output, with no Router Bridge, motor, or
server dependency.

## Inputs

- Context: `docs/CONTEXT.md`.
- Source pipeline: `/home/jishnu/embedded/cup_mukhyam/pcb-probe-inspector`.
- Existing fixture boards/tests from that source repository.

## Deliverables

- `app.yaml` and `python/main.py` for an App Lab-compatible project.
- `python/inspector/` containing the reused parser, model, generator, planner,
  and report code as importable modules.
- `python/device/app.py`, `job_runner.py`, `executor.py`, `storage.py`, and
  `config.py` with a local-only lifecycle.
- A `DryRunExecutor` that records planned operations and returns deterministic
  mock measurements.
- Local JSON job manifest, generated plan, execution trace, and report output.
- Tests proving the dry run works against a representative KiCad board.

## Implementation Steps

1. Create the App Lab Python package layout and configure imports so the
   inspector modules do not rely on their original repository location.
2. Copy or move only implemented inspector modules; exclude empty `api.py`,
   empty schemas, and `executor/serial_executor.py`.
3. Preserve existing thresholds, data models, test generation, report behavior,
   and deterministic LLM fallback. Do not introduce Gemini work in this phase.
4. Define a small local job input model: PCB path, schematic path, output
   directory, and dry-run configuration.
5. Implement a job runner that produces a logical `TestPattern`, then delegates
   each test to an executor interface.
6. Implement `DryRunExecutor` as the initial executor. It must capture logical
   test operations and return deterministic result values without hardware.
7. Persist a manifest sufficient to reproduce the run: input hashes, app
   version, configuration, logical plan, dry-run trace, and report paths.
8. Add tests for parsing-to-plan-to-report and failed/LLM-fallback cases.

## Out Of Scope

- Motion planning implementation.
- Router Bridge or STM32 firmware.
- Server communication.
- Gemini changes.
- Physical measurement behavior.

## Verification

- Python import and syntax checks pass in the App Lab Python environment.
- Existing parser/model/generator tests pass after relocation.
- A fixture board produces a stable plan and report with no hardware attached.
- A rerun with identical input/configuration produces the same logical tests.

## Handoff

Phase 2 replaces the dry-run operation trace with motion-planner requests.
Phase 3 later replaces `DryRunExecutor` with an RPC-backed executor.
