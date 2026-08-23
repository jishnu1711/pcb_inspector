# Phase 4: STM32 Motion, DRV8825, And Safety Firmware

## Goal

Implement the UNO Q STM32 firmware that receives joint-space trajectories over
Router Bridge, independently validates them, and executes safe deterministic
four-axis STEP/DIR motion.

## Inputs

- Context: `docs/CONTEXT.md`.
- Protocol: `shared/protocol.md` from Phase 3.
- Motion concepts from `/home/jishnu/embedded/zephyr/apps/tmc2225`.
- Python-produced trajectory semantics from Phase 2.

## Deliverables

- UNO Q App Lab `sketch/` build configuration using `Arduino_RouterBridge`.
- Four-axis DRV8825-oriented `stepper_axis` layer.
- Buffered trajectory state machine and deterministic timer-driven executor.
- RPC handlers for capability/status/trajectory/stop/fault lifecycle.
- Explicit hardware initialization and safe-disabled startup behavior.
- Build and non-hardware validation instructions.

## Firmware Rules

- Do not port the ESP32-C3 target, USB serial shell, or direct PySerial protocol.
- Do not port the busy-wait motion loop as the final executor.
- Do not run FK/IK or Cartesian planning on STM32.
- Router Bridge callbacks must enqueue/request work; lengthy motion execution
  must occur outside the callback.
- Firmware position is authoritative only after valid homing/commissioning.
- While running, allow only status and stop-related requests.

## Trajectory State Model

```text
EMPTY -> LOADING -> READY -> RUNNING -> COMPLETE
                  |         |
                  v         v
               INVALID    ABORTED
                     \     /
                      FAULT
```

`clear` returns non-running states to `EMPTY` while retaining actual motor
position. Aborted plans are never resumed; Python reads status and replans.

## Implementation Steps

1. Establish UNO Q STM32 build/flash workflow and create `sketch.ino`,
   `sketch.yaml`, and module skeletons.
2. Define compile-time pin/configuration interfaces for four DRV8825 axes:
   STEP, DIR, ENABLE, endstop/fault inputs, invert flags, and step conversion.
   Do not invent final pin numbers; safe stubs are acceptable until wiring is
   known.
3. Adapt only the generic low-level ideas from the prior prototype: axis state,
   step counters, coordinated stepping, and degree-to-step conversion.
4. Add explicit GPIO initialization checks, driver-disable startup state,
   direction setup/hold timing, step high/low timing, and counter overflow
   protection.
5. Implement trajectory upload buffering and validation: count, sample period,
   bounds, position continuity, speed, acceleration, capacity, and active-fault
   checks.
6. Implement timer-driven coordinated stepping such that every axis reaches its
   sampled target at the segment boundary.
7. Implement `stop`, endstop/fault handling, fault latching, driver disable,
   `clear_fault`, and structured status.
8. Add mock probe/measurement handlers only after the motion/safety lifecycle
   is stable.
9. Compile for UNO Q and test state transitions using safe outputs or no motors
   before connecting real mechanics.

## Out Of Scope

- Final pin map and wiring until supplied.
- Physical Z/contact implementation.
- ADC/relay measurement electronics.
- Inter-arm collision detection; Python currently sequences arms only.

## Verification

- The sketch compiles for the UNO Q Zephyr target.
- Invalid uploads never pulse motors.
- Stop/fault transitions disable motion and preserve reported step counters.
- A simulated/simple trajectory reaches the expected four-axis counters within
  a documented tolerance.
- No normal command can start concurrent pulse production while running.

## Handoff

Phase 5 connects actual driver/probe/measurement hardware. Phase 6 validates
the complete Python-to-STM32 run.
