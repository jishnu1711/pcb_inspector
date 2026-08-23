"""Four-bar forward/inverse kinematics in the software joint convention."""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, degrees, hypot, radians, sin

from .geometry import ARM_1, ArmGeometry, Point


def _unit(angle_deg: float) -> Point:
    angle = radians(angle_deg)
    return (cos(angle), sin(angle))


def _add(first: Point, second: Point) -> Point:
    return (first[0] + second[0], first[1] + second[1])


def _scale(value: Point, scale: float) -> Point:
    return (value[0] * scale, value[1] * scale)


def normalize_degrees(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def angular_distance_deg(first: float, second: float) -> float:
    return abs(normalize_degrees(first - second))


@dataclass(frozen=True)
class JointAngles:
    shoulder_deg: float
    elbow_deg: float


@dataclass(frozen=True)
class ArmPose:
    A: Point
    E: Point
    W: Point
    P: Point
    Q: Point
    joints: JointAngles


@dataclass(frozen=True)
class IKSolution:
    joints: JointAngles
    branch: str
    pose: ArmPose


class IKError(ValueError):
    pass


def forward_kinematics(joints: JointAngles, geometry: ArmGeometry = ARM_1) -> ArmPose:
    """Return the machine-frame pose for software shoulder/elbow angles.

    The second software angle is inverted relative to the absolute forearm
    heading, matching the current proven mechanism convention.
    """
    shoulder = _unit(joints.shoulder_deg)
    rocker = _unit(-joints.elbow_deg)
    forearm = _unit(-joints.elbow_deg)
    local_a = (0.0, 0.0)
    local_e = _scale(shoulder, geometry.upper_arm_mm)
    local_p = _scale(rocker, -geometry.input_rocker_mm)
    local_q = _add(local_e, _scale(rocker, -geometry.output_rocker_mm))
    local_w = _add(local_e, _scale(forearm, geometry.forearm_mm))
    return ArmPose(
        A=geometry.local_to_machine(local_a),
        E=geometry.local_to_machine(local_e),
        W=geometry.local_to_machine(local_w),
        P=geometry.local_to_machine(local_p),
        Q=geometry.local_to_machine(local_q),
        joints=joints,
    )


def inverse_kinematics_all(target_machine: Point, geometry: ArmGeometry = ARM_1) -> tuple[IKSolution, IKSolution]:
    """Return both explicit two-link branches for a machine-frame target."""
    x, y = geometry.machine_to_local(target_machine)
    distance = hypot(x, y)
    first, second = geometry.upper_arm_mm, geometry.forearm_mm
    if distance > first + second + 1e-9 or distance < abs(first - second) - 1e-9:
        raise IKError(f"target {target_machine} is outside the {abs(first - second):.1f}-{first + second:.1f} mm workspace")
    cosine = max(-1.0, min(1.0, (distance * distance - first * first - second * second) / (2.0 * first * second)))
    target_heading = atan2(y, x)
    solutions: list[IKSolution] = []
    for branch, relative in (("elbow_down", -acos(cosine)), ("elbow_up", acos(cosine))):
        shoulder = target_heading - atan2(second * sin(relative), first + second * cos(relative))
        forearm = shoulder + relative
        joints = JointAngles(normalize_degrees(degrees(shoulder)), normalize_degrees(-degrees(forearm)))
        solutions.append(IKSolution(joints=joints, branch=branch, pose=forward_kinematics(joints, geometry)))
    return tuple(solutions)  # type: ignore[return-value]


def inverse_kinematics(
    target_machine: Point,
    geometry: ArmGeometry = ARM_1,
    current: JointAngles | None = None,
    branch: str | None = None,
) -> IKSolution:
    """Select an explicit branch, preferring continuity with ``current``."""
    candidates = inverse_kinematics_all(target_machine, geometry)
    if branch is not None:
        for candidate in candidates:
            if candidate.branch == branch:
                return candidate
        raise IKError(f"unknown IK branch {branch!r}")
    if current is None:
        return candidates[0]
    return min(
        candidates,
        key=lambda candidate: angular_distance_deg(candidate.joints.shoulder_deg, current.shoulder_deg)
        + angular_distance_deg(candidate.joints.elbow_deg, current.elbow_deg),
    )
