"""Structural trajectory and per-arm kinematic validation."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from .calibration import ArmCalibration
from .geometry import ArmGeometry, Point
from .kinematics import ArmPose, JointAngles, angular_distance_deg, forward_kinematics
from .trajectory import DualJointState, TrajectoryOperation

# Top-view capsule model carried over from the four-bar prototype: 23 mm link
# width plus 5 mm clearance, compared against link centreline distances.
LINK_WIDTH_MM = 23.0
SELF_COLLISION_CLEARANCE_MM = 5.0
SELF_COLLISION_THRESHOLD_MM = LINK_WIDTH_MM + SELF_COLLISION_CLEARANCE_MM


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    sample_index: int | None = None


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    """Return True when two closed 2D segments touch or cross."""
    eps = 1e-9
    o1, o2 = _orientation(a0, a1, b0), _orientation(a0, a1, b1)
    o3, o4 = _orientation(b0, b1, a0), _orientation(b0, b1, a1)
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and (
        (o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)
    ):
        return True

    def on_segment(start: Point, point: Point, end: Point) -> bool:
        return (
            min(start[0], end[0]) - eps <= point[0] <= max(start[0], end[0]) + eps
            and min(start[1], end[1]) - eps <= point[1] <= max(start[1], end[1]) + eps
        )

    for orientation, point, start, end in (
        (o1, b0, a0, a1), (o2, b1, a0, a1), (o3, a0, b0, b1), (o4, a1, b0, b1)
    ):
        if abs(orientation) <= eps and on_segment(start, point, end):
            return True
    return False


def segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    """Minimum Euclidean distance between two closed 2D segments."""
    if segments_intersect(a0, a1, b0, b1):
        return 0.0
    return min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )


def arm_links(pose: ArmPose) -> tuple[tuple[str, Point, Point], ...]:
    """Named centrelines of every physical link, for clearance checks and drawing."""
    return (
        ("upper_arm_AE", pose.A, pose.E),
        ("forearm_EW", pose.E, pose.W),
        ("input_rocker_AP", pose.A, pose.P),
        ("coupler_PQ", pose.P, pose.Q),
        ("output_rocker_EQ", pose.E, pose.Q),
    )


def self_collision_free(pose: ArmPose, clearance_mm: float = SELF_COLLISION_THRESHOLD_MM) -> bool:
    """Apply the ported A-E versus P-Q rule; equal to 50*|sin(J0+J1)| >= clearance."""
    return segment_distance(pose.A, pose.E, pose.P, pose.Q) >= clearance_mm


def inter_arm_clearance(
    state: DualJointState, geometries: dict[str, ArmGeometry]
) -> tuple[float, str]:
    """Smallest centreline gap between any arm-1 link and any arm-2 link.

    Advisory only. Inter-arm collision is out of scope for the current planner,
    so this is reported for inspection rather than enforced.
    """
    pose1 = forward_kinematics(state.arm1, geometries["arm1"])
    pose2 = forward_kinematics(state.arm2, geometries["arm2"])
    worst, pair = float("inf"), ""
    for name1, start1, end1 in arm_links(pose1):
        for name2, start2, end2 in arm_links(pose2):
            distance = segment_distance(start1, end1, start2, end2)
            if distance < worst:
                worst, pair = distance, f"arm1.{name1} <-> arm2.{name2}"
    return worst, pair


def _point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > point[1]) != (y2 > point[1]):
            crossing = x1 + (point[1] - y1) * (x2 - x1) / (y2 - y1)
            if point[0] < crossing:
                inside = not inside
    return inside


def links_over_board(pose: ArmPose, board_corners: tuple[Point, ...]) -> tuple[str, ...]:
    """Names of links whose centreline enters the board outline in the top view."""
    if not board_corners:
        return ()
    intruding: list[str] = []
    count = len(board_corners)
    for name, start, end in arm_links(pose):
        if _point_in_polygon(start, board_corners) or _point_in_polygon(end, board_corners):
            intruding.append(name)
            continue
        for index in range(count):
            edge_start, edge_end = board_corners[index], board_corners[(index + 1) % count]
            if segments_intersect(start, end, edge_start, edge_end):
                intruding.append(name)
                break
    return tuple(intruding)


def validate_arm_state(joints: JointAngles, geometry: ArmGeometry, calibration: ArmCalibration) -> ValidationError | None:
    values = (joints.shoulder_deg, joints.elbow_deg)
    if not all(isfinite(value) for value in values):
        return ValidationError("non_finite", "joint value is not finite")
    # The elbow limit is a limit on the rocker the motor drives, so it couples
    # both joint coordinates rather than bounding the elbow angle on its own.
    offending = calibration.within_limits(joints, geometry)
    if offending == "shoulder":
        return ValidationError("shoulder_limit", "shoulder joint violates configured motor limits")
    if offending == "elbow":
        return ValidationError("elbow_limit", "elbow motor violates configured motor limits")
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
    if operation.samples[0].state != operation.source:
        errors.append(ValidationError("initial_state", "first sample does not equal operation source", 0))
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
