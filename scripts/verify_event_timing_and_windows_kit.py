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
MOVE_CAP_SEC = 2.0


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


def _world_xy(position):
    return (float(position[0]), float(position[1]))


async def _assert_event_move_cap(window, controller, event_type):
    stage_xy_before, _ = controller.get_current_stage_xy_height()
    window._trigger_event(event_type)
    await _step_updates(1)

    _assert(controller.target_stage_xy is not None, f"{event_type} did not create a move target")
    move_duration_sec = float(controller._move_duration_sec)
    _assert(
        move_duration_sec <= MOVE_CAP_SEC + 1e-6,
        f"{event_type} exceeded move cap: {move_duration_sec:.3f}s",
    )

    target_xy = controller.target_stage_xy
    initial_gap = _distance_xy(stage_xy_before, target_xy)
    await _step_updates(75)
    stage_xy_after, _ = controller.get_current_stage_xy_height()
    final_gap = _distance_xy(stage_xy_after, target_xy)
    _assert(final_gap < initial_gap, f"{event_type} did not move closer to target")
    _assert(final_gap <= 5.0, f"{event_type} did not finish near target: gap={final_gap:.2f}")
    _assert(controller.target_stage_xy is None, f"{event_type} target still active after cap window")

    print(
        f"[verify_event_timing_and_windows_kit] {event_type} move duration={move_duration_sec:.3f}s "
        f"gap={initial_gap:.2f}->{final_gap:.2f}",
        flush=True,
    )


async def main():
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"
    if not CITYDEMOPACK_STAGE_PATH.is_file():
        raise FileNotFoundError(CITYDEMOPACK_STAGE_PATH)

    opened = omni.usd.get_context().open_stage(str(CITYDEMOPACK_STAGE_PATH))
    print(f"[verify_event_timing_and_windows_kit] open_stage={opened}", flush=True)

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
    _assert(demo_app.monitor_window is not None, "monitor window not available")
    _assert(demo_app.follow_top_camera is not None, "follow controller not available")

    demo_app.characters.add_character_on_route(0)
    await _step_updates(30)

    controller = demo_app.follow_top_camera
    window = demo_app.window

    await _assert_event_move_cap(window, controller, "yell")
    await _assert_event_move_cap(window, controller, "crash")
    await _assert_event_move_cap(window, controller, "explosion")

    stage_xy_before, _ = controller.get_current_stage_xy_height()
    window._trigger_event("gun")
    await _step_updates(1)

    character_path = demo_app.characters.last_action_character_path
    _assert(character_path is not None, "gun event did not choose a character")
    character_controller = demo_app.characters.get_controller(character_path)
    _assert(character_controller is not None, "selected gun character controller missing")

    event_position = character_controller.get_position()
    event_xy = _world_xy(event_position)
    stage_xy_after_trigger, _ = controller.get_current_stage_xy_height()
    _assert(
        _distance_xy(stage_xy_after_trigger, event_xy) > 1.0,
        "drone snapped to gun event instead of moving",
    )
    _assert(controller.target_stage_xy is not None, "gun event did not create a move target")
    gun_event_move_duration_sec = float(controller._move_duration_sec)
    _assert(
        gun_event_move_duration_sec <= MOVE_CAP_SEC + 1e-6,
        f"gun event exceeded move cap: {gun_event_move_duration_sec:.3f}s",
    )

    initial_gap = _distance_xy(stage_xy_before, event_xy)
    await _step_updates(20)
    stage_xy_mid, _ = controller.get_current_stage_xy_height()
    mid_gap = _distance_xy(stage_xy_mid, event_xy)
    _assert(mid_gap < initial_gap, "drone did not move closer to gun event")

    for frame_index in range(900):
        await omni.kit.app.get_app().next_update_async()
        if character_controller.is_escaping:
            print(f"[verify_event_timing_and_windows_kit] gun escape_started_frame={frame_index}", flush=True)
            break
    else:
        raise RuntimeError("gun escape did not start in time")

    _assert(abs(controller._move_speed - controller.chase_speed) < 1e-6, "gun escape is not using chase speed")

    chase_start_char = _world_xy(character_controller.get_position())
    chase_start_drone, _ = controller.get_current_stage_xy_height()
    chase_start_gap = _distance_xy(chase_start_drone, chase_start_char)
    await _step_updates(60)
    chase_end_char = _world_xy(character_controller.get_position())
    chase_end_drone, _ = controller.get_current_stage_xy_height()
    chase_end_gap = _distance_xy(chase_end_drone, chase_end_char)
    _assert(
        chase_end_gap <= max(chase_start_gap + 1.0, 25.0),
        f"drone failed to keep up with gun escape: start_gap={chase_start_gap:.2f}, end_gap={chase_end_gap:.2f}",
    )

    print(
        f"[verify_event_timing_and_windows_kit] gun move duration={gun_event_move_duration_sec:.3f}s "
        f"event_gap={initial_gap:.2f}->{mid_gap:.2f} "
        f"escape_gap={chase_start_gap:.2f}->{chase_end_gap:.2f}",
        flush=True,
    )
    print("[verify_event_timing_and_windows_kit] PASS", flush=True)
    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
