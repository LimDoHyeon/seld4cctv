import asyncio
import builtins
import math
from pathlib import Path
import sys

import omni.kit.app
import omni.usd


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))

CITYDEMOPACK_STAGE_PATH = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _distance_xy(a, b):
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


async def _step_updates(count):
    for _ in range(count):
        await omni.kit.app.get_app().next_update_async()


async def main():
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"
    if not CITYDEMOPACK_STAGE_PATH.is_file():
        raise FileNotFoundError(CITYDEMOPACK_STAGE_PATH)

    opened = omni.usd.get_context().open_stage(str(CITYDEMOPACK_STAGE_PATH))
    print(f"[verify_goal_runtime_kit] open_stage={opened}", flush=True)

    usd_context = omni.usd.get_context()
    for _ in range(240):
        await omni.kit.app.get_app().next_update_async()
        stage = usd_context.get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(start_demo_script)
    await _step_updates(45)

    demo_app = getattr(builtins, "demo_app", None)
    _assert(demo_app is not None, "demo_app not available after start_demo")
    _assert(demo_app.window is not None, "demo window not available")
    _assert(demo_app.follow_top_camera is not None, "follow controller not available")

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

    demo_app.characters.add_character_on_route(0)
    await _step_updates(30)

    controller = demo_app.follow_top_camera
    stage_xy_before, _ = controller.get_current_stage_xy_height()
    demo_app.window._trigger_event("gun")
    await _step_updates(1)

    character_path = demo_app.characters.last_action_character_path
    _assert(character_path is not None, "gun event did not choose a character")
    character_controller = demo_app.characters.get_controller(character_path)
    _assert(character_controller is not None, "selected character controller missing")

    event_position = character_controller.get_position()
    stage_xy_after_trigger, _ = controller.get_current_stage_xy_height()
    _assert(
        _distance_xy(stage_xy_after_trigger, (event_position[0], event_position[1])) > 1.0,
        "drone snapped to gun event instead of moving",
    )
    _assert(controller.target_stage_xy is not None, "drone target not set after gun event")

    initial_gap = _distance_xy(stage_xy_before, (event_position[0], event_position[1]))
    await _step_updates(20)
    stage_xy_mid, _ = controller.get_current_stage_xy_height()
    mid_gap = _distance_xy(stage_xy_mid, (event_position[0], event_position[1]))
    _assert(mid_gap < initial_gap, "drone did not move closer to the gun event")

    for frame_index in range(900):
        await omni.kit.app.get_app().next_update_async()
        if character_controller.is_escaping:
            print(f"[verify_goal_runtime_kit] escape_started_frame={frame_index}", flush=True)
            break
    else:
        raise RuntimeError("gun escape did not start in time")

    _assert(abs(controller._move_speed - controller.chase_speed) < 1e-6, "drone not using chase speed")

    chase_start_char = character_controller.get_position()
    chase_start_drone, _ = controller.get_current_stage_xy_height()
    chase_start_gap = _distance_xy(chase_start_drone, (chase_start_char[0], chase_start_char[1]))
    await _step_updates(60)
    chase_end_char = character_controller.get_position()
    chase_end_drone, _ = controller.get_current_stage_xy_height()
    chase_end_gap = _distance_xy(chase_end_drone, (chase_end_char[0], chase_end_char[1]))
    _assert(
        chase_end_gap <= chase_start_gap + 1.0,
        f"drone failed to keep up with escape: start_gap={chase_start_gap:.2f}, end_gap={chase_end_gap:.2f}",
    )

    print(
        f"[verify_goal_runtime_kit] gaps event={initial_gap:.2f}->{mid_gap:.2f} "
        f"escape={chase_start_gap:.2f}->{chase_end_gap:.2f}",
        flush=True,
    )
    print("[verify_goal_runtime_kit] PASS", flush=True)
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
