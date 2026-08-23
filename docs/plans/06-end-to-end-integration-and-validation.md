# Phase 6: End-To-End Integration And Validation

## Goal

Integrate the completed Python inspector, motion planner, Router Bridge executor,
STM32 firmware, and available hardware into a reproducible local PCB inspection
workflow.

## Prerequisites

- Phases 1 through 4 complete for a software/motion/RPC dry run.
- Phase 5 complete for any claim of real probing or measurement.

## Deliverables

- Local command flow for a KiCad PCB/schematic pair.
- Durable run manifest, logical test plan, trajectory trace, STM32 status log,
  raw measurements, and final JSON/Markdown report.
- A fixture-board validation suite and documented acceptance criteria.
- Failure/restart/cancellation recovery behavior.

## Implementation Steps

1. Connect `job_runner.py` to the motion planner and RPC executor while keeping
   the dry-run executor selectable.
2. For each logical test, transform both probe points through fixture
   registration, generate sequential arm trajectories, upload/execute them,
   and request measurement.
3. Persist every state transition and associate generated trajectories with test
   case IDs for auditability.
4. Implement recovery behavior for Python restart, bridge loss, STM32 fault,
   cancelled jobs, and incomplete results. Never resume an aborted trajectory.
5. Validate with representative KiCad fixture boards and known electrical
   standards. Start with a single manually reviewed continuity test, then expand
   to generated test patterns.
6. Record limitations prominently: planar-only approach, no inter-arm collision
   validation, and any unfinished contact/measurement protections.

## Acceptance Criteria

- Dry run completes reproducibly with no UNO Q hardware attached.
- The UNO Q path reports capability/version compatibility before execution.
- Firmware rejects invalid trajectories independently of Python validation.
- Stop, fault, and restart preserve an auditable result instead of silently
  continuing.
- Every reported pass/fail remains deterministic and based on measured values,
  not LLM output.

## Deferred After This Phase

- Server job scheduling and fleet management.
- Gemini provider migration.
- 3D/inter-arm collision model and Z/contact motion planning.
