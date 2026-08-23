"""Explicit software-joint to motor configuration; no hardware I/O occurs here."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JointCalibration:
    offset_deg: float = 0.0
    sign: int = 1
    min_deg: float = -180.0
    max_deg: float = 180.0
    steps_per_degree: float = 1.0

    def __post_init__(self) -> None:
        if self.sign not in {-1, 1}:
            raise ValueError("sign must be -1 or 1")
        if self.min_deg > self.max_deg or self.steps_per_degree <= 0:
            raise ValueError("invalid joint calibration range")

    def software_to_motor_deg(self, software_deg: float) -> float:
        return self.offset_deg + self.sign * software_deg

    def motor_to_software_deg(self, motor_deg: float) -> float:
        return self.sign * (motor_deg - self.offset_deg)

    def software_to_steps(self, software_deg: float) -> int:
        motor_deg = self.software_to_motor_deg(software_deg)
        return round(motor_deg * self.steps_per_degree)

    def contains_software_angle(self, software_deg: float) -> bool:
        motor_deg = self.software_to_motor_deg(software_deg)
        return self.min_deg <= motor_deg <= self.max_deg


@dataclass(frozen=True)
class ArmCalibration:
    shoulder: JointCalibration = JointCalibration(min_deg=0.0, max_deg=160.0)
    elbow: JointCalibration = JointCalibration(min_deg=-130.0, max_deg=10.0)


DEFAULT_ARM_CALIBRATION = ArmCalibration()
