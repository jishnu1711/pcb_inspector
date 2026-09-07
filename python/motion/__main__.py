"""Command-line dry run for the dual-arm planner, with optional visual replay.

Examples
--------
    PYTHONPATH=python .venv/bin/python -m motion --jog
    PYTHONPATH=python .venv/bin/python -m motion --no-view
    PYTHONPATH=python .venv/bin/python -m motion --gap 180 --board 60x120
    PYTHONPATH=python .venv/bin/python -m motion --save runtime/plan.json --no-view
    PYTHONPATH=python .venv/bin/python -m motion --load runtime/plan.json
"""

from __future__ import annotations

import argparse

from .calibration import ELBOW_LIMIT_DEG, SHOULDER_LIMIT_DEG, default_calibrations
from .geometry import BoardOutline, FixtureTransform, MachineLayout
from .kinematics import IKError, inverse_kinematics_all
from .planner import DualArmPlanner, PlannerConfig, PlanningError
from .simulator import replay_plan
from .kinematics import branch_of
from .trajectory import DualJointState, safe_hold_state
from .validation import validate_arm_state
from .viewer import ViewerScene, animate_plan, interactive_ik, load_plan, save_plan


def _point(text: str) -> tuple[float, float]:
    x, _, y = text.partition(",")
    return (float(x), float(y))


def _size(text: str) -> tuple[float, float]:
    w, _, h = text.lower().partition("x")
    return (float(w), float(h))


def workspace_summary(scene: ViewerScene, hold: DualJointState, step_mm: float = 4.0) -> str:
    """Report what both arms can reach, before and after branch pinning.

    ``any branch`` is the mechanism's shared workspace. ``held branch`` is what
    the planner will actually accept, because it never changes branch: parking
    on a branch pins the arm to it for the whole job.
    """
    arms, cals = scene.arms(), scene.cals()
    pinned = {arm_id: branch_of(hold.for_arm(arm_id)) for arm_id in ("arm1", "arm2")}
    reach = arms["arm1"].upper_arm_mm + arms["arm1"].forearm_mm
    columns = int((scene.layout.base_gap_mm / 2.0 + reach) / step_mm) + 1
    rows = int(reach / step_mm) + 1
    # Index lattice centred on the machine origin, so an origin-centred board
    # rectangle lands exactly on sampled cells.
    any_branch: set[tuple[int, int]] = set()
    held_branch: set[tuple[int, int]] = set()
    opposite = 0
    for iy in range(-rows, rows + 1):
        for ix in range(-columns, columns + 1):
            point = (ix * step_mm, iy * step_mm)
            usable: dict[str, dict[str, bool]] = {}
            for arm_id in ("arm1", "arm2"):
                geometry = arms[arm_id]
                try:
                    candidates = inverse_kinematics_all(point, geometry)
                except IKError:
                    break
                valid = {
                    c.branch: c.pose.P[1] > 0
                    for c in candidates
                    if validate_arm_state(c.joints, geometry, cals[arm_id]) is None
                }
                if not valid:
                    break
                usable[arm_id] = valid
            if len(usable) != 2:
                continue
            any_branch.add((ix, iy))
            sides = [usable[arm_id].get(pinned[arm_id]) for arm_id in ("arm1", "arm2")]
            if None in sides:
                continue
            held_branch.add((ix, iy))
            if sides[0] != sides[1]:
                opposite += 1

    def largest_centred(grid: set[tuple[int, int]]) -> tuple[float, float]:
        best = (0.0, 0.0, -1.0)
        for half_w in range(0, columns + 1):
            half_h = -1
            while all((ix, iy) in grid for iy in range(-(half_h + 1), half_h + 2) for ix in range(-half_w, half_w + 1)):
                half_h += 1
            if half_h < 0:
                break
            area = (2 * half_w * step_mm) * (2 * half_h * step_mm)
            if area >= best[2]:
                best = (2 * half_w * step_mm, 2 * half_h * step_mm, area)
        return best[0], best[1]

    if not any_branch:
        return "  both arms reach: nothing (no shared workspace)"
    xs = [ix * step_mm for ix, _ in any_branch]
    ys = [iy * step_mm for _, iy in any_branch]
    cell = step_mm * step_mm
    width, height = largest_centred(held_branch)
    rate = 0.0 if not held_branch else 100.0 * opposite / len(held_branch)
    return (
        f"  both arms reach, any branch: {len(any_branch) * cell:.0f} mm^2, "
        f"x[{min(xs):+.0f},{max(xs):+.0f}] y[{min(ys):+.0f},{max(ys):+.0f}]\n"
        f"  both arms reach on held branches ({pinned['arm1']}/{pinned['arm2']}): "
        f"{len(held_branch) * cell:.0f} mm^2\n"
        f"  largest origin-centred board both arms cover: {width:.0f} x {height:.0f} mm\n"
        f"  rockers land on opposite sides of the base line over {rate:.0f}% of that region"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gap", type=float, default=MachineLayout().base_gap_mm,
                        help="distance between the two shoulder pivots in mm")
    parser.add_argument("--arm1-forearm", choices=("parallel", "opposed"), default="opposed",
                        help="how arm 1's forearm is bolted to its output rocker; 'parallel' folds the "
                             "A-P/P-Q/E-Q linkage onto the reach side of A-E, 'opposed' trails it behind")
    parser.add_argument("--arm2-forearm", choices=("parallel", "opposed"), default="opposed",
                        help="same choice for arm 2; matching both keeps the two arms one identical build")
    parser.add_argument("--arm1-target", type=_point, default=(-10.0, 30.0), help="PCB-frame probe point for arm 1")
    parser.add_argument("--arm2-target", type=_point, default=(10.0, -30.0), help="PCB-frame probe point for arm 2")
    parser.add_argument("--board", type=_size, default=(60.0, 60.0), help="PCB outline WxH in mm, or 0x0 for none")
    parser.add_argument("--fixture-origin", type=_point, default=(0.0, 0.0), help="PCB origin in machine mm")
    parser.add_argument("--fixture-rotation", type=float, default=0.0, help="PCB rotation in degrees")
    parser.add_argument("--dt", type=float, default=PlannerConfig().dt_s, help="trajectory sample period in seconds")
    parser.add_argument("--save", help="write the plan and scene to this JSON path")
    parser.add_argument("--load", help="replay a previously saved plan instead of planning a new one")
    parser.add_argument("--jog", action="store_true",
                        help="open the inverse-kinematics jog view: four sliders that drive each "
                             "arm's tool tip to an X/Y in the machine frame")
    parser.add_argument("--no-view", action="store_true", help="print the dry-run trace without opening the viewer")
    parser.add_argument("--no-envelope", action="store_true", help="skip the reachability shading in the viewer")
    parser.add_argument("--backend", default="WebAgg", help="Matplotlib backend, for example WebAgg or TkAgg")
    parser.add_argument("--snapshot", help="render one sample to this image file instead of opening a window")
    parser.add_argument("--snapshot-index", type=int, default=0, help="sample index for --snapshot")
    args = parser.parse_args()

    if args.jog:
        layout = MachineLayout(
            base_gap_mm=args.gap,
            arm1_forearm_opposes_rocker=args.arm1_forearm == "opposed",
            arm2_forearm_opposes_rocker=args.arm2_forearm == "opposed",
        )
        board = None if args.board[0] <= 0 or args.board[1] <= 0 else BoardOutline(*args.board)
        scene = ViewerScene(
            layout=layout,
            fixture=FixtureTransform(origin_machine_mm=args.fixture_origin, rotation_deg=args.fixture_rotation),
            board=board,
        )
        print(f"limits: shoulder +/-{SHOULDER_LIMIT_DEG:.0f} deg, elbow +/-{ELBOW_LIMIT_DEG:.0f} deg (provisional)")
        print(workspace_summary(scene, safe_hold_state()))
        result = interactive_ik(scene, backend=args.backend, show_envelope=not args.no_envelope,
                                snapshot_path=args.snapshot)
        if args.snapshot:
            print(f"snapshot {result}")
        return

    if args.load:
        plan, scene = load_plan(args.load)
        print(f"loaded {args.load}")
    else:
        layout = MachineLayout(
            base_gap_mm=args.gap,
            arm1_forearm_opposes_rocker=args.arm1_forearm == "opposed",
            arm2_forearm_opposes_rocker=args.arm2_forearm == "opposed",
        )
        fixture = FixtureTransform(origin_machine_mm=args.fixture_origin, rotation_deg=args.fixture_rotation)
        board = None if args.board[0] <= 0 or args.board[1] <= 0 else BoardOutline(*args.board)
        scene = ViewerScene(layout=layout, fixture=fixture, board=board)
        planner = DualArmPlanner(fixture=fixture, config=PlannerConfig(dt_s=args.dt),
                                 calibrations=default_calibrations(), layout=layout)
        try:
            plan = planner.plan_probe_pair(args.arm1_target, args.arm2_target, safe_hold_state())
        except PlanningError as error:
            print(f"planning failed: {error}")
            print(f"\nlimits: shoulder +/-{SHOULDER_LIMIT_DEG:.0f} deg, elbow +/-{ELBOW_LIMIT_DEG:.0f} deg")
            print(workspace_summary(scene, safe_hold_state()))
            raise SystemExit(1)

    arms, cals = scene.arms(), scene.cals()
    replay = replay_plan(plan, arms, cals, board_corners=scene.board_corners())

    builds = {arm_id: "opposed" if geometry.forearm_opposes_rocker else "parallel"
              for arm_id, geometry in arms.items()}
    print(f"layout: base gap {scene.layout.base_gap_mm:.0f} mm, forearm mounts arm1 {builds['arm1']} / "
          f"arm2 {builds['arm2']}"
          f"{' (one identical build)' if builds['arm1'] == builds['arm2'] else ' (two different builds)'}; "
          f"linkage sits on the {'back' if builds['arm1'] == 'opposed' else 'reach'} side of A-E for arm1, "
          f"{'back' if builds['arm2'] == 'opposed' else 'reach'} side for arm2")
    print(f"limits: shoulder +/-{SHOULDER_LIMIT_DEG:.0f} deg, elbow +/-{ELBOW_LIMIT_DEG:.0f} deg (provisional)")
    print(workspace_summary(scene, plan.source))
    print("plan:")
    for line in plan.dry_run_trace:
        print(f"  {line}")
    for arm_id, error_mm in sorted(replay.final_errors_mm.items()):
        print(f"  {arm_id} final tip error {error_mm:.2e} mm")
    print(f"  min inter-arm gap {replay.min_inter_arm_clearance_mm:.1f} mm ({replay.min_inter_arm_pair}) [advisory]")
    over = sorted({link for sample in replay.samples for link in sample.links_over_board})
    print(f"  links crossing the board outline: {', '.join(over) or 'none'}")
    opposite = sum(
        1 for sample in replay.samples
        if (sample.arm1_pose.P[1] > 0) != (sample.arm2_pose.P[1] > 0)
    )
    print(f"  rockers on opposite sides of the base line: {opposite}/{len(replay.samples)} samples")
    print(f"  validation: {'OK' if not replay.validation_errors else replay.validation_errors}")

    if args.save:
        print(f"saved {save_plan(plan, args.save, scene)}")
    if args.snapshot:
        written = animate_plan(plan, scene, show_envelope=not args.no_envelope,
                               snapshot_path=args.snapshot, snapshot_index=args.snapshot_index)
        print(f"snapshot {written}")
    elif not args.no_view:
        animate_plan(plan, scene, backend=args.backend, show_envelope=not args.no_envelope)


if __name__ == "__main__":
    main()
