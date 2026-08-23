"""Authoritative millimetre geometry and coordinate-frame definitions."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin


Point = tuple[float, float]


@dataclass(frozen=True)
class ArmGeometry:
    """Planar four-bar dimensions and the arm's rigid machine-frame transform."""

    base: Point
    local_rotation_deg: float
    upper_arm_mm: float = 60.0  # A-E
    input_rocker_mm: float = 50.0  # A-P
    coupler_mm: float = 60.0  # P-Q
    output_rocker_mm: float = 50.0  # E-Q
    forearm_mm: float = 82.5  # E-W

    def local_to_machine(self, point: Point) -> Point:
        """Map a local point with a rigid rotation followed by base translation."""
        x, y = point
        theta = radians(self.local_rotation_deg)
        return (
            self.base[0] + cos(theta) * x - sin(theta) * y,
            self.base[1] + sin(theta) * x + cos(theta) * y,
        )

    def machine_to_local(self, point: Point) -> Point:
        """Map a machine point into this arm's local, right-handed frame."""
        x, y = point[0] - self.base[0], point[1] - self.base[1]
        theta = radians(-self.local_rotation_deg)
        return (cos(theta) * x - sin(theta) * y, sin(theta) * x + cos(theta) * y)


# Arm 2's 180-degree rotation makes local +X face inward while preserving the
# mechanism handedness. It is deliberately not an assembly reflection.
ARM_1 = ArmGeometry(base=(-120.0, 0.0), local_rotation_deg=0.0)
ARM_2 = ArmGeometry(base=(120.0, 0.0), local_rotation_deg=180.0)


@dataclass(frozen=True)
class FixtureTransform:
    """Rigid transform from logical PCB coordinates to machine coordinates."""

    origin_machine_mm: Point = (0.0, 0.0)
    rotation_deg: float = 0.0

    def pcb_to_machine(self, point: Point) -> Point:
        x, y = point
        theta = radians(self.rotation_deg)
        return (
            self.origin_machine_mm[0] + cos(theta) * x - sin(theta) * y,
            self.origin_machine_mm[1] + sin(theta) * x + cos(theta) * y,
        )

    def machine_to_pcb(self, point: Point) -> Point:
        x, y = point[0] - self.origin_machine_mm[0], point[1] - self.origin_machine_mm[1]
        theta = radians(-self.rotation_deg)
        return (cos(theta) * x - sin(theta) * y, sin(theta) * x + cos(theta) * y)
