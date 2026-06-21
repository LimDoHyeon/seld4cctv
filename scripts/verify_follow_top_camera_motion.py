import asyncio
import builtins
from pathlib import Path
import sys

import omni.kit.app
import omni.usd


REPO_ROOT = Path("/home/user/Documents/DT_teamA")
sys.path.insert(0, str(REPO_ROOT / "omniverse" / "cctv_sim"))


def _exec_script(script_path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
    return namespace


def _snapshot(controller):
    stage_xy, current_height_meters = controller.get_current_stage_xy_height()
    return {
        "stage_x": round(stage_xy[0], 2),
        "stage_y": round(stage_xy[1], 2),
        "height_m": round(current_height_meters, 2),
        "focal": round(controller.get_current_focal_length(), 2),
        "target": controller.target_stage_xy,
        "move_elapsed": round(controller._move_elapsed, 3),
    }


async def main():
    stage_path = REPO_ROOT / "omniverse" / "cctv_sim" / "assets" / "city" / "World_CityDemopack.usd"
    start_demo_script = REPO_ROOT / "omniverse" / "cctv_sim" / "scripts" / "start_demo.py"

    opened = omni.usd.get_context().open_stage(str(stage_path))
    print(f"[verify_follow_top_camera_motion] open_stage={opened}")

    for _ in range(180):
        await omni.kit.app.get_app().next_update_async()
        stage = omni.usd.get_context().get_stage()
        if stage is not None and stage.GetPrimAtPath("/World").IsValid():
            break
    else:
        raise RuntimeError("Stage did not finish loading")

    _exec_script(start_demo_script)
    for _ in range(30):
        await omni.kit.app.get_app().next_update_async()

    demo_app = getattr(builtins, "demo_app", None)
    if demo_app is None:
        raise RuntimeError("demo_app not available")

    demo_app.bind_follow_top_camera_viewport()
    controller = demo_app.follow_top_camera
    print(f"[verify_follow_top_camera_motion] initial={_snapshot(controller)}")

    demo_app.move_follow_top_camera_to_stage_xy(-2200.0, 8400.0, bind_viewport=False, duration_sec=2.0)
    print(f"[verify_follow_top_camera_motion] move1_command={_snapshot(controller)}")

    checkpoints = (0, 15, 30, 45, 60)
    for frame_index in range(max(checkpoints) + 1):
        await omni.kit.app.get_app().next_update_async()
        if frame_index in checkpoints:
            print(f"[verify_follow_top_camera_motion] move1_frame_{frame_index}={_snapshot(controller)}")

    demo_app.move_follow_top_camera_to_stage_xy(-1800.0, 7600.0, bind_viewport=False, duration_sec=2.0)
    print(f"[verify_follow_top_camera_motion] move2_command={_snapshot(controller)}")
    checkpoints = (0, 10, 20, 30, 45, 60, 75, 90)
    for frame_index in range(max(checkpoints) + 1):
        await omni.kit.app.get_app().next_update_async()
        if frame_index in checkpoints:
            print(f"[verify_follow_top_camera_motion] move2_frame_{frame_index}={_snapshot(controller)}")

    cooldown_checkpoints = (0, 15, 30, 45, 60, 75)
    for frame_index in range(max(cooldown_checkpoints) + 1):
        await omni.kit.app.get_app().next_update_async()
        if frame_index in cooldown_checkpoints:
            print(f"[verify_follow_top_camera_motion] expire_frame_{frame_index}={_snapshot(controller)}")

    omni.kit.app.get_app().post_quit()


asyncio.ensure_future(main())
