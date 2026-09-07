"""Explicit software-joint to motor configuration; no hardware I/O occurs here.

Both motors sit at the base. The shoulder motor drives the upper arm A-E
directly, so its angle is the shoulder joint coordinate. The elbow motor drives
the input rocker A-P, and the parallelogram carries that to the forearm as an
*absolute* heading, so the elbow motor angle is not the elbow joint coordinate:
it depends on both joints,

    elbow motor angle  =  shoulder_deg + elbow_deg  (+ 180 if the forearm is
                          mounted opposed to its output rocker, absorbed by
                          ``offset_deg``)

which is the coupling every remote-driven arm has. Holding the elbow motor
still while the shoulder sweeps leaves the forearm pointing the same way in
space and changes the elbow joint angle one-for-one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import ArmGeometry
from .kinematics import JointAngles, forearm_heading_deg, normalize_degrees, rocker_heading_deg


# Provisional commissioning limits, applied to the *motor* angles. They keep the
# prototype's 160-degree travel per axis but are re-centred on each arm's inward
# axis, because shoulder 0 aims the upper arm at the machine origin for both
# arms and increasing shoulder rotates counter-clockwise for both. The
# prototype's [0, 160] / [-130, 10] windows were written for a single arm and,
# applied unchanged to a 180-degree rotated arm 2, swept arm 1 above the base
# line and arm 2 below it, leaving the two arms with no shared workspace at all.
# Real hardware must confirm zeros, signs, offsets and travel.
SHOULDER_LIMIT_DEG = 80.0
ELBOW_LIMIT_DEG = 80.0


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
        """Range check the motor angle, wrapped into a single turn.

        The wrap matters because an axis whose ``offset_deg`` is a half turn
        would otherwise fail its own working range: the input heading is already
        normalised, so subtracting 180 from it lands outside [-180, 180].
        Configured windows must therefore sit inside one turn.
        """
        motor_deg = normalize_degrees(self.software_to_motor_deg(software_deg))
        return self.min_deg <= motor_deg <= self.max_deg


@dataclass(frozen=True)
class ArmCalibration:
    shoulder: JointCalibration = JointCalibration(min_deg=-SHOULDER_LIMIT_DEG, max_deg=SHOULDER_LIMIT_DEG)
    elbow: JointCalibration = JointCalibration(min_deg=-ELBOW_LIMIT_DEG, max_deg=ELBOW_LIMIT_DEG)

    def motor_angles_deg(self, joints: JointAngles, geometry: ArmGeometry) -> tuple[float, float]:
        """Convert the two joint coordinates into the two base motor angles.

        The elbow motor is reported against a zero that points the *forearm*
        inward. The crank it actually turns is the input rocker A-P, which sits
        at ``rocker_heading_deg`` and is a rigid half turn away from the forearm
        on an opposed build; measuring from the forearm keeps one window that
        holds for either build. The real mechanical zero found during
        commissioning belongs in ``offset_deg``.
        """
        return (
            normalize_degrees(self.shoulder.software_to_motor_deg(joints.shoulder_deg)),
            normalize_degrees(self.elbow.software_to_motor_deg(forearm_heading_deg(joints))),
        )

    def within_limits(self, joints: JointAngles, geometry: ArmGeometry) -> str | None:
        """Return the offending axis name, or None when both motors are in range."""
        if not self.shoulder.contains_software_angle(joints.shoulder_deg):
            return "shoulder"
        if not self.elbow.contains_software_angle(forearm_heading_deg(joints)):
            return "elbow"
        return None

    def rocker_angles_deg(self, joints: JointAngles, geometry: ArmGeometry) -> float:
        """Heading of the crank the elbow motor physically turns, for reference."""
        return rocker_heading_deg(joints, geometry)


# Both arms are the same build, so they share one calibration until
# commissioning measures them separately.
DEFAULT_ARM_CALIBRATION = ArmCalibration()


def default_calibrations() -> dict[str, ArmCalibration]:
    return {"arm1": DEFAULT_ARM_CALIBRATION, "arm2": DEFAULT_ARM_CALIBRATION}
