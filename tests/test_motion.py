from __future__ import annotations

import json
from math import hypot, isclose, radians, sin

import pytest

from motion.calibration import SHOULDER_LIMIT_DEG, default_calibrations
from motion.geometry import ARM_1, ARM_2, ArmGeometry, BoardOutline, FixtureTransform, MachineLayout
from motion.kinematics import (
    IKError,
    JointAngles,
    branch_of,
    forearm_heading_deg,
    normalize_degrees,
    forward_kinematics,
    inverse_kinematics,
    inverse_kinematics_all,
    rocker_heading_deg,
)
from motion.planner import DualArmPlanner, PlanningError
from motion.simulator import replay_plan
from motion.trajectory import ARM1_HOLD_JOINTS, ARM2_HOLD_JOINTS, DualJointState, MotionPlan, safe_hold_state
from motion.validation import (
    SELF_COLLISION_THRESHOLD_MM,
    inter_arm_clearance,
    links_over_board,
    segment_distance,
    self_collision_free,
    validate_arm_state,
)
from motion.viewer import ViewerScene, solve_machine_target

HOLD = safe_hold_state()
CALIBRATIONS = default_calibrations()


def test_golden_fk_vectors_and_arm2_inward_frame():
    arm1 = forward_kinematics(JointAngles(60.0, -40.0), ARM_1)
    arm2 = forward_kinematics(JointAngles(60.0, -40.0), ARM_2)
    assert arm1.E == pytest.approx((-90.0, 51.961524), abs=1e-6)
    assert arm1.W == pytest.approx((-12.475359, 80.178186), abs=1e-6)
    # Arm 2 is the 180-degree rotation of arm 1 about the machine origin, so the
    # same joints put its tip at the point reflection of arm 1's tip.
    assert arm2.E == pytest.approx((90.0, -51.961524), abs=1e-6)
    assert arm2.W == pytest.approx((12.475359, -80.178186), abs=1e-6)
    assert ARM_2.local_to_machine((1.0, 0.0)) == pytest.approx((119.0, 0.0))
    assert ARM_2.local_to_machine((0.0, 1.0)) == pytest.approx((120.0, -1.0))


def test_shoulder_zero_aims_both_arms_at_the_machine_origin():
    for geometry in (ARM_1, ARM_2):
        tip = forward_kinematics(JointAngles(0.0, 60.0), geometry).W
        base = geometry.base
        assert abs(tip[0]) < abs(base[0])  # the tip moved inward, toward x = 0
        inward = geometry.local_to_machine((10.0, 0.0))
        assert abs(inward[0]) < abs(base[0])


@pytest.mark.parametrize("geometry,target", [(ARM_1, (-40.0, 80.0)), (ARM_2, (40.0, -80.0))])
def test_golden_fk_ik_round_trip(geometry, target):
    solution = inverse_kinematics(target, geometry, current=JointAngles(30.0, -75.0))
    pose = forward_kinematics(solution.joints, geometry)
    assert pose.W == pytest.approx(target, abs=1e-9)


def test_ik_preserves_both_branches_and_rejects_unreachable_target():
    branches = inverse_kinematics_all((-40.0, 80.0), ARM_1)
    assert {candidate.branch for candidate in branches} == {"elbow_down", "elbow_up"}
    with pytest.raises(IKError):
        inverse_kinematics((500.0, 0.0), ARM_1)


def test_elbow_angle_is_relative_and_the_elbow_motor_is_coupled_to_both_joints():
    """J1 is the textbook theta2; the motor that produces it is not."""
    for arm_id, geometry in (("arm1", ARM_1), ("arm2", ARM_2)):
        offset = 180.0 if geometry.forearm_opposes_rocker else 0.0
        del arm_id
        for shoulder, elbow in ((0.0, -75.0), (40.0, 20.0), (-30.0, -20.0)):
            joints = JointAngles(shoulder, elbow)
            # theta2 is measured from the extension of the upper arm, so the
            # forearm heading is the sum of the two joint coordinates...
            assert forearm_heading_deg(joints) == pytest.approx(
                normalize_degrees(shoulder + elbow), abs=1e-9)
            # ...and the rocker the motor drives follows it, offset by the build.
            assert rocker_heading_deg(joints, geometry) == pytest.approx(
                normalize_degrees(shoulder + elbow + offset), abs=1e-9)

    # Holding the elbow motor still while the shoulder sweeps is the defining
    # behaviour of the remote drive: the forearm keeps pointing the same way in
    # space, so the elbow joint angle changes one-for-one with the shoulder.
    calibration = CALIBRATIONS["arm1"]
    reference = JointAngles(0.0, -75.0)
    _, elbow_motor = calibration.motor_angles_deg(reference, ARM_1)
    for shoulder in (-40.0, -10.0, 25.0, 50.0):
        held = JointAngles(shoulder, -75.0 - shoulder)
        assert calibration.motor_angles_deg(held, ARM_1)[1] == pytest.approx(elbow_motor, abs=1e-9)
        assert forearm_heading_deg(held) == pytest.approx(forearm_heading_deg(reference), abs=1e-9)
        assert forward_kinematics(held, ARM_1).W != forward_kinematics(reference, ARM_1).W

    # Point-symmetric parking on one identical build: identical motor angles.
    assert CALIBRATIONS["arm1"].motor_angles_deg(HOLD.arm1, ARM_1) == pytest.approx((0.0, -75.0), abs=1e-9)
    assert CALIBRATIONS["arm2"].motor_angles_deg(HOLD.arm2, ARM_2) == pytest.approx((0.0, -75.0), abs=1e-9)


def test_branch_of_matches_the_branch_ik_reports():
    for target in ((-40.0, 80.0), (-60.0, -30.0), (-150.0, 60.0), (-90.0, 20.0)):
        for solution in inverse_kinematics_all(target, ARM_1):
            assert branch_of(solution.joints) == solution.branch


def test_fixture_transform_is_rigid_and_invertible():
    fixture = FixtureTransform(origin_machine_mm=(10.0, 20.0), rotation_deg=90.0)
    machine = fixture.pcb_to_machine((5.0, 3.0))
    assert machine == pytest.approx((7.0, 25.0))
    assert fixture.machine_to_pcb(machine) == pytest.approx((5.0, 3.0))


def test_board_outline_maps_through_the_fixture():
    corners = BoardOutline(60.0, 40.0).corners_machine(FixtureTransform(origin_machine_mm=(5.0, 0.0)))
    assert corners[0] == pytest.approx((-25.0, -20.0))
    assert corners[2] == pytest.approx((35.0, 20.0))


def test_self_collision_rule_is_the_documented_closed_form():
    # The clearance is now a function of the elbow angle alone: 50*|sin(theta2)|.
    for joints in (JointAngles(60.0, -40.0), JointAngles(30.0, 45.0), JointAngles(20.0, -50.0)):
        pose = forward_kinematics(joints, ARM_1)
        expected = ARM_1.input_rocker_mm * abs(sin(radians(joints.elbow_deg)))
        assert segment_distance(pose.A, pose.E, pose.P, pose.Q) == pytest.approx(expected, abs=1e-9)
    assert not self_collision_free(forward_kinematics(JointAngles(0.0, 0.0), ARM_1))
    assert SELF_COLLISION_THRESHOLD_MM == pytest.approx(28.0)


def test_forearm_mount_decides_the_parallelogram_side_of_the_upper_arm():
    """The mount choice, not the pose, fixes which side of A-E the linkage sits on."""
    def side(origin, along, point):
        return (along[0] - origin[0]) * (point[1] - origin[1]) - (along[1] - origin[1]) * (point[0] - origin[0])

    for opposed, expect_reach_side in ((True, False), (False, True)):
        geometry = ArmGeometry(base=(-120.0, 0.0), local_rotation_deg=0.0, forearm_opposes_rocker=opposed)
        for joints in (JointAngles(70.0, -45.0), JointAngles(30.0, 45.0), JointAngles(-45.0, 35.0),
                       JointAngles(0.0, -60.0), JointAngles(-20.0, 70.0)):
            pose = forward_kinematics(joints, geometry)
            rocker = side(pose.A, pose.E, pose.P)
            forearm = side(pose.A, pose.E, pose.W)
            assert ((rocker > 0) == (forearm > 0)) is expect_reach_side


def test_forearm_mount_flip_only_mirrors_the_rocker():
    opposed = ArmGeometry(base=(-120.0, 0.0), local_rotation_deg=0.0, forearm_opposes_rocker=True)
    parallel = ArmGeometry(base=(-120.0, 0.0), local_rotation_deg=0.0, forearm_opposes_rocker=False)
    for joints in (JointAngles(60.0, -40.0), JointAngles(30.0, 45.0), JointAngles(-45.0, 35.0)):
        a = forward_kinematics(joints, opposed)
        b = forward_kinematics(joints, parallel)
        assert b.W == pytest.approx(a.W, abs=1e-12)
        assert b.E == pytest.approx(a.E, abs=1e-12)
        assert b.P[1] == pytest.approx(-a.P[1], abs=1e-12)
        assert segment_distance(b.A, b.E, b.P, b.Q) == pytest.approx(
            segment_distance(a.A, a.E, a.P, a.Q), abs=1e-12
        )


def test_configured_limits_are_symmetric_about_each_inward_axis():
    assert validate_arm_state(JointAngles(SHOULDER_LIMIT_DEG + 5.0, -40.0), ARM_1, CALIBRATIONS["arm1"]).code == "shoulder_limit"
    # The elbow limit bounds the motor, so it is violated by a shoulder/elbow
    # *combination*, not by a large elbow angle on its own.
    assert validate_arm_state(JointAngles(60.0, 45.0), ARM_1, CALIBRATIONS["arm1"]).code == "elbow_limit"
    assert validate_arm_state(JointAngles(0.0, 0.0), ARM_1, CALIBRATIONS["arm1"]).code == "self_collision"
    # The provisional windows must never bias an arm to one side of the base
    # line again: mirroring a valid pose must stay valid for both arms.
    for joints in (JointAngles(30.0, -75.0), JointAngles(60.0, -40.0), JointAngles(-70.0, 45.0)):
        mirrored = JointAngles(-joints.shoulder_deg, -joints.elbow_deg)
        for arm_id, geometry in (("arm1", ARM_1), ("arm2", ARM_2)):
            assert validate_arm_state(joints, geometry, CALIBRATIONS[arm_id]) is None
            assert validate_arm_state(mirrored, geometry, CALIBRATIONS[arm_id]) is None


def test_hold_state_lays_both_base_links_flat_along_the_base_line():
    for arm_id, geometry in (("arm1", ARM_1), ("arm2", ARM_2)):
        joints = HOLD.for_arm(arm_id)
        assert joints.shoulder_deg == 0.0
        pose = forward_kinematics(joints, geometry)
        # A-E collinear with the two shoulder pivots, so the upper arm is
        # horizontal in the top view and its elbow sits on the base line.
        assert pose.A[1] == pytest.approx(0.0, abs=1e-9)
        assert pose.E[1] == pytest.approx(0.0, abs=1e-9)
        assert abs(pose.E[0]) == pytest.approx(abs(pose.A[0]) - geometry.upper_arm_mm, abs=1e-9)


def test_hold_state_is_point_symmetric_about_the_machine_origin():
    # One identical build 180 degrees apart, driven to identical angles, so the
    # poses are point reflections and both arms sit on the same branch.
    assert ARM1_HOLD_JOINTS == ARM2_HOLD_JOINTS == JointAngles(0.0, -75.0)
    assert branch_of(ARM1_HOLD_JOINTS) == branch_of(ARM2_HOLD_JOINTS) == "elbow_down"
    for arm_id, geometry in (("arm1", ARM_1), ("arm2", ARM_2)):
        joints = HOLD.for_arm(arm_id)
        assert validate_arm_state(joints, geometry, CALIBRATIONS[arm_id]) is None
        assert abs(joints.elbow_deg) == pytest.approx(75.0)
    pose1 = forward_kinematics(HOLD.arm1, ARM_1)
    pose2 = forward_kinematics(HOLD.arm2, ARM_2)
    # Arm 1 keeps its linkage at (-x, +y) and reaches down; arm 2 is the 180
    # degree rotation of that, linkage at (+x, -y) reaching up.
    assert pose1.P[0] < 0 and pose1.P[1] > 0 and pose1.Q[0] < 0 and pose1.Q[1] > 0
    assert pose2.P[0] > 0 and pose2.P[1] < 0 and pose2.Q[0] > 0 and pose2.Q[1] < 0
    assert pose1.W[1] < pose1.E[1]
    assert pose2.W[1] > pose2.E[1]
    # Point reflections through the machine origin, links and all.
    for a, b in ((pose1.A, pose2.A), (pose1.E, pose2.E), (pose1.P, pose2.P),
                 (pose1.Q, pose2.Q), (pose1.W, pose2.W)):
        assert b == pytest.approx((-a[0], -a[1]), abs=1e-9)
    # Both forearms reach inward, and each rocker leans outward past its base.
    for pose in (pose1, pose2):
        assert abs(pose.W[0]) < abs(pose.E[0])
        assert abs(pose.P[0]) > abs(pose.A[0])
    clearance, _ = inter_arm_clearance(HOLD, {"arm1": ARM_1, "arm2": ARM_2})
    assert clearance > 50.0  # mirrored parking brings the arms nearer than point symmetry did
    board = BoardOutline(60.0, 60.0).corners_machine(FixtureTransform())
    assert links_over_board(pose1, board) == ()
    assert links_over_board(pose2, board) == ()


def test_both_forearms_run_against_their_output_rockers():
    """One identical build: E-W opposes E-Q on both arms."""
    def along(pose):
        forearm = (pose.W[0] - pose.E[0], pose.W[1] - pose.E[1])
        output = (pose.Q[0] - pose.E[0], pose.Q[1] - pose.E[1])
        return forearm[0] * output[0] + forearm[1] * output[1]

    assert ARM_1.forearm_opposes_rocker is ARM_2.forearm_opposes_rocker is True
    for joints in (JointAngles(0.0, -75.0), JointAngles(40.0, 20.0), JointAngles(-30.0, -20.0)):
        assert along(forward_kinematics(joints, ARM_1)) < 0.0
        assert along(forward_kinematics(joints, ARM_2)) < 0.0


def test_arms_are_one_identical_build_with_equal_links():
    """Every link is the same length on both arms; only the poses mirror."""
    for field in ("upper_arm_mm", "input_rocker_mm", "coupler_mm", "output_rocker_mm", "forearm_mm"):
        assert getattr(ARM_1, field) == getattr(ARM_2, field)
    for joints in (JointAngles(0.0, -75.0), JointAngles(40.0, -93.0), JointAngles(-30.0, 55.0)):
        a = forward_kinematics(joints, ARM_1)
        b = forward_kinematics(joints, ARM_2)
        for start, end in (("A", "E"), ("A", "P"), ("P", "Q"), ("E", "Q"), ("E", "W")):
            span = lambda pose: hypot(getattr(pose, end)[0] - getattr(pose, start)[0],
                                      getattr(pose, end)[1] - getattr(pose, start)[1])
            assert span(a) == pytest.approx(span(b), abs=1e-9)


def test_sequential_plan_holds_other_arm_and_replays_to_targets():
    planner = DualArmPlanner()
    plan = planner.plan_probe_pair((-10.0, 30.0), (10.0, -30.0), HOLD)
    assert len(plan.operations) == 2
    first, second = plan.operations
    assert (first.moving_arm, second.moving_arm) == ("arm1", "arm2")
    assert first.samples[0].state == HOLD
    assert all(sample.state.arm2 == HOLD.arm2 for sample in first.samples)
    assert all(sample.state.arm1 == first.target.arm1 for sample in second.samples)
    assert "hold arm2" in plan.dry_run_trace[0]
    replay = replay_plan(plan, planner.geometries, planner.calibrations)
    assert not replay.validation_errors
    assert all(isclose(error, 0.0, abs_tol=1e-9) for error in replay.final_errors_mm.values())


def test_plan_is_deterministic_for_the_same_input():
    planner = DualArmPlanner()
    first = planner.plan_probe_pair((-10.0, 30.0), (10.0, -30.0), HOLD)
    second = planner.plan_probe_pair((-10.0, 30.0), (10.0, -30.0), HOLD)
    assert first == second


def test_required_branch_change_is_rejected_instead_of_emitting_a_jump():
    planner = DualArmPlanner()
    on_elbow_up = JointAngles(-40.0, 90.0)
    assert branch_of(on_elbow_up) == "elbow_up"
    assert validate_arm_state(on_elbow_up, ARM_1, CALIBRATIONS["arm1"]) is None
    # (-40, -40) is only reachable on elbow_down, so continuing from an elbow_up
    # pose must fail rather than emit an instantaneous branch flip at sample 0.
    source = DualJointState(on_elbow_up, ARM2_HOLD_JOINTS)
    with pytest.raises(PlanningError, match="branch changes are not planned"):
        planner._plan_arm_move("arm1", (-40.0, -40.0), source)


def test_unreachable_and_out_of_limit_targets_are_reported():
    planner = DualArmPlanner()
    with pytest.raises(PlanningError):
        planner.plan_probe_pair((-500.0, 0.0), (10.0, -30.0), HOLD)
    # Reachable by the two-link geometry but no branch survives the joint
    # limits and the self-collision clearance.
    with pytest.raises(PlanningError, match="no branch within limits"):
        planner.plan_probe_pair((-120.0, 30.0), (10.0, -30.0), HOLD)


def test_plan_survives_a_json_round_trip():
    planner = DualArmPlanner()
    plan = planner.plan_probe_pair((-10.0, 30.0), (10.0, -30.0), HOLD)
    restored = MotionPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert restored == plan


def test_replay_measures_inter_arm_clearance_and_board_intrusion():
    planner = DualArmPlanner(layout=MachineLayout())
    plan = planner.plan_probe_pair((-10.0, 30.0), (10.0, -30.0), HOLD)
    board = BoardOutline(60.0, 60.0).corners_machine(FixtureTransform())
    replay = replay_plan(plan, planner.geometries, planner.calibrations, board_corners=board)
    assert replay.min_inter_arm_clearance_mm > 0.0
    assert replay.min_inter_arm_pair
    crossing = {link for sample in replay.samples for link in sample.links_over_board}
    # Only the forearms should ever pass over the board; the rockers stay outside.
    assert crossing and all("forearm" in link for link in crossing)
    # Point-symmetric parking puts the rockers on opposite sides of the base
    # line at home, but that is a property of the pose, not a guarantee the
    # planner maintains, so it is measured and reported rather than enforced.
    assert (replay.samples[0].arm1_pose.P[1] > 0) != (replay.samples[0].arm2_pose.P[1] > 0)


def test_both_arms_solve_the_same_machine_frame_point():
    """One machine target, both arms, no per-arm coordinates anywhere."""
    scene = ViewerScene()
    pinned = {arm_id: branch_of(HOLD.for_arm(arm_id)) for arm_id in ("arm1", "arm2")}
    for target in ((0.0, 0.0), (0.0, 40.0), (0.0, -40.0), (12.0, 20.0), (-12.0, -20.0)):
        for arm_id in ("arm1", "arm2"):
            pose, reason = solve_machine_target(arm_id, target, scene, pinned[arm_id])
            assert pose is not None, f"{arm_id} rejected {target}: {reason}"
            assert reason == ""
            # The tip lands on the requested machine point, not on some
            # per-arm-frame equivalent of it.
            assert pose.W == pytest.approx(target, abs=1e-9)


def test_unreachable_machine_points_are_reported_not_silently_clamped():
    scene = ViewerScene()
    # Far outside both annuli.
    for arm_id in ("arm1", "arm2"):
        pose, reason = solve_machine_target(arm_id, (300.0, 0.0), scene, "elbow_down")
        assert pose is None and "out of reach" in reason
    # Inside arm 1's dead disc around its own shoulder.
    pose, reason = solve_machine_target("arm1", (-118.0, 6.0), scene, "elbow_down")
    assert pose is None and "out of reach" in reason
    # Reachable by the geometry but refused by the configured limits.
    pose, reason = solve_machine_target("arm1", (-100.0, 40.0), scene, "elbow_down")
    assert pose is None and reason == "shoulder_limit"


def test_a_point_one_arm_can_reach_and_the_other_cannot():
    scene = ViewerScene()
    reached, rejected = solve_machine_target("arm1", (-8.0, 50.0), scene, "elbow_down")
    assert reached is not None and rejected == ""
    pose, reason = solve_machine_target("arm2", (-8.0, 50.0), scene, "elbow_down")
    assert pose is None and reason == "self_collision"


def test_solver_agrees_with_the_planner_about_what_is_reachable():
    """The jog view must never accept a point the planner would refuse."""
    scene = ViewerScene()
    planner = DualArmPlanner()
    for target in ((0.0, 30.0), (0.0, -30.0), (8.0, 0.0), (-8.0, 45.0), (0.0, 70.0), (40.0, 0.0)):
        for arm_id in ("arm1", "arm2"):
            pose, _ = solve_machine_target(arm_id, target, scene, branch_of(HOLD.for_arm(arm_id)))
            try:
                planner._plan_arm_move(arm_id, target, HOLD)
            except PlanningError:
                planned = False
            else:
                planned = True
            assert (pose is not None) == planned, f"{arm_id} disagreed about {target}"
