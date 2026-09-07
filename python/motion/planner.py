"""Sequential, fixed-dt dual-arm Cartesian trajectory planner."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from .calibration import ArmCalibration, default_calibrations
from .geometry import DEFAULT_LAYOUT, ArmGeometry, FixtureTransform, MachineLayout, Point
from .kinematics import (
    IKError,
    IKSolution,
    branch_of,
    forward_kinematics,
    inverse_kinematics,
    inverse_kinematics_all,
)
from .profile import make_profile
from .trajectory import DualJointState, MotionPlan, TrajectoryOperation, TrajectorySample
from .validation import validate_arm_state, validate_operation


@dataclass(frozen=True)
class PlannerConfig:
    dt_s: float = 0.05
    max_speed_mm_s: float = 30.0
    max_acceleration_mm_s2: float = 80.0

    def __post_init__(self) -> None:
        if self.dt_s <= 0 or self.max_speed_mm_s <= 0 or self.max_acceleration_mm_s2 <= 0:
            raise ValueError("planner timing and motion limits must be positive")


class PlanningError(ValueError):
    pass


class DualArmPlanner:
    """Plan arm 1 then arm 2, holding the non-moving arm at every sample."""

    def __init__(
        self,
        fixture: FixtureTransform = FixtureTransform(),
        config: PlannerConfig = PlannerConfig(),
        geometries: dict[str, ArmGeometry] | None = None,
        calibrations: dict[str, ArmCalibration] | None = None,
        layout: MachineLayout = DEFAULT_LAYOUT,
    ) -> None:
        self.fixture = fixture
        self.config = config
        self.layout = layout
        self.geometries = geometries or layout.arms()
        self.calibrations = calibrations or default_calibrations()

    def plan_probe_pair(
        self,
        arm1_pcb_target: Point,
        arm2_pcb_target: Point,
        current: DualJointState,
    ) -> MotionPlan:
        """Register two PCB targets and return arm-1 then arm-2 operations."""
        targets = {
            "arm1": self.fixture.pcb_to_machine(arm1_pcb_target),
            "arm2": self.fixture.pcb_to_machine(arm2_pcb_target),
        }
        first = self._plan_arm_move("arm1", targets["arm1"], current)
        second = self._plan_arm_move("arm2", targets["arm2"], first.target)
        trace = (
            self._trace(first),
            self._trace(second),
        )
        return MotionPlan(source=current, target=second.target, operations=(first, second), dry_run_trace=trace)

    def _choose_target_solution(self, arm_id: str, target: Point, current_branch: str) -> IKSolution:
        """Return the target solution on the branch the arm is physically on.

        Continuity is measured against ``current_branch``, not against whichever
        solution happens to be numerically nearest, so a rejected move can never
        become a silent branch flip. This phase has no safe reconfiguration
        policy, so a required branch change is an error rather than a jump.
        """
        try:
            candidates = inverse_kinematics_all(target, self.geometries[arm_id])
        except IKError as error:
            raise PlanningError(f"{arm_id}: {error}") from error
        valid = [
            candidate
            for candidate in candidates
            if validate_arm_state(candidate.joints, self.geometries[arm_id], self.calibrations[arm_id]) is None
        ]
        if not valid:
            raise PlanningError(f"{arm_id}: target {target} has no branch within limits and self-collision clearance")
        matching = [candidate for candidate in valid if candidate.branch == current_branch]
        if matching:
            return matching[0]
        raise PlanningError(
            f"{arm_id}: target {target} is only reachable on branch {valid[0].branch}, "
            f"but the arm is on {current_branch}; branch changes are not planned in this phase"
        )

    def _plan_arm_move(self, arm_id: str, target: Point, source: DualJointState) -> TrajectoryOperation:
        geometry = self.geometries[arm_id]
        start_joints = source.for_arm(arm_id)
        start_failure = validate_arm_state(start_joints, geometry, self.calibrations[arm_id])
        if start_failure:
            raise PlanningError(f"{arm_id}: source state invalid: {start_failure.message}")
        branch = branch_of(start_joints)
        target_solution = self._choose_target_solution(arm_id, target, branch)
        start_tip = forward_kinematics(start_joints, geometry).W
        distance = hypot(target[0] - start_tip[0], target[1] - start_tip[1])
        if distance == 0.0:
            # Already on target: hold the measured state instead of re-solving it.
            return self._finish(arm_id, source, source, target, (TrajectorySample(0.0, source, arm_id, target),))
        profile = make_profile(distance, self.config.max_speed_mm_s, self.config.max_acceleration_mm_s2)
        # Sample 0 is the measured source state itself rather than a re-solve of
        # the start tip, so the trajectory always begins where the arm already is.
        samples: list[TrajectorySample] = [TrajectorySample(0.0, source, arm_id, target)]
        for index, travelled in enumerate(profile.samples(self.config.dt_s)):
            if index == 0:
                continue
            ratio = 0.0 if distance == 0 else travelled / distance
            waypoint = (start_tip[0] + (target[0] - start_tip[0]) * ratio, start_tip[1] + (target[1] - start_tip[1]) * ratio)
            try:
                solution = inverse_kinematics(waypoint, geometry, start_joints, branch=branch)
            except IKError as error:
                raise PlanningError(f"{arm_id}: path sample {index} is unreachable: {error}") from error
            state = source.replace_arm(arm_id, solution.joints)
            samples.append(TrajectorySample(index * self.config.dt_s, state, arm_id, target))
        target_state = source.replace_arm(arm_id, target_solution.joints)
        # The profile's final coordinate is exact, but assigning the selected
        # target state also guarantees stable branch and round-trip metadata.
        final_sample = samples[-1]
        samples[-1] = TrajectorySample(final_sample.time_s, target_state, arm_id, target)
        return self._finish(arm_id, source, target_state, target, tuple(samples))

    def _finish(
        self,
        arm_id: str,
        source: DualJointState,
        target_state: DualJointState,
        target: Point,
        samples: tuple[TrajectorySample, ...],
    ) -> TrajectoryOperation:
        operation = TrajectoryOperation(
            name=f"move_{arm_id}", moving_arm=arm_id, source=source, target=target_state,
            requested_machine_target=target, dt_s=self.config.dt_s, samples=samples,
        )
        errors = validate_operation(operation, self.geometries, self.calibrations)
        if errors:
            first = errors[0]
            location = "" if first.sample_index is None else f" at sample {first.sample_index}"
            raise PlanningError(f"{arm_id}: trajectory validation failed{location}: {first.message}")
        return operation

    @staticmethod
    def _trace(operation: TrajectoryOperation) -> str:
        target = operation.requested_machine_target
        return (
            f"{operation.name}: hold {'arm2' if operation.moving_arm == 'arm1' else 'arm1'}; "
            f"move {operation.moving_arm} to ({target[0]:.3f}, {target[1]:.3f}) mm "
            f"in {len(operation.samples)} samples at dt={operation.dt_s:.3f}s"
        )
