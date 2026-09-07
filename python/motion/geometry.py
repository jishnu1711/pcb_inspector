"""Authoritative millimetre geometry and coordinate-frame definitions.

Frames
------
``machine``
    Right-handed millimetre frame. The origin is the midpoint of the two
    shoulder pivots, ``+X`` runs from arm 1's base toward arm 2's base, and
    ``+Y`` is 90 degrees counter-clockwise from ``+X`` in the top view. The
    line ``y = 0`` through both base joints is referred to as the base line.
``local``
    Per-arm frame: translate to the arm's base, then rotate by
    ``local_rotation_deg``. Local ``+X`` points at the machine origin for both
    arms, so shoulder angle 0 aims the upper arm inward and increasing shoulder
    angle rotates counter-clockwise in the machine top view for both arms.
``pcb``
    Logical board coordinates, mapped into machine XY by ``FixtureTransform``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin


Point = tuple[float, float]

# Distance between the two shoulder pivots. This is the dominant limit on the
# region both arms can reach: the per-arm tip band is 47.0-136.4 mm, so at
# 240 mm the shared region is only about 24 x 64 mm regardless of joint limits.
BASE_GAP_MM = 240.0


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
    forearm_opposes_rocker: bool = True

    # ``forearm_opposes_rocker`` records how the forearm E-W is rigidly bolted to
    # the output rocker E-Q, and it decides which side of the upper arm A-E the
    # whole parallelogram sits on, in every pose:
    #
    #   True  (prototype build) E-W points opposite E-Q, so A-P is exactly
    #         anti-parallel to the forearm and the A-P/P-Q/E-Q linkage always
    #         trails on the BACK side of A-E, away from the reach direction.
    #   False (default)         E-W points along E-Q, so A-P is parallel to the
    #         forearm and the linkage always folds onto the REACH side of A-E,
    #         tucked alongside the arm.
    #
    # The choice leaves the tool tip, the reachable workspace and the A-E/P-Q
    # clearance bit-for-bit identical; it only mirrors A-P and E-Q about the
    # base joint. On real hardware it implies a 180 degree elbow motor offset,
    # to be measured during commissioning.

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


@dataclass(frozen=True)
class MachineLayout:
    """Placement of both arms relative to the shared machine origin.

    Both arms mount the forearm opposed to their output rocker, so they are one
    identical build, and arm 2 is arm 1 rotated 180 degrees about the machine
    origin. Driving them to identical joint angles therefore puts their poses in
    point symmetry: each lays its base link flat along the base line with the
    A-P rocker and P-Q coupler to one side leaning outward, and reaches its
    forearm out the other side, arm 1 downward and arm 2 upward.

    The mount choice costs nothing kinematically. Each arm's reachable set and
    its branch labelling are identical either way, because the tool tip depends
    only on the shoulder angle and the absolute forearm heading, and the elbow
    limit window is expressed against that heading. Only the linkage layout and
    the sense in which the forearm extends change.
    """

    base_gap_mm: float = BASE_GAP_MM
    arm1_forearm_opposes_rocker: bool = True
    arm2_forearm_opposes_rocker: bool = True

    def __post_init__(self) -> None:
        if self.base_gap_mm <= 0:
            raise ValueError("base gap must be positive")

    def arms(self) -> dict[str, ArmGeometry]:
        """Build both arm frames symmetrically about the machine origin."""
        half = self.base_gap_mm / 2.0
        return {
            "arm1": ArmGeometry(
                base=(-half, 0.0),
                local_rotation_deg=0.0,
                forearm_opposes_rocker=self.arm1_forearm_opposes_rocker,
            ),
            "arm2": ArmGeometry(
                base=(half, 0.0),
                local_rotation_deg=180.0,
                forearm_opposes_rocker=self.arm2_forearm_opposes_rocker,
            ),
        }


# Arm 2's 180-degree rotation makes local +X face inward while preserving the
# mechanism handedness. It is deliberately not an assembly reflection.
DEFAULT_LAYOUT = MachineLayout()
ARM_1 = DEFAULT_LAYOUT.arms()["arm1"]
ARM_2 = DEFAULT_LAYOUT.arms()["arm2"]


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


@dataclass(frozen=True)
class BoardOutline:
    """Rectangular PCB footprint expressed in logical PCB coordinates."""

    width_mm: float
    height_mm: float
    centre_pcb_mm: Point = (0.0, 0.0)

    def corners_pcb(self) -> tuple[Point, ...]:
        half_w, half_h = self.width_mm / 2.0, self.height_mm / 2.0
        cx, cy = self.centre_pcb_mm
        return (
            (cx - half_w, cy - half_h),
            (cx + half_w, cy - half_h),
            (cx + half_w, cy + half_h),
            (cx - half_w, cy + half_h),
        )

    def corners_machine(self, fixture: FixtureTransform) -> tuple[Point, ...]:
        return tuple(fixture.pcb_to_machine(corner) for corner in self.corners_pcb())
