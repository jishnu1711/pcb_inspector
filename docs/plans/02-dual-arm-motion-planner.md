# Phase 2: Dual-Arm Motion Planner

## Goal

Create a pure Python, hardware-independent planner that turns two logical PCB
probe coordinates into sequential, fixed-dt four-axis joint trajectories. It
must be testable without UNO Q hardware or Router Bridge.

## Inputs

- Context: `docs/CONTEXT.md`.
- Existing kinematics: `/home/jishnu/embedded/four+bar/fourbar_leg_sim.py`,
  `/home/jishnu/embedded/four+bar/fourbar_leg_ik.py`, and
  `/home/jishnu/embedded/four+bar/dual_fourbar_arm_sim.py`.

## Deliverables

- `python/motion/geometry.py` as the authoritative geometry/frame definition.
- `kinematics.py` for FK/IK and explicit branch selection.
- `calibration.py` for software-to-hardware joint mapping, offsets, signs,
  limits, and steps-per-degree configuration.
- `planner.py`, `profile.py`, `trajectory.py`, and `validation.py`.
- Unit tests and golden FK/IK vectors.
- A dry-run trace showing the planned sequential arm movements for each test.
- A headless simulator and optional Matplotlib trajectory-replay viewer that use
  the same `python/motion/` APIs as the production planner.

## Required Design Rules

- Use `60/50/60/50/82.5 mm` geometry.
- Use arm bases `(-120, 0)` and `(120, 0)`; arm 2 faces inward with no assembly
  reflection.
- Treat all coordinates as millimetres and all model angles as degrees.
- Apply PCB fixture registration before inverse kinematics.
- Plan arm movement sequentially. A stationary arm remains at its configured
  safe/hold pose while the other moves.
- Validate reachability, configured joint limits, branch continuity, and the
  existing per-arm 2D self-collision rule.
- Do not claim inter-arm collision safety, 3D collision safety, or contact/Z
  safety in this phase.

## Implementation Steps

1. Extract the current simulator geometry and transforms into a deterministic,
   UI-free package. Correct arm 2 to the approved base/orientation.
2. Separate kinematic mathematics from hardware calibration. FK/IK must operate
   in a software joint convention; mapping to motor direction/offset belongs in
   `calibration.py`.
3. Preserve both valid IK branches and select a branch consistently from the
   current joint state. Reject branch changes unless an explicit safe policy
   permits them.
4. Define the rigid fixture transform from PCB coordinates to machine XY.
5. Define trajectory objects containing sample period, four joint coordinates,
   source/target state, and operation metadata.
6. Implement straight Cartesian travel and conservative trapezoidal or
   triangular scalar profiles. Sample at fixed `dt` and run IK for every sample.
7. Emit sequential operations: arm 1 move/hold, arm 2 move/hold, and later
   abstract contact/measurement hooks. Do not invent Z mechanics.
8. Add structural validation for trajectory continuity, bounds, and output
   finiteness. Real speed/acceleration values remain configuration.
9. Build test vectors for reachable/unreachable targets, limits, branch choice,
   self-collision rejection, fixture transforms, and arm 2 inward orientation.
10. Add a headless simulator that replays every sampled joint point through FK,
    records arm geometry, tool-tip positions, validation results, and final
    error from the requested machine target.
11. Add an optional Matplotlib viewer, equivalent in purpose to the existing
    `four+bar` visualizer, that animates a saved trajectory with link geometry,
    fixture/PCB outline, requested probe points, tool-tip trace, limits, and
    validation failures. It must consume saved trajectory data and must not
    contain a second implementation of FK, IK, or planning.

## Out Of Scope

- STM32 pulse timing or trajectory transport.
- Inter-arm collision checks.
- Homing or physical calibration.
- Probe lowering/contact and measurement hardware.

## Verification

- FK/IK round trips meet a documented positional tolerance.
- Every sampled point passes software validation before it is returned.
- The same input state and target generate the same trajectory.
- The planner produces a human-readable dry-run trace usable by Phase 1.
- The headless simulator confirms each replayed tool tip reaches its requested
  machine target within a documented tolerance.
- The visual replay shows every sample of each sequential arm move and flags
  reachability, limit, or internal self-collision rejection.

## Handoff

Phase 3 maps trajectory objects to the Router Bridge contract. Phase 4 consumes
the resulting joint-space samples on the STM32.
