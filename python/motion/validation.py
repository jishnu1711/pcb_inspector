"""Structural trajectory and per-arm kinematic validation."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from .calibration import ArmCalibration
from .geometry import ArmGeometry, Point
from .kinematics import ArmPose, JointAngles, angular_distance_deg, forward_kinematics
from .trajectory import TrajectoryOperation


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    sample_index: int | None = None


def _segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    def point_segment(point: Point, start: Point, end: Point) -> float:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return hypot(point[0] - start[0], point[1] - start[1])
        t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
        return hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)

    # The existing rule uses the A-E and P-Q capsule centerlines. Detecting a
    # crossing is sufficient because these equal-length links otherwise have
    # their minimum at an endpoint projection.
    return min(point_segment(a, c, d), point_segment(b, c, d), point_segment(c, a, b), point_segment(d, a, b))


def self_collision_free(pose: ArmPose, clearance_mm: float = 28.0) -> bool:
    return _segment_distance(pose.A, pose.E, pose.P, pose.Q) >= clearance_mm


def validate_arm_state(joints: JointAngles, geometry: ArmGeometry, calibration: ArmCalibration) -> ValidationError | None:
    values = (joints.shoulder_deg, joints.elbow_deg)
    if not all(isfinite(value) for value in values):
        return ValidationError("non_finite", "joint value is not finite")
    if not calibration.shoulder.contains_software_angle(joints.shoulder_deg):
        return ValidationError("shoulder_limit", "shoulder joint violates configured motor limits")
    if not calibration.elbow.contains_software_angle(joints.elbow_deg):
        return ValidationError("elbow_limit", "elbow joint violates configured motor limits")
    if not self_collision_free(forward_kinematics(joints, geometry)):
        return ValidationError("self_collision", "A-E and P-Q violate the configured 2D clearance")
    return None


def validate_operation(
    operation: TrajectoryOperation,
    geometries: dict[str, ArmGeometry],
    calibrations: dict[str, ArmCalibration],
) -> tuple[ValidationError, ...]:
    errors: list[ValidationError] = []
    if not operation.samples:
        errors.append(ValidationError("empty", "operation contains no samples"))
        return tuple(errors)
    previous = operation.source
    stationary_arm = "arm2" if operation.moving_arm == "arm1" else "arm1"
    for index, sample in enumerate(operation.samples):
        if abs(sample.time_s - index * operation.dt_s) > 1e-9:
            errors.append(ValidationError("sample_period", "sample time is not fixed dt", index))
        if sample.state.for_arm(stationary_arm) != operation.source.for_arm(stationary_arm):
            errors.append(ValidationError("stationary_arm", "stationary arm changed during sequential operation", index))
        for arm_id in ("arm1", "arm2"):
            failure = validate_arm_state(sample.state.for_arm(arm_id), geometries[arm_id], calibrations[arm_id])
            if failure:
                errors.append(ValidationError(failure.code, f"{arm_id}: {failure.message}", index))
        moved_before, moved_now = previous.for_arm(operation.moving_arm), sample.state.for_arm(operation.moving_arm)
        if angular_distance_deg(moved_before.shoulder_deg, moved_now.shoulder_deg) > 90 or angular_distance_deg(moved_before.elbow_deg, moved_now.elbow_deg) > 90:
            errors.append(ValidationError("joint_discontinuity", "adjacent samples exceed 90 degrees", index))
        previous = sample.state
    if operation.samples[-1].state != operation.target:
        errors.append(ValidationError("final_state", "last sample does not equal operation target"))
    return tuple(errors)
