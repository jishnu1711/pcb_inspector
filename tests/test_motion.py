from __future__ import annotations

from math import isclose

import pytest

from motion.calibration import DEFAULT_ARM_CALIBRATION
from motion.geometry import ARM_1, ARM_2, FixtureTransform
from motion.kinematics import IKError, JointAngles, forward_kinematics, inverse_kinematics, inverse_kinematics_all
from motion.planner import DualArmPlanner
from motion.simulator import replay_plan
from motion.trajectory import DualJointState
from motion.validation import validate_arm_state


START = DualJointState(JointAngles(90.0, 0.0), JointAngles(90.0, 0.0))


def test_golden_fk_vectors_and_arm2_inward_frame():
    arm1 = forward_kinematics(START.arm1, ARM_1)
    arm2 = forward_kinematics(START.arm2, ARM_2)
    assert arm1.E == pytest.approx((-120.0, 60.0))
    assert arm1.W == pytest.approx((-37.5, 60.0))
    assert arm2.E == pytest.approx((120.0, -60.0))
    assert arm2.W == pytest.approx((37.5, -60.0))
    assert ARM_2.local_to_machine((1.0, 0.0)) == pytest.approx((119.0, 0.0))
    assert ARM_2.local_to_machine((0.0, 1.0)) == pytest.approx((120.0, -1.0))


@pytest.mark.parametrize("geometry,target", [(ARM_1, (-40.0, 80.0)), (ARM_2, (40.0, -80.0))])
def test_golden_fk_ik_round_trip(geometry, target):
    solution = inverse_kinematics(target, geometry, current=JointAngles(90.0, 0.0))
    pose = forward_kinematics(solution.joints, geometry)
    assert solution.branch == "elbow_down"
    assert pose.W == pytest.approx(target, abs=1e-9)


def test_ik_preserves_both_branches_and_rejects_unreachable_target():
    branches = inverse_kinematics_all((-40.0, 80.0), ARM_1)
    assert {candidate.branch for candidate in branches} == {"elbow_down", "elbow_up"}
    with pytest.raises(IKError):
        inverse_kinematics((500.0, 0.0), ARM_1)


def test_fixture_transform_is_rigid_and_invertible():
    fixture = FixtureTransform(origin_machine_mm=(10.0, 20.0), rotation_deg=90.0)
    machine = fixture.pcb_to_machine((5.0, 3.0))
    assert machine == pytest.approx((7.0, 25.0))
    assert fixture.machine_to_pcb(machine) == pytest.approx((5.0, 3.0))


def test_configured_limits_and_existing_self_collision_rule_apply():
    assert validate_arm_state(JointAngles(170.0, 0.0), ARM_1, DEFAULT_ARM_CALIBRATION).code == "shoulder_limit"
    assert validate_arm_state(JointAngles(0.0, 0.0), ARM_1, DEFAULT_ARM_CALIBRATION).code == "self_collision"


def test_sequential_plan_holds_other_arm_and_replays_to_targets():
    planner = DualArmPlanner()
    plan = planner.plan_probe_pair((-40.0, 80.0), (40.0, -80.0), START)
    assert len(plan.operations) == 2
    first, second = plan.operations
    assert first.moving_arm == "arm1"
    assert second.moving_arm == "arm2"
    assert all(sample.state.arm2 == START.arm2 for sample in first.samples)
    assert all(sample.state.arm1 == first.target.arm1 for sample in second.samples)
    assert "hold arm2" in plan.dry_run_trace[0]
    replay = replay_plan(plan, planner.geometries, planner.calibrations)
    assert not replay.validation_errors
    assert all(isclose(error, 0.0, abs_tol=1e-9) for error in replay.final_errors_mm.values())
