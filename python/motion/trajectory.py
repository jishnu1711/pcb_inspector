"""Serializable fixed-period, four-axis motion trajectory records."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point
from .kinematics import JointAngles


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


@dataclass(frozen=True)
class TrajectorySample:
    time_s: float
    state: DualJointState
    moving_arm: str
    machine_target: Point


@dataclass(frozen=True)
class TrajectoryOperation:
    name: str
    moving_arm: str
    source: DualJointState
    target: DualJointState
    requested_machine_target: Point
    dt_s: float
    samples: tuple[TrajectorySample, ...]


@dataclass(frozen=True)
class MotionPlan:
    source: DualJointState
    target: DualJointState
    operations: tuple[TrajectoryOperation, ...]
    dry_run_trace: tuple[str, ...]
