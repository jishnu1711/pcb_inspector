"""Serializable fixed-period, four-axis motion trajectory records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geometry import Point
from .kinematics import JointAngles


# Configured safe/hold poses.
#
# Shoulder 0 is the inward horizontal for both arms, so parking at J0 = 0 lays
# each upper arm A-E flat along the base line, pointing at the machine origin.
# That makes the pose the natural commissioning datum: the home position is the
# one you can set by eye or against a hard stop, with both base links collinear
# with the two shoulder pivots. Arm 1's elbow E lands on (-60, 0) and arm 2's on
# (+60, 0), both exactly on the base line.
#
# The arms are one identical build parked at identical joint angles, so their
# poses are in point symmetry about the machine origin: arm 2 is arm 1 rotated
# 180 degrees, P2 = -P1 and W2 = -W1. Each arm lays its base link flat on the
# base line with the A-P rocker and P-Q coupler on one side leaning outward, and
# reaches its forearm out the other side:
#
#   arm 1  rocker and coupler at (-x, +y),  forearm down to (-38.6, -79.7) mm
#   arm 2  rocker and coupler at (+x, -y),  forearm up   to (+38.6, +79.7) mm
#
# Identical angles put both arms on the same branch, elbow_down. Because the
# planner never changes branch, parking here pins them there for the whole job.
#
# An elbow angle of -75 degrees holds the arm 75 degrees off straight, well clear of the 34.06
# degree self-collision bound, keeps 5 degrees of margin on the joint stop, and
# at the default 240 mm base gap keeps the tips clear of boards up to
# 80 x 120 mm. Re-pick it if the base gap or board size changes.
ARM1_HOLD_JOINTS = JointAngles(0.0, -75.0)
ARM2_HOLD_JOINTS = JointAngles(0.0, -75.0)


@dataclass(frozen=True)
class DualJointState:
    arm1: JointAngles
    arm2: JointAngles

    def for_arm(self, arm_id: str) -> JointAngles:
        return self.arm1 if arm_id == "arm1" else self.arm2

    def replace_arm(self, arm_id: str, joints: JointAngles) -> "DualJointState":
        if arm_id == "arm1":
            return DualJointState(joints, self.arm2)
        if arm_id == "arm2":
            return DualJointState(self.arm1, joints)
        raise ValueError(f"unknown arm {arm_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm1": [self.arm1.shoulder_deg, self.arm1.elbow_deg],
            "arm2": [self.arm2.shoulder_deg, self.arm2.elbow_deg],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DualJointState":
        return cls(JointAngles(*data["arm1"]), JointAngles(*data["arm2"]))


def safe_hold_state() -> DualJointState:
    """Both arms parked at their configured safe/hold poses."""
    return DualJointState(ARM1_HOLD_JOINTS, ARM2_HOLD_JOINTS)


@dataclass(frozen=True)
class TrajectorySample:
    time_s: float
    state: DualJointState
    moving_arm: str
    machine_target: Point

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "state": self.state.to_dict(),
            "moving_arm": self.moving_arm,
            "machine_target": list(self.machine_target),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrajectorySample":
        return cls(
            time_s=float(data["time_s"]),
            state=DualJointState.from_dict(data["state"]),
            moving_arm=str(data["moving_arm"]),
            machine_target=tuple(data["machine_target"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class TrajectoryOperation:
    name: str
    moving_arm: str
    source: DualJointState
    target: DualJointState
    requested_machine_target: Point
    dt_s: float
    samples: tuple[TrajectorySample, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "moving_arm": self.moving_arm,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "requested_machine_target": list(self.requested_machine_target),
            "dt_s": self.dt_s,
            "samples": [sample.to_dict() for sample in self.samples],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrajectoryOperation":
        return cls(
            name=str(data["name"]),
            moving_arm=str(data["moving_arm"]),
            source=DualJointState.from_dict(data["source"]),
            target=DualJointState.from_dict(data["target"]),
            requested_machine_target=tuple(data["requested_machine_target"]),  # type: ignore[arg-type]
            dt_s=float(data["dt_s"]),
            samples=tuple(TrajectorySample.from_dict(item) for item in data["samples"]),
        )


@dataclass(frozen=True)
class MotionPlan:
    source: DualJointState
    target: DualJointState
    operations: tuple[TrajectoryOperation, ...]
    dry_run_trace: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "operations": [operation.to_dict() for operation in self.operations],
            "dry_run_trace": list(self.dry_run_trace),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotionPlan":
        return cls(
            source=DualJointState.from_dict(data["source"]),
            target=DualJointState.from_dict(data["target"]),
            operations=tuple(TrajectoryOperation.from_dict(item) for item in data["operations"]),
            dry_run_trace=tuple(data["dry_run_trace"]),
        )
