# Phase 3: Router Bridge Contract And Python Executor

## Goal

Define and prove the Linux Python-to-onboard-STM32 communication contract using
Arduino Router Bridge. Implement the Python RPC adapter and RPC-backed executor
without coupling it to unfinished motor hardware.

## Inputs

- Context: `docs/CONTEXT.md`.
- Router Bridge reference: `/home/jishnu/embedded/unoq/test_69`.
- Planned trajectory objects from Phase 2.
- Arduino Router Bridge documentation for supported argument types, return
  values, payload limits, timeouts, and safe callback behavior.

## Deliverables

- `shared/protocol.md` with a versioned, tested conceptual RPC contract.
- `python/device/rpc.py` as the only Python module importing `Bridge`.
- `python/device/executor.py` that replaces the serial executor boundary.
- A mock RPC transport for Python tests.
- A minimal Bridge proof that calls a status/capability handler on UNO Q.

## Required Research Before Encoding Payloads

Verify Router Bridge support for:

- integers, floats, booleans, strings, arrays, and structured return values;
- maximum request/response size;
- method error behavior and exception propagation;
- callback execution context and concurrency;
- request timeouts and behavior when Linux or firmware restarts.

Do not assume that arbitrary JSON-like objects or a whole trajectory fit in one
RPC call.

## Conceptual Contract

The final encoding may change after research, but semantics are fixed:

```text
get_capabilities() -> protocol version, axis/probe/measurement capabilities
get_status() -> state, position, active trajectory, fault details
home() -> accepted/completed/error state
stop() -> accepted/completed/error state
clear_fault() -> accepted/error state

trajectory_begin(trajectory metadata)
trajectory_point(one point or one bounded chunk)
trajectory_commit()
trajectory_start()
trajectory_clear()

probe_set(probe identifier, requested state)
measure(logical mode) -> value, unit, diagnostics
```

Every response must communicate success/failure, a stable error code, and a
human-readable message. Long-running motion must be non-blocking: start is
acknowledged first, then Python polls `get_status()`.

## Implementation Steps

1. Record Router Bridge findings in `shared/protocol.md` before committing to
   method signatures.
2. Define capability/version negotiation so Python rejects unsupported firmware
   safely.
3. Implement a transport wrapper with one method per conceptual RPC operation;
   no other Python module may call `Bridge.call` directly.
4. Implement trajectory upload with bounded chunks or points based on proven
   bridge limits. Add unique trajectory identifiers and expected sample count.
5. Implement the RPC executor that uploads, commits, starts, polls, stops on
   cancellation/fault, and translates replies into executor results.
6. Provide a fake transport to test normal completion, invalid trajectory,
   timeout, fault, restart, and cancellation without UNO Q hardware.
7. Adapt the test_69 sketch only enough to prove the chosen basic types and
   status semantics before firmware motion work begins.

## Out Of Scope

- Real STM32 trajectory execution.
- Final probe/measurement electronics.
- Direct UART, shell commands, or PySerial.

## Verification

- No Python module except `python/device/rpc.py` imports `Bridge`.
- Protocol behavior is covered by fake-transport tests.
- A basic UNO Q Bridge round trip succeeds using matching RPC names.
- The executor never treats an acknowledgement as motion completion.

## Handoff

Phase 4 implements matching STM32 handlers and trajectory state semantics.
