"""Optional Matplotlib views of the machine: trajectory replay and live jogging.

This module draws only. Every pose, clearance and validation result it shows
comes from :mod:`motion.kinematics`, :mod:`motion.simulator` and
:mod:`motion.validation`, so there is no second implementation of forward
kinematics, inverse kinematics or planning here. It is safe to import without
Matplotlib installed; the import happens inside the entry points.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .calibration import ArmCalibration, default_calibrations
from .geometry import DEFAULT_LAYOUT, ArmGeometry, BoardOutline, FixtureTransform, MachineLayout, Point
from .kinematics import (
    ArmPose,
    IKError,
    branch_of,
    forearm_heading_deg,
    forward_kinematics,
    inverse_kinematics,
    inverse_kinematics_all,
)
from .simulator import ReplaySample, replay_plan
from .trajectory import DualJointState, MotionPlan, safe_hold_state
from .validation import inter_arm_clearance, links_over_board, self_collision_free, validate_arm_state

ARM_COLOURS = {"arm1": "#2563eb", "arm2": "#f97316"}
LINK_STYLE = {
    "upper_arm_AE": dict(linewidth=5.0, alpha=1.0),
    "forearm_EW": dict(linewidth=5.0, alpha=1.0),
    "input_rocker_AP": dict(linewidth=3.5, alpha=1.0, linestyle="-"),
    "coupler_PQ": dict(linewidth=2.5, alpha=0.85, linestyle="--"),
    "output_rocker_EQ": dict(linewidth=3.5, alpha=0.85, linestyle="--"),
}


@dataclass(frozen=True)
class ViewerScene:
    """Everything the viewer needs that is not carried inside the plan itself."""

    layout: MachineLayout = DEFAULT_LAYOUT
    fixture: FixtureTransform = FixtureTransform()
    board: BoardOutline | None = None
    geometries: dict[str, ArmGeometry] | None = None
    calibrations: dict[str, ArmCalibration] | None = None

    def arms(self) -> dict[str, ArmGeometry]:
        return self.geometries or self.layout.arms()

    def cals(self) -> dict[str, ArmCalibration]:
        return self.calibrations or default_calibrations()

    def board_corners(self) -> tuple[Point, ...]:
        return () if self.board is None else self.board.corners_machine(self.fixture)


def save_plan(plan: MotionPlan, path: str | Path, scene: ViewerScene | None = None) -> Path:
    """Write a plan, and the scene needed to draw it, as replayable JSON."""
    path = Path(path)
    payload: dict[str, Any] = {"version": 1, "plan": plan.to_dict()}
    if scene is not None:
        payload["scene"] = {
            "base_gap_mm": scene.layout.base_gap_mm,
            "arm1_forearm_opposes_rocker": scene.layout.arm1_forearm_opposes_rocker,
            "arm2_forearm_opposes_rocker": scene.layout.arm2_forearm_opposes_rocker,
            "fixture": {
                "origin_machine_mm": list(scene.fixture.origin_machine_mm),
                "rotation_deg": scene.fixture.rotation_deg,
            },
            "board": None if scene.board is None else {
                "width_mm": scene.board.width_mm,
                "height_mm": scene.board.height_mm,
                "centre_pcb_mm": list(scene.board.centre_pcb_mm),
            },
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_plan(path: str | Path) -> tuple[MotionPlan, ViewerScene]:
    """Read back a plan saved by :func:`save_plan`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = MotionPlan.from_dict(payload["plan"])
    data = payload.get("scene")
    if not data:
        return plan, ViewerScene()
    board = data.get("board")
    scene = ViewerScene(
        layout=MachineLayout(
            base_gap_mm=float(data["base_gap_mm"]),
            arm1_forearm_opposes_rocker=bool(data.get("arm1_forearm_opposes_rocker", False)),
            arm2_forearm_opposes_rocker=bool(data["arm2_forearm_opposes_rocker"]),
        ),
        fixture=FixtureTransform(
            origin_machine_mm=tuple(data["fixture"]["origin_machine_mm"]),  # type: ignore[arg-type]
            rotation_deg=float(data["fixture"]["rotation_deg"]),
        ),
        board=None if board is None else BoardOutline(
            width_mm=float(board["width_mm"]),
            height_mm=float(board["height_mm"]),
            centre_pcb_mm=tuple(board["centre_pcb_mm"]),  # type: ignore[arg-type]
        ),
    )
    return plan, scene


def reach_field(scene: ViewerScene, extent: tuple[float, float, float, float], step_mm: float = 4.0):
    """Classify a grid of machine points as reachable by neither/arm1/arm2/both.

    Uses the production IK and the production per-arm validator, so the shaded
    envelope always agrees with what the planner will accept.
    """
    left, right, bottom, top = extent
    arms, cals = scene.arms(), scene.cals()
    rows: list[list[int]] = []
    y = bottom
    while y <= top + 1e-9:
        row: list[int] = []
        x = left
        while x <= right + 1e-9:
            value = 0
            for bit, arm_id in ((1, "arm1"), (2, "arm2")):
                geometry = arms[arm_id]
                try:
                    candidates = inverse_kinematics_all((x, y), geometry)
                except IKError:
                    continue
                if any(validate_arm_state(c.joints, geometry, cals[arm_id]) is None for c in candidates):
                    value |= bit
            row.append(value)
            x += step_mm
        rows.append(row)
        y += step_mm
    return rows


def _pose_links(pose: ArmPose) -> dict[str, tuple[Point, Point]]:
    return {
        "upper_arm_AE": (pose.A, pose.E),
        "forearm_EW": (pose.E, pose.W),
        "input_rocker_AP": (pose.A, pose.P),
        "coupler_PQ": (pose.P, pose.Q),
        "output_rocker_EQ": (pose.E, pose.Q),
    }


def _select_backend(backend: str):
    import matplotlib

    if backend:
        matplotlib.use(backend, force=True)
        if backend == "WebAgg":
            matplotlib.rcParams["webagg.address"] = "127.0.0.1"
            matplotlib.rcParams["webagg.port"] = 8988
            matplotlib.rcParams["webagg.port_retries"] = 20
            matplotlib.rcParams["webagg.open_in_browser"] = False
    import matplotlib.pyplot as plt

    return plt


def _draw_static_scene(ax, scene: ViewerScene, show_envelope: bool, title: str):
    """Draw the machine frame, reach envelopes and fixture; return the plot extent."""
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Polygon

    arms = scene.arms()
    reach = arms["arm1"].upper_arm_mm + arms["arm1"].forearm_mm
    limit = scene.layout.base_gap_mm / 2.0 + reach + 20.0
    extent = (-limit, limit, -reach - 30.0, reach + 30.0)

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("machine X (mm)")
    ax.set_ylabel("machine Y (mm)")
    ax.grid(True, color="0.92", linewidth=0.8)
    ax.set_title(title)

    if show_envelope:
        ax.imshow(
            reach_field(scene, extent, step_mm=4.0), origin="lower", extent=extent,
            interpolation="nearest", alpha=0.30,
            cmap=ListedColormap(["#ffffff", "#bfdbfe", "#fed7aa", "#86efac"]), vmin=0, vmax=3,
        )

    # Machine frame: origin, axes and the base line through both shoulder pivots.
    ax.axhline(0.0, color="0.55", linewidth=1.0, linestyle=":", zorder=1)
    ax.annotate("", xy=(60, 0), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="0.25", lw=1.6))
    ax.annotate("", xy=(0, 60), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="0.25", lw=1.6))
    ax.text(63, 2, "+X", fontsize=9, color="0.25")
    ax.text(3, 63, "+Y", fontsize=9, color="0.25")
    ax.plot([0], [0], marker="+", markersize=12, color="0.15", zorder=6)
    ax.text(4, -12, "machine origin\n(midpoint of base joints)", fontsize=8, color="0.30")
    for arm_id, geometry in arms.items():
        ax.plot(*geometry.base, marker="s", markersize=9, color=ARM_COLOURS[arm_id], zorder=6)
        ax.annotate("", xy=geometry.local_to_machine((34.0, 0.0)), xytext=geometry.base,
                    arrowprops=dict(arrowstyle="->", color=ARM_COLOURS[arm_id], lw=1.4, alpha=0.9))
        ax.text(geometry.base[0], geometry.base[1] - 16.0, f"{arm_id} base\nlocal +X (J0=0)",
                fontsize=8, color=ARM_COLOURS[arm_id], ha="center", va="top")

    corners = scene.board_corners()
    if corners:
        ax.add_patch(Polygon(corners, closed=True, facecolor="#15803d", alpha=0.12,
                             edgecolor="#15803d", linewidth=1.5, zorder=2))
    return extent


def _make_arm_artists(ax, with_trace: bool = True) -> dict[str, Any]:
    """Create the per-arm link, joint and trace artists plus the readout box."""
    artists: dict[str, Any] = {"links": {}, "dots": {}, "traces": {}}
    for arm_id in ("arm1", "arm2"):
        for name, style in LINK_STYLE.items():
            line, = ax.plot([], [], color=ARM_COLOURS[arm_id], zorder=5, solid_capstyle="round", **style)
            artists["links"][(arm_id, name)] = line
        artists["dots"][arm_id] = ax.plot(
            [], [], linestyle="", marker="o", markersize=6, markerfacecolor="white",
            markeredgecolor=ARM_COLOURS[arm_id], zorder=6)[0]
        if with_trace:
            artists["traces"][arm_id] = ax.plot(
                [], [], color=ARM_COLOURS[arm_id], linewidth=1.0, alpha=0.6, zorder=4)[0]
    artists["readout"] = ax.text(
        0.01, 0.99, "", transform=ax.transAxes, ha="left", va="top", fontsize=8, family="monospace",
        bbox=dict(facecolor="white", edgecolor="0.8", boxstyle="round,pad=0.4"))
    return artists


def _apply_pose(artists: dict[str, Any], arm_id: str, pose: ArmPose) -> None:
    for name, (start, end) in _pose_links(pose).items():
        artists["links"][(arm_id, name)].set_data([start[0], end[0]], [start[1], end[1]])
    artists["dots"][arm_id].set_data(
        [pose.A[0], pose.E[0], pose.W[0], pose.P[0], pose.Q[0]],
        [pose.A[1], pose.E[1], pose.W[1], pose.P[1], pose.Q[1]],
    )


def _joint_report(arm_id: str, pose: ArmPose, scene: ViewerScene) -> str:
    motor0, motor1 = scene.cals()[arm_id].motor_angles_deg(pose.joints, scene.arms()[arm_id])
    side = "above" if pose.P[1] > 0 else "below" if pose.P[1] < 0 else "on"
    return (
        f"{arm_id}  {pose.joints.shoulder_deg:+9.2f}   {pose.joints.elbow_deg:+9.2f}   "
        f"{forearm_heading_deg(pose.joints):+9.2f}  {motor0:+8.2f}  {motor1:+8.2f}  "
        f"({pose.W[0]:+7.2f},{pose.W[1]:+7.2f})  rocker {side} base line"
    )


JOINT_HEADER = "      J0 shoulder  J1 elbow(rel)  forearm hdg  motor J0  motor J1      tip"


def animate_plan(
    plan: MotionPlan,
    scene: ViewerScene | None = None,
    backend: str = "WebAgg",
    show_envelope: bool = True,
    interval_ms: int = 40,
    snapshot_path: str | Path | None = None,
    snapshot_index: int = 0,
):
    """Animate a saved plan: link geometry, frames, envelope, traces and faults.

    With ``snapshot_path`` set, render one sample to an image file instead of
    opening an interactive window. Useful headlessly and in tests.
    """
    if snapshot_path is not None:
        backend = "Agg"
    plt = _select_backend(backend)
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button, Slider

    scene = scene or ViewerScene()
    arms, cals = scene.arms(), scene.cals()
    replay = replay_plan(plan, arms, cals, board_corners=scene.board_corners())
    frames: tuple[ReplaySample, ...] = replay.samples
    if not frames:
        raise ValueError("plan contains no samples to animate")

    fig, ax = plt.subplots(figsize=(11.0, 8.0))
    plt.subplots_adjust(left=0.06, right=0.99, bottom=0.17, top=0.95)
    _draw_static_scene(ax, scene, show_envelope, "dual four-bar arms - trajectory replay")
    for operation in plan.operations:
        ax.plot(*operation.requested_machine_target, marker="x", markersize=9, markeredgewidth=2.0,
                color=ARM_COLOURS[operation.moving_arm], zorder=7)

    artists = _make_arm_artists(ax)
    trace_points: dict[str, list[Point]] = {"arm1": [], "arm2": []}

    def render(index: int) -> None:
        sample = frames[index]
        poses = {"arm1": sample.arm1_pose, "arm2": sample.arm2_pose}
        for arm_id, pose in poses.items():
            _apply_pose(artists, arm_id, pose)
            points = trace_points[arm_id]
            if index == 0:
                points.clear()
            points.append(pose.W)
            artists["traces"][arm_id].set_data([p[0] for p in points], [p[1] for p in points])

        faults = []
        for arm_id, pose in poses.items():
            failure = validate_arm_state(pose.joints, arms[arm_id], cals[arm_id])
            if failure:
                faults.append(f"{arm_id} {failure.code}")
            elif not self_collision_free(pose):
                faults.append(f"{arm_id} self_collision")
        artists["readout"].set_text("\n".join([
            f"{sample.operation}  sample {sample.sample_index:3d}  t={sample.time_s:6.2f}s"
            f"  moving {sample.moving_arm}",
            JOINT_HEADER,
            _joint_report("arm1", poses["arm1"], scene),
            _joint_report("arm2", poses["arm2"], scene),
            f"inter-arm gap {sample.inter_arm_clearance_mm:6.1f} mm  ({sample.inter_arm_pair})",
            f"over board: {', '.join(sample.links_over_board) or 'none'}",
            f"faults: {', '.join(faults) or 'none'}",
        ]))

    slider = Slider(fig.add_axes((0.28, 0.07, 0.60, 0.03)), "sample", 0, len(frames) - 1,
                    valinit=0, valstep=1)
    button = Button(fig.add_axes((0.09, 0.06, 0.12, 0.045)), "Pause")
    state = {"playing": True, "index": 0}

    slider.on_changed(lambda value: (state.__setitem__("index", int(value)), render(int(value))))

    def on_button(_event: Any) -> None:
        state["playing"] = not state["playing"]
        button.label.set_text("Pause" if state["playing"] else "Play")

    button.on_clicked(on_button)

    def tick(_frame: int):
        if state["playing"]:
            state["index"] = (state["index"] + 1) % len(frames)
            slider.eventson = False
            slider.set_val(state["index"])
            slider.eventson = True
            render(state["index"])
        return ()

    render(0)
    if snapshot_path is not None:
        index = min(max(snapshot_index, 0), len(frames) - 1)
        for step in range(1, index + 1):
            render(step)  # replay so the tip trace matches the chosen sample
        slider.set_val(index)
        path = Path(snapshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return path

    animation = FuncAnimation(fig, tick, interval=interval_ms, blit=False, cache_frame_data=False)
    fig._motion_animation = animation  # keep a reference alive
    print(
        f"replay: {len(frames)} samples | validation "
        f"{'OK' if not replay.validation_errors else replay.validation_errors} | "
        f"min inter-arm gap {replay.min_inter_arm_clearance_mm:.1f} mm ({replay.min_inter_arm_pair})"
    )
    plt.show()
    return animation


def solve_machine_target(
    arm_id: str,
    target: Point,
    scene: ViewerScene,
    branch: str,
) -> tuple[ArmPose | None, str]:
    """Solve one arm to a machine-frame point on a fixed branch.

    Returns the pose and an empty reason on success, or ``None`` and a short
    reason when the point cannot be reached. Everything here is the production
    IK and the production validator, so a point this accepts is a point the
    planner will accept.
    """
    geometry = scene.arms()[arm_id]
    try:
        solution = inverse_kinematics(target, geometry, branch=branch)
    except IKError:
        distance = ((target[0] - geometry.base[0]) ** 2 + (target[1] - geometry.base[1]) ** 2) ** 0.5
        inner = abs(geometry.upper_arm_mm - geometry.forearm_mm)
        outer = geometry.upper_arm_mm + geometry.forearm_mm
        return None, f"out of reach ({distance:.0f} mm, arm spans {inner:.0f}-{outer:.0f} mm)"
    failure = validate_arm_state(solution.joints, geometry, scene.cals()[arm_id])
    if failure:
        return None, failure.code
    return solution.pose, ""


def interactive_ik(
    scene: ViewerScene | None = None,
    backend: str = "WebAgg",
    show_envelope: bool = True,
    start: DualJointState | None = None,
    snapshot_path: str | Path | None = None,
    snapshot_targets: dict[str, Point] | None = None,
):
    """Jog both tool tips around the machine frame with four sliders.

    Two sliders per arm set that arm's tool-tip target as an X and a Y in the
    *machine* frame, the same coordinates the planner and the fixture transform
    use. Each arm is solved independently and holds its last good pose when a
    target cannot be reached, so the rejected target marker keeps moving while
    the linkage stays put and the readout says why.
    """
    if snapshot_path is not None:
        backend = "Agg"
    plt = _select_backend(backend)
    from matplotlib.widgets import Button, Slider

    scene = scene or ViewerScene()
    arms = scene.arms()
    start = start or safe_hold_state()
    corners = scene.board_corners()

    fig, ax = plt.subplots(figsize=(11.0, 9.0))
    plt.subplots_adjust(left=0.06, right=0.99, bottom=0.28, top=0.95)
    extent = _draw_static_scene(ax, scene, show_envelope, "dual four-bar arms - inverse kinematics jog")
    artists = _make_arm_artists(ax, with_trace=True)

    # Each arm keeps the branch it is parked on, exactly as the planner does.
    state: dict[str, Any] = {
        arm_id: {
            "branch": branch_of(start.for_arm(arm_id)),
            "pose": forward_kinematics(start.for_arm(arm_id), arms[arm_id]),
            "reason": "",
            "trace": [],
        }
        for arm_id in ("arm1", "arm2")
    }
    requested = {
        arm_id: ax.plot([], [], marker="x", markersize=10, markeredgewidth=2.0, linestyle="",
                        color=ARM_COLOURS[arm_id], zorder=8)[0]
        for arm_id in ("arm1", "arm2")
    }

    def refresh() -> None:
        for arm_id in ("arm1", "arm2"):
            entry = state[arm_id]
            _apply_pose(artists, arm_id, entry["pose"])
            trace = entry["trace"]
            trace.append(entry["pose"].W)
            del trace[:-400]
            artists["traces"][arm_id].set_data([p[0] for p in trace], [p[1] for p in trace])

        poses = {arm_id: state[arm_id]["pose"] for arm_id in ("arm1", "arm2")}
        combined = DualJointState(poses["arm1"].joints, poses["arm2"].joints)
        clearance, pair = inter_arm_clearance(combined, arms)
        over = links_over_board(poses["arm1"], corners) + tuple(
            f"arm2.{name}" for name in links_over_board(poses["arm2"], corners))
        lines = ["      requested target      status"]
        for arm_id in ("arm1", "arm2"):
            entry = state[arm_id]
            wanted = (sliders[arm_id]["x"].val, sliders[arm_id]["y"].val)
            status = f"reached on {entry['branch']}" if not entry["reason"] else f"REJECTED: {entry['reason']}"
            lines.append(f"{arm_id}  ({wanted[0]:+7.1f},{wanted[1]:+7.1f})       {status}")
        lines.append(JOINT_HEADER)
        lines.append(_joint_report("arm1", poses["arm1"], scene))
        lines.append(_joint_report("arm2", poses["arm2"], scene))
        lines.append(f"inter-arm gap {clearance:6.1f} mm  ({pair})  [advisory]")
        lines.append(f"over board: {', '.join(over) or 'none'}")
        artists["readout"].set_text("\n".join(lines))
        fig.canvas.draw_idle()

    def on_change(_value: float = 0.0) -> None:
        for arm_id in ("arm1", "arm2"):
            target = (sliders[arm_id]["x"].val, sliders[arm_id]["y"].val)
            requested[arm_id].set_data([target[0]], [target[1]])
            pose, reason = solve_machine_target(arm_id, target, scene, state[arm_id]["branch"])
            state[arm_id]["reason"] = reason
            if pose is not None:
                state[arm_id]["pose"] = pose
        refresh()

    sliders: dict[str, dict[str, Any]] = {}
    rows = {"arm1": (0.205, 0.160), "arm2": (0.090, 0.045)}
    for arm_id, (row_x, row_y) in rows.items():
        home_tip = forward_kinematics(start.for_arm(arm_id), arms[arm_id]).W
        sliders[arm_id] = {
            "x": Slider(fig.add_axes((0.33, row_x, 0.55, 0.026)), f"{arm_id}  X",
                        extent[0], extent[1], valinit=home_tip[0], valstep=0.5,
                        color=ARM_COLOURS[arm_id]),
            "y": Slider(fig.add_axes((0.33, row_y, 0.55, 0.026)), f"{arm_id}  Y",
                        extent[2], extent[3], valinit=home_tip[1], valstep=0.5,
                        color=ARM_COLOURS[arm_id]),
        }
        for slider in sliders[arm_id].values():
            slider.on_changed(on_change)

    def flip(arm_id: str):
        def handler(_event: Any) -> None:
            entry = state[arm_id]
            entry["branch"] = "elbow_up" if entry["branch"] == "elbow_down" else "elbow_down"
            branch_buttons[arm_id].label.set_text(f"{arm_id} {entry['branch']}")
            on_change()
        return handler

    branch_buttons = {
        "arm1": Button(fig.add_axes((0.03, 0.170, 0.16, 0.046)), f"arm1 {state['arm1']['branch']}"),
        "arm2": Button(fig.add_axes((0.03, 0.055, 0.16, 0.046)), f"arm2 {state['arm2']['branch']}"),
    }
    for arm_id, button in branch_buttons.items():
        button.on_clicked(flip(arm_id))

    reset = Button(fig.add_axes((0.905, 0.115, 0.075, 0.05)), "Home")

    def on_reset(_event: Any) -> None:
        for arm_id in ("arm1", "arm2"):
            state[arm_id]["trace"].clear()
            home_tip = forward_kinematics(start.for_arm(arm_id), arms[arm_id]).W
            for axis, value in (("x", home_tip[0]), ("y", home_tip[1])):
                sliders[arm_id][axis].eventson = False
                sliders[arm_id][axis].set_val(value)
                sliders[arm_id][axis].eventson = True
        on_change()

    reset.on_clicked(on_reset)
    fig._motion_widgets = (sliders, branch_buttons, reset)  # keep references alive
    on_change()

    if snapshot_path is not None:
        for arm_id, target in (snapshot_targets or {}).items():
            for axis, value in zip(("x", "y"), target):
                sliders[arm_id][axis].eventson = False
                sliders[arm_id][axis].set_val(value)
                sliders[arm_id][axis].eventson = True
        on_change()
        path = Path(snapshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return path

    print("jog: drag the four sliders; both targets are machine-frame X/Y from the origin")
    plt.show()
    return fig
