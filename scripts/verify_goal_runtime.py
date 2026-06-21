from __future__ import annotations

import builtins
import math
import sys
from pathlib import Path

from isaacsim import SimulationApp


CONFIG = {"headless": True, "sync_loads": True, "renderer": "RaytracedLighting"}
simulation_app = SimulationApp(launch_config=CONFIG)

import omni.usd
from isaacsim.core.utils.stage import is_stage_loading


REPO_ROOT = Path("/home/user/Documents/DT_teamA/omniverse")
SIM_ROOT = REPO_ROOT / "cctv_sim"
sys.path.insert(0, str(SIM_ROOT))


def _exec_script(script_path: Path):
    namespace = {"__name__": "__main__", "__file__": str(script_path)}
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


def _step(count: int):
    for _ in range(count):
        simulation_app.update()


def _distance_xy(a, b):
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    stage_path = SIM_ROOT / "assets" / "city" / "World_CityDemopack.usd"
    opened = omni.usd.get_context().open_stage(str(stage_path))
    print(f"[verify_goal_runtime] open_stage={opened}")

    _step(2)
    while is_stage_loading():
        simulation_app.update()

    _exec_script(SIM_ROOT / "scripts" / "start_demo.py")
    _step(30)

    demo_app = getattr(builtins, "demo_app", None)
    _assert(demo_app is not None, "demo_app not available")

    demo_app.added_character_path = demo_app.characters.add_character_on_route(0)
    _step(30)

    window = demo_app.window
    _assert(window is not None, "demo window not available")
    controller = demo_app.follow_top_camera
    _assert(controller is not None, "follow controller not available")

    from sim.awareness import SituationAwarenessManager
    from sim.minimap_window import MinimapWindow

    _assert(
        SituationAwarenessManager.CCTV_DOT_STYLE["background_color"] == 0xFFFF7A00,
        "awareness CCTV color mismatch",
    )
    _assert(
        SituationAwarenessManager.DRONE_DOT_STYLE["background_color"] == 0xFF2F8FFF,
        "awareness drone color mismatch",
    )
    _assert(
        MinimapWindow.DRONE_DOT_STYLE["background_color"] == 0xFF2F8FFF,
        "minimap drone color mismatch",
    )

    stage_xy_before, _ = controller.get_current_stage_xy_height()
    window._trigger_event("gun")
    _step(1)

    character_path = demo_app.characters.last_action_character_path
    _assert(character_path is not None, "gun event did not select a character")
    character_controller = demo_app.characters.get_controller(character_path)
    _assert(character_controller is not None, "selected character controller missing")

    event_position = character_controller.get_position()
    stage_xy_after_trigger, _ = controller.get_current_stage_xy_height()
    _assert(
        _distance_xy(stage_xy_after_trigger, (event_position[0], event_position[1])) > 1.0,
        "drone snapped to gun event instead of moving toward it",
    )
    _assert(controller.target_stage_xy is not None, "drone target not set after gun event")

    initial_gap = _distance_xy(stage_xy_before, (event_position[0], event_position[1]))
    _step(20)
    stage_xy_mid, _ = controller.get_current_stage_xy_height()
    mid_gap = _distance_xy(stage_xy_mid, (event_position[0], event_position[1]))
    _assert(mid_gap < initial_gap, "drone did not move closer to gun event")

    escape_started = False
    for _ in range(500):
        simulation_app.update()
        if character_controller.is_escaping:
            escape_started = True
            break
    _assert(escape_started, "gun escape did not start in time")
    _assert(abs(controller._move_speed - controller.chase_speed) < 1e-6, "drone is not using chase speed")

    chase_start_char = character_controller.get_position()
    chase_start_drone, _ = controller.get_current_stage_xy_height()
    chase_start_gap = _distance_xy(chase_start_drone, (chase_start_char[0], chase_start_char[1]))
    _step(45)
    chase_end_char = character_controller.get_position()
    chase_end_drone, _ = controller.get_current_stage_xy_height()
    chase_end_gap = _distance_xy(chase_end_drone, (chase_end_char[0], chase_end_char[1]))
    _assert(
        chase_end_gap <= chase_start_gap + 1.0,
        f"drone failed to keep up with escape: start_gap={chase_start_gap:.2f}, end_gap={chase_end_gap:.2f}",
    )

    print("[verify_goal_runtime] PASS")


try:
    main()
finally:
    try:
        demo_app = getattr(builtins, "demo_app", None)
        if demo_app is not None:
            demo_app.stop()
    except Exception:
        pass
    simulation_app.close()
