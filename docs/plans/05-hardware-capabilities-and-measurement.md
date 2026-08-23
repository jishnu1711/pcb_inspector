# Phase 5: Hardware Capabilities, Probes, And Measurement

## Goal

Replace the mock hardware capability layer with the actual DRV8825, endstop,
probe, and measurement design without leaking mechanical assumptions into the
KiCad inspection pipeline.

## Prerequisites

- Phase 4 firmware trajectory and safety lifecycle is functioning.
- Actual UNO Q pin map, DRV8825 wiring, motor/gear data, and safety inputs are
  available.
- Probe/Z mechanism and measurement frontend are designed.

## Decisions Required Before Implementation

- STEP/DIR/ENABLE, endstop, fault, E-stop, power-enable, and probe GPIO wiring.
- Motor steps/revolution, microstepping, gearing, maximum current, and thermal
  requirements for each axis.
- Homing direction, switch logic, zero offsets, physical joint limits, and
  commissioning procedure.
- Probe actuator type, safe retracted state, contact method, and failure mode.
- Measurement stimulus, relay/mux topology, protection, ADC/reference/range,
  settling, calibration, and powered-board policy.

## Deliverables

- Versioned machine capability/configuration record.
- Commissioned calibration record: directions, zeros, limits, steps-per-degree,
  conservative speed/acceleration limits, and calibration date.
- Real homing and interlock behavior.
- Probe actuator RPC behavior and safe default state.
- Measurement response with calibrated value, unit, diagnostics, and error
  codes.
- Hardware test/commissioning procedure.

## Implementation Steps

1. Add final pin mapping and electrical initialization to `hardware/pins.h` and
   hardware modules. Keep drivers disabled until firmware reports a healthy,
   homed state.
2. Implement manual-jog/homing commissioning to replace provisional simulator
   joint conventions with measured signs, offsets, and limits.
3. Store commissioned values in Python device configuration and STM32 firmware
   configuration; reject a mismatch during capability negotiation.
4. Implement probe control with a safe retracted default and explicit failure
   response. Keep planar positioning separate from future Z/contact policy.
5. Implement measurement modes incrementally, beginning with mock-compatible
   continuity behavior and then calibrated real acquisition.
6. Add electrical protection and safe handling for open leads, shorts, charged
   capacitors, and externally powered boards before permitting general testing.
7. Attach calibration/configuration versions to every result.

## Out Of Scope

- Server workflow.
- Gemini/provider work.
- Full 3D/inter-arm collision modeling unless hardware geometry is supplied.

## Verification

- Homing and limits stop motion deterministically.
- Driver disable and E-stop produce the specified safe state.
- Commissioned joint mapping reproduces known tip positions.
- Known open/short/resistor/diode standards validate measurement accuracy.
- Probe behavior fails safe on controller, bridge, or power loss.
