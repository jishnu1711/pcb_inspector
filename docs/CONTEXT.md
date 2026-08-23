# UNO Q PCB Inspector Context

## Purpose

This repository will become the Arduino App Lab application for a two-probe PCB
inspector running on an Arduino UNO Q. This document is the source of truth for
the approved application boundary and the existing work to reuse. The phase
plans in `docs/plans/` are intentionally independent enough to be implemented
in separate chats.

## Existing Implementation Sources

| Stack | Path | Reuse status |
|---|---|---|
| PCB inspection prototype | `/home/jishnu/embedded/cup_mukhyam/pcb-probe-inspector` | Reuse the Python parsing, electrical model, probe selection, test generation, reports, and deterministic LLM fallbacks. Do not reuse the empty serial executor or placeholder schemas/API. |
| UNO Q Router Bridge proof | `/home/jishnu/embedded/unoq/test_69` | Reuse the Arduino App Lab project shape and `Bridge.call(...)` / `Bridge.provide_safe(...)` integration pattern. It is not a trajectory protocol. |
| Zephyr motor prototype | `/home/jishnu/embedded/zephyr/apps/tmc2225` | Reuse STEP/DIR concepts, software step accounting, and coordinated stepping ideas only. It targets ESP32-C3 and a serial shell, so its target, transport, timing, and safety design are not reusable as-is. |
| Four-bar planner/simulator | `/home/jishnu/embedded/four+bar` | Reuse current geometry plus Python FK/IK and internal static self-collision concepts after refactoring. It is a 2D prototype, not a safe trajectory planner or hardware implementation. |
| Four-bar hardware plan | `/home/jishnu/embedded/four+bar/.kilo/plans/1782157852252-fourbar-hardware-kinematics-plan.md` | Historical hardware/kinematics reference. Where it conflicts with the approved decisions below, this document wins. |

## Approved App Lab Layout

```text
mark1/
├── app.yaml
├── python/
│   ├── main.py
│   ├── requirements.txt
│   ├── inspector/
│   ├── motion/
│   └── device/
├── sketch/
│   ├── sketch.ino
│   ├── sketch.yaml
│   └── src/
│       ├── rpc/
│       ├── motion/
│       ├── hardware/
│       └── safety/
├── shared/
│   └── protocol.md
└── docs/
    └── plans/
```

`sketch/src/` is used for firmware modules because Arduino sketch builds
reliably compile the sketch and its `src` tree. Firmware implementation files
must not be placed in arbitrary sketch subdirectories.

## Responsibility Split

### Linux Python application

- Parse KiCad files and generate logical electrical test cases.
- Build the fixture-based PCB-to-machine transform.
- Perform four-bar FK/IK, branch selection, Cartesian path planning, trajectory
  profiling, sampling, and sequential dual-arm planning.
- Orchestrate a test run, interpret deterministic pass/fail results, persist
  local state, and later communicate with the server.
- Use `Bridge.call(...)` only through `python/device/rpc.py`.

### Onboard UNO Q STM32 firmware

- Expose Router Bridge handlers with `Bridge.provide_safe(...)`.
- Control four DRV8825-style axes: arm 1 J0/J1 and arm 2 J0/J1.
- Validate and execute preplanned joint-space trajectories using deterministic
  timing.
- Own endstops, driver faults, stop/fault latching, driver disable, and final
  physical safety checks.
- Later control probe actuation and measurement hardware.

The STM32 must not parse KiCad, call an LLM, perform FK/IK, register the board,
or create Cartesian trajectories. Python must not produce motor pulses or be
the sole safety authority.

## Approved Mechanical And Planning Assumptions

- There are two planar four-bar arms and one electrical probe per arm.
- Use the current simulator geometry in millimetres: `A-E=60`, `A-P=50`,
  `P-Q=60`, `E-Q=50`, `E-W=82.5`.
- Arm 1 base is `(-120, 0)`. Arm 2 base is `(120, 0)`, faces inward, and has no
  assembly reflection.
- The fixture supplies the PCB origin and orientation in machine XY; the initial
  registration transform is rigid translation plus rotation.
- Planning initially covers planar tool-tip positioning only. Z retraction,
  contact, force sensing, and measurement hardware are not yet designed.
- Arms move sequentially. Inter-arm collision validation is intentionally out
  of the first planner scope.
- Existing simulator joint signs/ranges are provisional commissioning values.
  Real hardware must later confirm zeros, signs, offsets, and limits.
- Conservative motion limits are acceptable initially; measured limits replace
  them during commissioning.

## Explicitly Deferred Items

- Gemini provider/API changes.
- Server assignment, job download, result upload, and fleet operations.
- Z/probe mechanism, contact detection, measurement frontend, relays, ADC,
  calibration, and powered-board policy.
- Real inter-arm, fixture, PCB, probe, and 3D collision geometry.
- Exact UNO Q STM32 pin map, DRV8825 wiring, endstops, E-stop, and driver fault
  hardware.
- Router Bridge payload limits and structured-return support. These must be
  verified from Arduino documentation before final protocol encoding.

## Initial Execution Sequence

```text
KiCad files
  -> inspector TestPattern
  -> fixture registration
  -> sequential arm targets and sampled joint trajectories
  -> Router Bridge trajectory commands
  -> STM32 validates and executes four-axis movement
  -> probe/measurement operation
  -> deterministic TestResult and report
```

The initial end-to-end milestone is a local dry run: parsing, test generation,
fixture transform, motion planning, simulated execution, mock measurement, and
reporting. It has no server dependency and does not drive motors.
